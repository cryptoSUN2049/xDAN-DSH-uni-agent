"""Bounded same-host SSH authorization/spec preparation and real HTTP forwarding probe."""

import argparse
import asyncio
import hashlib
import json
import os
import runpy
import secrets
import socket
import subprocess
import time
from pathlib import Path

DEADLINE = 1790759992
PRIVATE = Path("/root/mimo-private")
BASE = Path("/workspace/mimo-dsh-rl-20260928")
PORTS = dict(control=38880, worker=38881, model=38882, ingress=38883, remote_control=38780, remote_worker=38781)


def read_authorization(path, expected_sha256):
    helper = runpy.run_path(str(Path(__file__).with_name("mimo_r20_operator.py")))
    return helper["load_authorization"](path, expected_sha256)


def window(authorization, minimum):
    deadline = DEADLINE if authorization is None else authorization["deadline_unix"]
    maximum = 14400 if authorization is None else authorization["max_run_seconds"]
    now = time.time()
    if authorization is not None and now < authorization["allocated_at_unix"]:
        raise ValueError("Authorization window has not started")
    if not minimum < deadline - now <= maximum:
        raise ValueError("Authorization window expired or insufficient")
    return deadline


def validate_local_host(authorization, *, host_public_key=None):
    """Match the separately approved key to this sshd and prove the node IPv4 is local."""
    if "pod_id" in authorization and os.environ.get("RUNPOD_POD_ID") != authorization["pod_id"]:
        raise ValueError("Current Pod differs from host authorization")
    known = Path(authorization["known_hosts_path"])
    if sha(known) != authorization["known_hosts_sha256"]:
        raise ValueError("Fresh host key SHA differs")
    key = Path("/etc/ssh/ssh_host_ed25519_key.pub") if host_public_key is None else host_public_key
    algorithm, material = key.read_text().split()[:2]
    fields = [line.split() for line in known.read_text().splitlines() if line and not line.startswith("#")]
    if len(fields) != 1 or fields[0] not in [
        ["127.0.0.1", algorithm, material],
        ["[127.0.0.1]:22", algorithm, material],
    ]:
        raise ValueError("Approved loopback host key does not match actual sshd")
    with socket.socket() as probe:
        probe.bind((authorization["gateway_host"], 0))


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


def authorize(*, authorization=None):
    deadline = window(authorization, 1800)
    if occupied():
        raise ValueError("Authorized window or dedicated ports unavailable")
    folder = PRIVATE / ("cohost-r20" if authorization is None else "cohost-r21")
    if authorization is None:
        known = PRIVATE / "cohost-r19/known_hosts"
        if sha(known) != "1713b5f13a0eee60d07fad9de5cd1ac099855fadcada95dc29e812099ba7d793":
            raise ValueError("Previously verified same-host host key changed")
    else:
        validate_local_host(authorization)
        known = Path(authorization["known_hosts_path"])
    folder.mkdir(mode=0o700, exist_ok=False)
    write_new(folder / "known_hosts", known.read_bytes())
    key = folder / "loopback-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "mimo-r20-loopback-only", "-f", str(key)],
        check=True,
        timeout=15,
    )
    public = key.with_suffix(".pub").read_text().strip()
    gateway = "172.24.0.2" if authorization is None else authorization["gateway_host"]
    options = (
        f'from="127.0.0.1",restrict,port-forwarding,permitopen="{gateway}:*",'
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
        deadline_unix=deadline,
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


def prepare_spec(stage, task_dir, image_digest, *, authorization=None, base_spec_path=None, base_spec_sha256=None):
    from deployment.services.harbor_run_controller import RunSpec, digest
    from examples.harbor.prepare_m2_training import task_digest
    from uni_agent.tasks.harbor_dsh.mimo import load_mimo_binding

    if not stage.startswith("r20") or not stage.replace("-", "").isalnum():
        raise ValueError("Invalid stage/window")
    if authorization is not None and stage != authorization["stage"]:
        raise ValueError("Invalid authorization stage/window")
    base_path = PRIVATE / "run-spec-r19.json" if authorization is None else base_spec_path
    expected = (
        "5951ccbe2ab4c29705bed8655a949efafa598c16cd26670c2791b0544e6e1e33"
        if authorization is None
        else base_spec_sha256
    )
    if base_path is None or expected is None or not Path(base_path).is_absolute() or Path(base_path).is_symlink():
        raise ValueError("Explicit bound base spec required")
    raw = Path(base_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Base spec changed")
    try:
        deadline = window(authorization, 1800)
    except ValueError as error:
        raise ValueError("Invalid stage/window") from error
    value = RunSpec.model_validate_json(raw).model_dump(mode="json")
    if authorization is not None:
        helper = runpy.run_path(str(Path(__file__).with_name("mimo_r20_operator.py")))
        release = value["policy_template"]["dsh_release"]
        pins = dict(
            source_sha=helper["DSH_SOURCE"],
            sdk_sha256=helper["SDK_SHA"],
            runtime_sha256=helper["RUNTIME_SHA"],
            patch_sha256s=[],
            platform="linux/amd64",
            profile="sdk-minimal",
        )
        if any(release.get(key) != expected for key, expected in pins.items()):
            raise ValueError("New base spec changed pinned DSH provenance")
    binding = load_mimo_binding(task_dir / "mimo-binding.json")
    if binding.image_binding.dsh_image.rsplit("@", 1)[1] != image_digest:
        raise ValueError("Task immutable image mismatch")
    run_id = "mimo9b-" + binding.task_id.rsplit("-", 1)[1] + "-" + stage
    value.update(
        run_id=run_id,
        controller_id="mimo-controller-" + stage,
        worker_id="mimo-worker-" + stage,
        deadline_unix=deadline,
        root=str(PRIVATE / ("controller-" + stage)),
        task_dir=str(task_dir),
        registration_token_file=str(PRIVATE / ("registration-token-" + stage)),
        worker_token_file=str(PRIVATE / ("worker-token-" + stage)),
        ssh_host="127.0.0.1",
        ssh_port=22,
        ssh_user="root",
        ssh_key=str(PRIVATE / ("cohost-r20" if authorization is None else "cohost-r21") / "loopback-key"),
        known_hosts=str(PRIVATE / ("cohost-r20" if authorization is None else "cohost-r21") / "known_hosts"),
        control_port=PORTS["control"],
        worker_port=PORTS["worker"],
        model_port=PORTS["model"],
        remote_control_port=PORTS["remote_control"],
        remote_worker_port=PORTS["remote_worker"],
        max_concurrent_jobs=2,
    )
    value["modal_ingress"]["listen_port"] = PORTS["ingress"]
    if authorization is not None:
        value["policy_template"]["gateway_host"] = authorization["gateway_host"]
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
        deadline_unix=deadline,
        base_spec_path=str(base_path),
        base_spec_sha256=expected,
    )


async def probe(spec_path, *, authorization=None, authorization_sha256=None):
    from aiohttp import ClientSession, ClientTimeout, web

    from deployment.services.harbor_run_controller import HarborRunController, RunSpec, create_app, digest, read_token

    deadline = window(authorization, 600)
    if occupied():
        raise ValueError("Probe ports/window unavailable")
    original = RunSpec.model_validate_json(spec_path.read_bytes())
    gateway = "172.24.0.2" if authorization is None else authorization["gateway_host"]
    if authorization is not None:
        validate_local_host(authorization)
        if original.deadline_unix != deadline or original.policy_template["gateway_host"] != gateway:
            raise ValueError("Probe spec/authorization differs")
        from deployment.services import harbor_modal_ingress, harbor_run_controller, harbor_tunnel
        from uni_agent.tasks.harbor_dsh import worker_http

        helper = runpy.run_path(str(Path(__file__).with_name("mimo_r20_operator.py")))
        manifest = helper["read_bound"](
            BASE / "integration-check/source-r20-manifest.json", helper["SOURCE_MANIFEST_SHA"]
        )
        for module in (harbor_run_controller, harbor_tunnel, harbor_modal_ingress, worker_http):
            relative = module.__name__.replace(".", "/") + ".py"
            actual = Path(module.__file__).resolve()
            if (
                actual != (BASE / "run-src-r20" / relative).resolve()
                or sha(actual) != manifest["files"][relative]["sha256"]
            ):
                raise ValueError("Probe imported a different frozen production source")
    value = original.model_dump(mode="json")
    probe_identity = "r20" if authorization is None else authorization["stage"]
    value.update(
        run_id=f"mimo-{probe_identity}-http-probe",
        controller_id=f"mimo-{probe_identity}-probe-controller",
        worker_id=f"mimo-{probe_identity}-probe-worker",
        root=str(PRIVATE / f"controller-{probe_identity}-probe"),
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
        site = web.TCPSite(upstream_runner, gateway, 0)
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
                gateway_host=gateway, gateway_port=port, run_spec_sha256=digest(spec.model_dump(mode="json"))
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
        gateway_host=gateway,
        ssh_host="127.0.0.1",
        ssh_port=22,
        deadline_unix=deadline,
        authorization_sha256=authorization_sha256,
        cleanup_ports_occupied=occupied(),
        cleaned_up=not occupied(),
        jobs_submitted=0,
        gpu_training_started=False,
        training_started=False,
        synthetic_upstream=True,
        source_sha256={
            name: sha(BASE / ("run-src-r19" if authorization is None else "run-src-r20") / name)
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
    write_new(
        BASE / f"integration-check/{probe_identity}-cohost-http-probe.json",
        (json.dumps(report, indent=2) + "\n").encode(),
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("authorize", "prepare-spec", "probe"))
    parser.add_argument("--stage")
    parser.add_argument("--task-dir", type=Path)
    parser.add_argument("--image-digest")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--authorization-sha256")
    parser.add_argument("--base-spec", type=Path)
    parser.add_argument("--base-spec-sha256")
    args = parser.parse_args()
    if bool(args.authorization) != bool(args.authorization_sha256):
        parser.error("Both authorization path and SHA are required")
    authorization = (
        None if args.authorization is None else read_authorization(args.authorization, args.authorization_sha256)
    )
    if args.mode == "authorize":
        result = authorize(authorization=authorization)
    elif args.mode == "prepare-spec":
        result = prepare_spec(
            args.stage,
            args.task_dir,
            args.image_digest,
            authorization=authorization,
            base_spec_path=args.base_spec,
            base_spec_sha256=args.base_spec_sha256,
        )
    else:
        result = asyncio.run(
            asyncio.wait_for(
                probe(args.spec, authorization=authorization, authorization_sha256=args.authorization_sha256),
                timeout=120,
            )
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
