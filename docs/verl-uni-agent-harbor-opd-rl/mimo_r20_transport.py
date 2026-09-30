"""Bounded same-host SSH authorization/spec preparation and real HTTP forwarding probe."""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path

DEADLINE = 1790759992
PRIVATE = Path("/root/mimo-private")
BASE = Path("/workspace/mimo-dsh-rl-20260928")
PORTS = dict(control=38880, worker=38881, model=38882, ingress=38883, remote_control=38780, remote_worker=38781)


def write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def occupied():
    result = []
    for port in PORTS.values():
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                result.append(port)
    return result


def authorize():
    if not 1800 < DEADLINE - time.time() <= 14400 or occupied():
        raise ValueError("Authorized window or dedicated ports unavailable")
    folder = PRIVATE / "cohost-r20"
    folder.mkdir(mode=0o700, exist_ok=False)
    known = PRIVATE / "cohost-r19/known_hosts"
    if sha(known) != "1713b5f13a0eee60d07fad9de5cd1ac099855fadcada95dc29e812099ba7d793":
        raise ValueError("Previously verified same-host host key changed")
    write_new(folder / "known_hosts", known.read_bytes())
    key = folder / "loopback-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "mimo-r20-loopback-only", "-f", str(key)],
        check=True,
        timeout=15,
    )
    public = key.with_suffix(".pub").read_text().strip()
    options = (
        'from="127.0.0.1",restrict,port-forwarding,permitopen="172.24.0.2:*",'
        'permitlisten="127.0.0.1:38780",permitlisten="127.0.0.1:38781",command="/bin/false"'
    )
    entry = (options + " " + public + "\n").encode()
    path = Path("/root/.ssh/authorized_keys")
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        with os.fdopen(os.dup(fd), "rb") as stream:
            before = stream.read()
        if b"mimo-r20-loopback-only" in before or before and not before.endswith(b"\n"):
            raise ValueError("Refuse existing R20 entry or non-newline file")
        write_new(folder / "authorized_keys_before.private", before)
        os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, entry)
        os.fsync(fd)
    finally:
        os.close(fd)
    report = dict(
        schema="mimo.r20-scoped-ssh-authorization.v1",
        at=time.time(),
        deadline_unix=DEADLINE,
        ssh_key=str(key),
        known_hosts=str(folder / "known_hosts"),
        authorized_entry_sha256=hashlib.sha256(entry).hexdigest(),
        before_sha256=hashlib.sha256(before).hexdigest(),
        after_sha256=sha(path),
        other_bytes_preserved=path.read_bytes() == before + entry,
        options=options,
        private_credentials_printed=False,
    )
    write_new(folder / "authorization.json", (json.dumps(report, indent=2) + "\n").encode())
    return report


def prepare_spec(stage, task_dir, image_digest):
    from deployment.services.harbor_run_controller import RunSpec, digest
    from examples.harbor.prepare_m2_training import task_digest
    from uni_agent.tasks.harbor_dsh.mimo import load_mimo_binding

    if (
        not stage.startswith("r20")
        or not stage.replace("-", "").isalnum()
        or not 1800 < DEADLINE - time.time() <= 14400
    ):
        raise ValueError("Invalid stage/window")
    raw = (PRIVATE / "run-spec-r19.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != "5951ccbe2ab4c29705bed8655a949efafa598c16cd26670c2791b0544e6e1e33":
        raise ValueError("Base spec changed")
    value = json.loads(raw)
    binding = load_mimo_binding(task_dir / "mimo-binding.json")
    if binding.image_binding.dsh_image.rsplit("@", 1)[1] != image_digest:
        raise ValueError("Task immutable image mismatch")
    run_id = "mimo9b-" + binding.task_id.rsplit("-", 1)[1] + "-" + stage
    value.update(
        run_id=run_id,
        controller_id="mimo-controller-" + stage,
        worker_id="mimo-worker-" + stage,
        deadline_unix=DEADLINE,
        root=str(PRIVATE / ("controller-" + stage)),
        task_dir=str(task_dir),
        registration_token_file=str(PRIVATE / ("registration-token-" + stage)),
        worker_token_file=str(PRIVATE / ("worker-token-" + stage)),
        ssh_key=str(PRIVATE / "cohost-r20/loopback-key"),
        known_hosts=str(PRIVATE / "cohost-r20/known_hosts"),
        control_port=PORTS["control"],
        worker_port=PORTS["worker"],
        model_port=PORTS["model"],
        remote_control_port=PORTS["remote_control"],
        remote_worker_port=PORTS["remote_worker"],
        max_concurrent_jobs=2,
    )
    value["modal_ingress"]["listen_port"] = PORTS["ingress"]
    value["policy_template"]["dsh_release"]["image_digest"] = image_digest
    value["policy_template"]["task_refs"] = [
        dict(id="mimo-code-" + binding.task_id, version="v1", sha256=task_digest(task_dir))
    ]
    spec = RunSpec.model_validate(value)
    if spec.root.exists():
        raise ValueError("Stage controller output already exists")
    for name in ("registration_token_file", "worker_token_file"):
        write_new(Path(getattr(spec, name)), secrets.token_hex(32).encode())
    path = PRIVATE / ("run-spec-" + stage + ".json")
    write_new(path, json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode())
    return dict(
        schema="mimo.r20-spec-preparation.v1",
        run_id=run_id,
        stage=stage,
        spec_path=str(path),
        spec_file_sha256=sha(path),
        run_spec_sha256=digest(spec.model_dump(mode="json")),
        task_ref=spec.policy_template["task_refs"][0],
        deadline_unix=DEADLINE,
    )


async def probe(spec_path):
    from aiohttp import ClientSession, ClientTimeout, web

    from deployment.services.harbor_run_controller import HarborRunController, RunSpec, create_app, digest, read_token

    if occupied() or not 600 < DEADLINE - time.time() <= 14400:
        raise ValueError("Probe ports/window unavailable")
    original = RunSpec.model_validate_json(spec_path.read_bytes())
    value = original.model_dump(mode="json")
    value.update(
        run_id="mimo-r20-http-probe",
        controller_id="mimo-r20-probe-controller",
        worker_id="mimo-r20-probe-worker",
        root=str(PRIVATE / "controller-r20-probe"),
    )
    spec = RunSpec.model_validate(value)
    token = read_token(spec.registration_token_file)
    worker_token = read_token(spec.worker_token_file)
    nonce = secrets.token_hex(16)
    model_auth = "Bearer probe-" + secrets.token_hex(16)
    payload = json.dumps({"nonce": nonce}).encode()
    counters = dict(upstream_requests=0, accepted=0, invalid_session=0)

    async def upstream(request):
        counters["upstream_requests"] += 1
        if request.path != "/sessions/r20-proof-session/v1/chat/completions":
            counters["invalid_session"] += 1
            raise web.HTTPNotFound()
        if request.headers.get("Authorization") != model_auth or await request.read() != payload:
            raise web.HTTPBadRequest()
        counters["accepted"] += 1
        return web.json_response({"nonce": nonce})

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", upstream)
    upstream_runner = web.AppRunner(app, access_log=None)
    controller = HarborRunController(spec)
    controller_runner = web.AppRunner(create_app(controller), access_log=None)
    checks = {}
    started = time.time()
    try:
        await upstream_runner.setup()
        site = web.TCPSite(upstream_runner, "172.24.0.2", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        await controller_runner.setup()
        await web.TCPSite(controller_runner, "127.0.0.1", spec.control_port).start()
        await controller.start()
        async with ClientSession(timeout=ClientTimeout(total=40)) as client:
            base = f"http://127.0.0.1:{spec.remote_control_port}/v1/runs/{spec.run_id}"
            for label, headers, expected in [
                ("control_no_auth", {}, 401),
                ("control_wrong_auth", {"Authorization": "Bearer wrong"}, 401),
                ("control_auth", {"Authorization": "Bearer " + token}, 200),
            ]:
                async with client.get(base + "/status", headers=headers) as response:
                    checks[label] = response.status == expected
            registration = dict(
                gateway_host="172.24.0.2", gateway_port=port, run_spec_sha256=digest(spec.model_dump(mode="json"))
            )
            async with client.post(
                base + "/gateway",
                headers={"Authorization": "Bearer " + token},
                json={**registration, "run_spec_sha256": "sha256:" + "0" * 64},
            ) as response:
                checks["registration_wrong_sha"] = response.status == 409
            async with client.post(
                base + "/gateway", headers={"Authorization": "Bearer " + token}, json=registration
            ) as response:
                checks["registration_accepted"] = response.status == 200
                await response.read()
            worker = f"http://127.0.0.1:{spec.remote_worker_port}/v1/jobs/absent-proof-job"
            for label, headers, expected in [
                ("worker_no_auth", {}, 401),
                ("worker_wrong_auth", {"Authorization": "Bearer wrong"}, 401),
                ("worker_auth_missing_job", {"Authorization": "Bearer " + worker_token}, 404),
            ]:
                async with client.get(worker, headers=headers) as response:
                    checks[label] = response.status == expected
            public = spec.modal_ingress.origin
            async with client.post(
                public + "/disabled", data=payload, headers={"Authorization": model_auth}
            ) as response:
                checks["public_disabled_path"] = response.status == 404
            async with client.post(
                public + "/sessions/wrong-session/v1/chat/completions",
                data=payload,
                headers={"Authorization": model_auth},
            ) as response:
                checks["public_unknown_session"] = response.status == 404
            async with client.post(
                public + "/sessions/r20-proof-session/v1/chat/completions",
                data=payload,
                headers={"Authorization": model_auth},
            ) as response:
                checks["public_model_body_auth_roundtrip"] = (
                    response.status == 200 and (await response.json()).get("nonce") == nonce
                )
        if not all(checks.values()) or counters != dict(upstream_requests=2, accepted=1, invalid_session=1):
            raise ValueError("Production cohost proof incomplete")
    finally:
        try:
            await controller_runner.cleanup()
        finally:
            try:
                await controller.close()
            finally:
                await upstream_runner.cleanup()
    checks.update(
        public_model_forward=checks["public_model_body_auth_roundtrip"],
        reverse_control_auth=checks["control_auth"],
        reverse_worker_auth=checks["worker_auth_missing_job"],
        bad_token_rejected=checks["control_wrong_auth"] and checks["worker_wrong_auth"],
        unknown_session_rejected=checks["public_unknown_session"],
        disabled_path_rejected=checks["public_disabled_path"],
    )
    report = dict(
        schema="mimo.r20-cohost-http-probe.v1",
        status="passed",
        started_at=started,
        finished_at=time.time(),
        checks=checks,
        counters=counters,
        ports=PORTS,
        actual_stage_spec_sha256=sha(spec_path),
        probe_spec_sha256=digest(spec.model_dump(mode="json")),
        gateway_host="172.24.0.2",
        ssh_host="127.0.0.1",
        ssh_port=22,
        deadline_unix=DEADLINE,
        cleanup_ports_occupied=occupied(),
        cleaned_up=not occupied(),
        jobs_submitted=0,
        gpu_training_started=False,
        training_started=False,
        synthetic_upstream=True,
        source_sha256={
            name: sha(BASE / "run-src-r19" / name)
            for name in (
                "deployment/services/harbor_run_controller.py",
                "deployment/services/harbor_tunnel.py",
                "deployment/services/harbor_modal_ingress.py",
                "uni_agent/tasks/harbor_dsh/worker_http.py",
            )
        },
    )
    if not report["cleaned_up"]:
        raise ValueError("Probe cleanup incomplete")
    write_new(BASE / "integration-check/r20-cohost-http-probe.json", (json.dumps(report, indent=2) + "\n").encode())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("authorize", "prepare-spec", "probe"))
    parser.add_argument("--stage")
    parser.add_argument("--task-dir", type=Path)
    parser.add_argument("--image-digest")
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()
    if args.mode == "authorize":
        result = authorize()
    elif args.mode == "prepare-spec":
        result = prepare_spec(args.stage, args.task_dir, args.image_digest)
    else:
        result = asyncio.run(asyncio.wait_for(probe(args.spec), timeout=120))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
