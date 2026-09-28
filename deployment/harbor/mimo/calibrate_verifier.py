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
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def calibrate(*, row_path, source_root, image_binding, output, candidate_patch=None, candidate_wait=0):
    import modal

    if output.exists():
        raise FileExistsError("Calibration evidence directory must be new")
    instance = json.loads(json.loads(row_path.read_text())["extra_info"]["instance_json"])
    binding = json.loads(image_binding.read_text())
    verifier_path = source_root / "examples/mimo_dsh_rl/verifier.py"
    workspace_path = source_root / "uni_agent/tasks/harbor_dsh/mimo_workspace.py"
    verifier_source, workspace_source = verifier_path.read_text(), workspace_path.read_text()
    output.mkdir(parents=True, mode=0o700)
    resources = []
    deadline = time.monotonic() + 600
    report = {
        "schema": "dsh.mimo-verifier-calibration.v1",
        "status": "running",
        "gpu": None,
        "operator_budget_seconds": 600,
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
        # Execute the exact trusted verifier source; hidden tests travel only to
        # the independent original-image verifier, never to the source sandbox.
        code = (
            "import json,sys; p=json.load(sys.stdin); ns={'__name__':'trusted_verifier'}; "
            "exec(p.pop('source'),ns); result=ns['verify'](**p); print(json.dumps(result))"
        )
        result = json.loads(
            run(
                sandbox,
                label,
                ["python3", "-c", code],
                payload={
                    "source": verifier_source,
                    "cwd": instance["cwd"],
                    "base_ref": base_ref,
                    "test_patch": instance["test_patch"],
                    "test_command": instance["test_command"],
                    "timeout": instance["verifier_timeout_sec"],
                },
            )
        )
        (output / (label + ".json")).write_text(json.dumps(result, indent=2) + "\n")
        report["results"][label] = {key: value for key, value in result.items() if key != "test_output"}
        save()
        return result

    save()
    try:
        source = create("source", binding["dsh_image"], private=True)
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
        public_code = (
            "import json,pathlib; p=pathlib.Path('/workspace/repo'); "
            "files=[p/'friends'/n for n in ('models.py','__init__.py','signals.py','managers.py')]; "
            "print(json.dumps({str(f.relative_to(p)):f.read_text() for f in files if f.is_file()}))"
        )
        public_source = json.loads(run(source, "public-source", ["python3", "-c", public_code]))
        (output / "public-source.json").write_text(
            json.dumps(
                {
                    "problem_statement": instance["problem_statement"],
                    "source_files": public_source,
                    "source_sha256": {name: digest(text.encode()) for name, text in public_source.items()},
                    "base_ref": base["base_ref"],
                    "allowed_input": "public problem and original source only",
                },
                indent=2,
            )
            + "\n"
        )
        archive, _ = snapshot(source, "unchanged-workspace")
        baseline = create("baseline-original", binding["original_image"])
        baseline_base = helper(baseline, "baseline", "capture")
        report["baseline_history_admission"] = baseline_base
        if any(baseline_base[key] != base[key] for key in ("base_ref", "base_tree")):
            raise ValueError("Original/DSH repository baseline differs")
        direct = grade(baseline, "baseline-direct", base["base_ref"])
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
                sandbox.terminate(wait=True)
                record["terminated"] = True
            except BaseException as exc:
                record["termination_error"] = type(exc).__name__
                report["status"] = "cleanup_failed"
            save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("row-path", "source-root", "image-binding", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--candidate-patch", type=Path)
    parser.add_argument("--candidate-wait", type=int, default=0)
    args = vars(parser.parse_args())

    def interrupted(_signum, _frame):
        raise TimeoutError("operator_budget_or_signal; no reward")

    for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    signal.alarm(600)
    try:
        print(json.dumps(calibrate(**args), sort_keys=True))
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
