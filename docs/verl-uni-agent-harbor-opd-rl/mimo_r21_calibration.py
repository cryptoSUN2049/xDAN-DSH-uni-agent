"""Run bounded, CPU-only MiMo verifier controls on real immutable images.

This operator calibration never calls a model or creates training rewards.
Source test bytes/command/timeouts remain unchanged; an outer deadline is an
infrastructure failure. An optional candidate patch is independently authored
from public problem/source only, and never receives the verifier test patch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path("/workspace/mimo-dsh-rl-20260928")
SOURCE = BASE / "run-src-r20"
SOURCE_COMMIT = "1ccc1640c0f34ba5f515d3613fac6a278bd38f4c"
SOURCE_MANIFEST = "99ac03f55d4eaeebc63d2ba466452fef2af7a51af289fc135d5051dadca0591f"
WORKSPACE_SHA = "faba54386d324f0fc25b76bed6f0d81aa8f03cf926ad9c542214a6ae71b4409d"
VERIFIER_SHA = "12a6f9d3a849ff66168269f800f63325077d76a61942e9315d8335eb6d63c371"
DATA_REVISION = "639865fd3374018d6cb29b9fb82dd531406fcf5f"
MEASURED_DSH = {
    "dsh_revision": "b2369692ea530007075ebcd18d39fdba0bbd3982",
    "source_commit": "c51f6fc7dad24fd03fdc090741bc30d07488b574",
    "profile": "sdk-minimal",
    "python_distribution_version": "0.1.3a2",
    "runner_sha256": "a122de903b1775231f6ff6f70762b78500819d6c9ce8a3323b729dac64468732",
    "runtime_binary_sha256": "d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb",
    "runtime_rg_sha256": "193906679498de4d939345b937fa24e0e69a03c244bd70c859f5e41232713f21",
}


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bound(path, expected):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "Bound input must be a regular file")
    raw = path.read_bytes()
    require(digest(raw).removeprefix("sha256:") == expected.removeprefix("sha256:"), "Bound input SHA differs")
    return raw


def validate_inputs(config, now):
    require(os.environ.get("CUDA_VISIBLE_DEVICES") == "", "CPU-only operator required")
    auth = json.loads(bound(config["authorization_path"], config["authorization_sha256"]))
    require(
        auth["schema"] == "mimo.recovery-authorization.v1"
        and auth["pod_id"] == "vo6u0t8x398bnm"
        and auth["allocated_at_unix"] == 1790791473
        and auth["deadline_unix"] == 1790813073
        and auth["max_run_seconds"] == 21600
        and auth["cleanup_reserve_seconds"] == 180
        and auth["stage"] == "r20f"
        and auth["allocated_at_unix"] <= now < auth["deadline_unix"] - 780,
        "Recovery authorization/window differs or insufficient calibration reserve",
    )
    row = json.loads(bound(config["row_path"], config["row_sha256"]))
    instance = json.loads(row["extra_info"]["instance_json"])
    package = json.loads(bound(config["task_package_manifest"], config["task_package_manifest_sha256"]))
    binding = json.loads(bound(config["image_binding"], config["image_binding_sha256"]))
    public = json.loads(bound(config["public_source_path"], config["public_source_sha256"]))
    candidate = bound(config["candidate_patch"], config["candidate_sha256"])
    provenance = json.loads(bound(config["candidate_provenance"], config["candidate_provenance_sha256"]))
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    require(
        instance["instance_id"] == package["task_id"] == "format-code-task-002549"
        and package["source_revision"] == DATA_REVISION
        and package["source_row_hash"] == digest(canonical(row))
        and package["test_patch_sha256"] == digest(instance["test_patch"].encode())
        and row["prompt"] == [{"role": "user", "content": instance["problem_statement"]}]
        and public["problem_statement"] == instance["problem_statement"]
        and provenance["patch_sha256"] == digest(candidate).removeprefix("sha256:")
        and provenance["public_source_sha256"] == config["public_source_sha256"].removeprefix("sha256:")
        and provenance["hidden_test_patch_read_for_authorship"] is False
        and provenance["hidden_test_files_read_for_authorship"] is False
        and provenance["verifier_output_read_for_authorship"] is False,
        "Task/row/public-only candidate provenance differs",
    )
    original = (
        "docker.io/xiaomimimo/mimo-v2.6-rl-oss@sha256:4a04d1bbe8d8edf0f29d13325bdb7bdf838c6b1474374b8e59a59e584b3b906c"
    )
    derived = (
        "ghcr.io/cryptosun2049/mimo-dsh-code-002549@sha256:"
        "951f488e9e4d8e4218a2c29e20b18a80ce4e509be0d39a88b0c887961ea360bf"
    )
    require(
        package["original_image"] == binding["original_image"] == original
        and package["dsh_image"] == binding["dsh_image"] == derived
        and package["verifier_image"] == binding["verifier_image"] == original,
        "Fixed image identity differs",
    )
    source_manifest = json.loads(bound(BASE / "integration-check/source-r20-manifest.json", SOURCE_MANIFEST))
    require(
        source_manifest["git_commit"] == SOURCE_COMMIT and source_manifest["source_root"] == str(SOURCE),
        "Source identity differs",
    )
    workspace = bound(SOURCE / "uni_agent/tasks/harbor_dsh/mimo_workspace.py", WORKSPACE_SHA)
    verifier = bound(SOURCE / "examples/mimo_dsh_rl/verifier.py", VERIFIER_SHA)
    root = Path(config["task_package_manifest"]).parent
    actual = {}
    for path in sorted((root / "task").rglob("*")):
        require(not path.is_symlink(), "Task contains symlink")
        if path.is_file():
            actual[str(path.relative_to(root))] = digest(path.read_bytes())
    require(actual == package["files"] and len(actual) == 8, "Actual package tree differs")
    native = {name.removeprefix("task/"): sha.removeprefix("sha256:") for name, sha in actual.items()}
    require(package["task_ref"]["sha256"] == digest(canonical(native)), "TaskRef differs")
    require(actual["task/tests/verifier.py"] == digest(verifier), "Packaged verifier differs")
    output = Path(config["output"])
    require(not output.exists() and not output.is_symlink(), "Output must be new")
    return auth, instance, package, binding, workspace.decode(), output


def calibrate(config):
    auth, instance, package, binding, workspace_source, output = validate_inputs(config, time.time())
    import modal

    row_path, source_root = Path(config["row_path"]), SOURCE
    candidate_patch, candidate_wait = Path(config["candidate_patch"]), 0
    package_root = Path(config["task_package_manifest"]).parent
    verifier_path = source_root / "examples/mimo_dsh_rl/verifier.py"
    workspace_path = source_root / "uni_agent/tasks/harbor_dsh/mimo_workspace.py"
    output.mkdir(parents=True, mode=0o700)
    resources = []
    attempt_started = time.time()
    absolute_deadline = min(attempt_started + 600, auth["deadline_unix"] - auth["cleanup_reserve_seconds"])
    deadline = time.monotonic() + absolute_deadline - attempt_started
    report = {
        "schema": "mimo.r20-production-task-calibration.raw.v1",
        "status": "running",
        "gpu": None,
        "operator_budget_seconds": 600,
        "attempt_started_unix": attempt_started,
        "absolute_deadline_unix": absolute_deadline,
        "authorization_path": config["authorization_path"],
        "authorization_sha256": config["authorization_sha256"],
        "source_root": str(SOURCE),
        "source_manifest_sha256": "sha256:" + SOURCE_MANIFEST,
        "current_runtime_commit": SOURCE_COMMIT,
        "workspace_helper_sha256": "sha256:" + WORKSPACE_SHA,
        "packaged_verifier_sha256": "sha256:" + VERIFIER_SHA,
        "immutable_package_manifest_sha256": config["task_package_manifest_sha256"],
        "task_ref": package["task_ref"],
        "data_revision": DATA_REVISION,
        "no_shim": True,
        "private_compatibility_injection": False,
        "max_actual_live_sandboxes": 2,
        "public_source_sha256": config["public_source_sha256"],
        "candidate_provenance_sha256": config["candidate_provenance_sha256"],
        "model_requests": 0,
        "packaged_test_patch_sha256": package["test_patch_sha256"],
        "grade_execution": "exact packaged /tests/test.sh -> python3 /tests/verifier.py CLI, original image",
        "task_id": instance["instance_id"],
        "original_timeout_seconds": instance["verifier_timeout_sec"],
        "original_image": binding["original_image"],
        "dsh_image": binding["dsh_image"],
        "source_hashes": {
            str(p): digest(p.read_bytes()) for p in (row_path, verifier_path, workspace_path, Path(__file__))
        },
        "test_patch_sha256": digest(instance["test_patch"].encode()),
        "test_command": instance["test_command"],
        "resources": resources,
        "results": {},
        "history_policy": "strip",
        "baseline": "not_run",
        "positive_control": "not_provided",
        "scope": "verifier controls only; no training or Gateway acceptance",
    }

    def save():
        temporary = output / "status.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        temporary.replace(output / "status.json")

    def remaining():
        value = int(deadline - time.monotonic())
        if value <= 0:
            raise TimeoutError("operator_budget_exhausted")
        return value

    def run(sandbox, stage, argv, *, payload=None):
        report["stage"] = stage
        save()
        process = sandbox.exec(*argv, timeout=remaining())
        if payload is not None:
            process.stdin.write(json.dumps(payload).encode())
            process.stdin.write_eof()
            process.stdin.drain()
        with ThreadPoolExecutor(max_workers=2) as pool:
            stdout, stderr = pool.submit(process.stdout.read), pool.submit(process.stderr.read)
            code = process.wait()
            out, err = stdout.result(), stderr.result()
        (output / (stage + ".stdout.log")).write_text(out)
        (output / (stage + ".stderr.log")).write_text(err)
        if code != 0:
            raise RuntimeError(f"{stage}: infrastructure exit {code}; no reward")
        return out

    app = modal.App.lookup("mimo-dsh-verifier-calibration", create_if_missing=True)
    allocated = []

    def create(role, image, *, private=False):
        require(sum(not rec["terminated"] for _, rec in allocated) < 2, "Two-live-sandbox limit exceeded")
        kwargs = {"secret": modal.Secret.from_name("mimo-dsh-ghcr-20260928")} if private else {}
        sandbox = modal.Sandbox.create(
            "/bin/sleep",
            "600",
            app=app,
            image=modal.Image.from_registry(image, **kwargs),
            cpu=(1, 1),
            memory=4096,
            timeout=remaining(),
            block_network=True,
        )
        record = {"role": role, "sandbox_id": sandbox.object_id, "image": image, "terminated": False}
        allocated.append((sandbox, record))
        resources.append(record)
        save()
        return sandbox

    def helper(sandbox, role, action, *, python="python3", archive=None, base_ref=None):
        argv = [python, "-c", workspace_source, action, instance["cwd"]]
        argv += ["--history-policy", "strip"]
        if archive:
            argv += ["--archive", archive]
        if base_ref:
            argv += ["--base-ref", base_ref]
        return json.loads(run(sandbox, role + "-" + action, argv))

    def snapshot(source, label):
        remote = "/tmp/" + label + ".tar"
        evidence = helper(source, label, "snapshot", python="/opt/dsh/bin/python", archive=remote)
        path = output / (label + ".tar")
        source.filesystem.copy_to_local(remote, path)
        if digest(path.read_bytes()) != evidence["snapshot_sha256"] or path.stat().st_size != evidence["bytes"]:
            raise ValueError("Snapshot changed in transport")
        report[label] = evidence
        save()
        return path, evidence

    def grade(sandbox, label, base_ref):
        run(
            sandbox,
            label + "-setup",
            [
                "python3",
                "-S",
                "-c",
                "import pathlib; [pathlib.Path(p).mkdir(parents=True,exist_ok=True) "
                "for p in ['/tests','/audit-input','/logs/verifier']]",
            ],
        )
        for name in ("test.sh", "verifier.py", "verification.json", "test.patch"):
            sandbox.filesystem.copy_from_local(package_root / "task/tests" / name, "/tests/" + name)
        identity_code = (
            "import hashlib,json,pathlib,sys; "
            "print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),"
            "'executable':sys.executable,'files':{n:'sha256:'+hashlib.sha256("
            "(pathlib.Path('/tests')/n).read_bytes()).hexdigest() "
            "for n in ['test.sh','verifier.py','verification.json','test.patch']}}))"
        )
        identity = json.loads(run(sandbox, label + "-packaged-readback", ["python3", "-S", "-c", identity_code]))
        require(
            all(identity["files"][n] == package["files"]["task/tests/" + n] for n in identity["files"]),
            "Uploaded verifier files differ",
        )
        require(
            not report.get("original_python_version") or report["original_python_version"] == identity["version"],
            "Original Python changed between controls",
        )
        report["original_python_version"] = identity["version"]
        report.setdefault("packaged_file_readback", {})[label] = identity
        snapshot_label = "candidate-workspace" if label == "candidate-restored" else "unchanged-workspace"
        state = dict(
            cwd=instance["cwd"],
            base_ref=base_ref,
            snapshot_sha256=report[snapshot_label]["snapshot_sha256"],
            gateway_session_id="operator-production-calibration-002549",
        )
        code = (
            "import json,pathlib,sys; pathlib.Path('/audit-input/mimo-state.json').write_text("
            "json.dumps(json.load(sys.stdin))+chr(10))"
        )
        run(sandbox, label + "-operator-state", ["python3", "-S", "-c", code], payload=state)
        run(sandbox, label, ["bash", "/tests/test.sh"])
        receipt_code = (
            "import json,pathlib; p=pathlib.Path('/logs/verifier'); "
            "r=json.loads((p/'mimo-receipt.json').read_text()); "
            "assert json.loads((p/'reward.json').read_text())['reward']==r['reward']; print(json.dumps(r))"
        )
        result = json.loads(run(sandbox, label + "-receipt", ["python3", "-S", "-c", receipt_code]))
        require(
            result["test_patch_sha256"] == package["test_patch_sha256"]
            and result["snapshot_sha256"] == state["snapshot_sha256"]
            and result["base_ref"] == base_ref,
            "Actual verifier receipt differs",
        )
        (output / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n")
        report["results"][label] = {key: value for key, value in result.items() if key != "test_output"}
        save()
        return result

    save()
    try:
        source = create("source", binding["dsh_image"], private=True)
        measured_code = (
            "import json,pathlib; b=json.loads(pathlib.Path('/opt/dsh/build-inputs.json').read_text()); "
            "k=b['lock']; print(json.dumps({n:k[n] for n in ['dsh_revision','profile',"
            "'python_distribution_version']}|{'source_commit':b['source_commit']}))"
        )
        measured = json.loads(run(source, "dsh-build-identity", ["/opt/dsh/bin/python", "-S", "-c", measured_code]))
        smoke = json.loads(run(source, "dsh-offline-smoke", ["/opt/dsh/bin/python", "-B", "/opt/dsh/checks/smoke.py"]))
        measured.update({name: smoke[name] for name in ("runner_sha256", "runtime_binary_sha256", "runtime_rg_sha256")})
        require(
            measured == MEASURED_DSH and smoke["status"] == "passed" and smoke["scope"] == "initialize-shutdown-only",
            "Actual fixed DSH measurement differs",
        )
        report["dsh_release"] = measured
        base = helper(source, "source", "capture", python="/opt/dsh/bin/python")
        report["base"] = base
        history_code = (
            "import json,subprocess,sys; cwd=sys.argv[1]; "
            "run=lambda *a:subprocess.check_output(['git','-C',cwd,*a],text=True,timeout=30).splitlines(); "
            "print(json.dumps({'refs':run('for-each-ref','--format=%(refname) %(objectname)'),"
            "'reachable_outside_head':run('rev-list','--all','--not','HEAD')}))"
        )
        history = json.loads(run(source, "history-audit", ["python3", "-c", history_code, instance["cwd"]]))
        (output / "history-audit.json").write_text(json.dumps(history, indent=2) + "\n")
        report["reachable_outside_head_count"] = len(history["reachable_outside_head"])
        archive, _ = snapshot(source, "unchanged-workspace")
        baseline = create("baseline-original", binding["original_image"])
        baseline_base = helper(baseline, "baseline", "capture")
        report["baseline_history_admission"] = baseline_base
        if any(baseline_base[key] != base[key] for key in ("base_ref", "base_tree")):
            raise ValueError("Original/DSH repository baseline differs")
        direct = grade(baseline, "baseline-direct", base["base_ref"])
        baseline.terminate(wait=True)
        rec = next(rec for box, rec in allocated if box is baseline)
        code = modal.Sandbox.from_id(baseline.object_id).poll()
        require(code is not None, "Independent baseline termination unconfirmed")
        rec.update(terminated=True, independent_modal_poll_returncode=code, observed_unix=time.time())
        save()
        restored = create("restored-original", binding["original_image"])
        restored.filesystem.copy_from_local(archive, "/tmp/unchanged-workspace.tar")
        report["restored_history_admission"] = helper(
            restored, "restored", "restore", archive="/tmp/unchanged-workspace.tar", base_ref=base["base_ref"]
        )
        transported = grade(restored, "baseline-restored", base["base_ref"])
        keys = ("status", "reward", "resolved", "verifier_returncode")
        if any(direct[key] != transported[key] for key in keys):
            raise ValueError("Workspace transport changed the baseline verifier result")
        if direct["status"] != "graded" or direct["reward"] != 0 or direct["verifier_returncode"] == 0:
            raise ValueError("Expected a completed failing baseline control")
        report["baseline_calibration"] = "passed"
        report["baseline"] = "passed"
        save()
        until = min(time.monotonic() + candidate_wait, deadline - 60)
        while candidate_patch and not candidate_patch.exists() and time.monotonic() < until:
            time.sleep(1)
        if candidate_patch and candidate_patch.is_file():
            bound(candidate_patch, config["candidate_sha256"])
            patch = candidate_patch.read_text()
            report["candidate_patch_sha256"] = digest(patch.encode())
            apply_code = (
                "import json,subprocess,sys; p=json.load(sys.stdin); "
                "subprocess.run(['git','-C',p['cwd'],'apply','--whitespace=nowarn','-'],input=p['patch'],text=True,check=True)"
            )
            run(
                source,
                "apply-public-candidate",
                ["python3", "-c", apply_code],
                payload={"cwd": instance["cwd"], "patch": patch},
            )
            changed, _ = snapshot(source, "candidate-workspace")
            restored.filesystem.copy_from_local(changed, "/tmp/candidate-workspace.tar")
            helper(restored, "candidate", "restore", archive="/tmp/candidate-workspace.tar", base_ref=base["base_ref"])
            positive = grade(restored, "candidate-restored", base["base_ref"])
            report["positive_control"] = (
                "passed"
                if positive["status"] == "graded"
                and positive["reward"] == 1
                and positive["resolved"]
                and positive["verifier_returncode"] == 0
                else "candidate_failed"
            )
        report["status"] = "calibration_passed" if report["positive_control"] == "passed" else "controls_incomplete"
    except BaseException as exc:
        report.update(status="infra_error", error_type=type(exc).__name__, error=str(exc)[-1000:])
        raise
    finally:
        for sandbox, record in allocated:
            try:
                if not record["terminated"]:
                    sandbox.terminate(wait=True)
                code = modal.Sandbox.from_id(sandbox.object_id).poll()
                require(code is not None, "Independent cleanup poll still active")
                record.update(terminated=True, independent_modal_poll_returncode=code, observed_unix=time.time())
            except BaseException as exc:
                record["termination_error"] = type(exc).__name__
                report["status"] = "cleanup_failed"
            save()
    report["finished_unix"] = time.time()
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--configuration-sha256", required=True)
    args = parser.parse_args()
    config = json.loads(bound(args.configuration, args.configuration_sha256))

    def interrupted(_signum, _frame):
        raise TimeoutError("operator_budget_or_signal; no reward")

    for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    signal.alarm(600)
    try:
        result = calibrate(config)
        print(json.dumps({"status": result["status"], "output": config["output"], "model_requests": 0}))
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
