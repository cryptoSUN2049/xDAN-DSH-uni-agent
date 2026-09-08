"""No-model SDK policy canary; synthetic selection comparison is NOT student evaluation."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from examples.dsh.rsi_closed.profile import POLICY_SHA256
from uni_agent.tasks.dsh.memory_artifacts import _directory, _sha
from uni_agent.tasks.dsh.rsi_candidates import Registry, initialize

RUNTIME_SHA256 = "sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb"


def _private_directory(path):
    fd = _directory(path.parent)
    try:
        os.mkdir(path.name, 0o700, dir_fd=fd)
    finally:
        os.close(fd)
    if path.stat().st_mode & 0o777 != 0o700 or path.stat().st_uid != os.getuid():
        raise ValueError("Canary requires actual private local directory permissions")


def _write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError("Canary file permissions not private")
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def stage(root, label, registry, pins_sha, active_sha, public_file, private_file, private_text, exe):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    target = root / label
    _private_directory(target)
    render = subprocess.run(
        [
            sys.executable,
            "-m",
            "examples.dsh.rsi_closed.profile",
            "--registry",
            str(registry),
            "--pins-sha256",
            pins_sha,
            "--active-sha256",
            active_sha,
            "--read-file",
            str(public_file),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    loaded = json.loads(render.stdout)
    report = target / "probe.json"
    calls = [
        {
            "label": "read-public",
            "name": "str_replace_editor",
            "arguments": {"command": "view", "path": str(public_file)},
            "expectedText": "PUBLIC-FACT",
        },
        {"label": "inspect-list", "name": "cordis_inspect_list", "arguments": {}, "expectedText": "providers"},
        {
            "label": "deny-private",
            "name": "str_replace_editor",
            "arguments": {"command": "view", "path": str(private_file)},
        },
        {
            "label": "deny-write",
            "name": "str_replace_editor",
            "arguments": {
                "command": "str_replace",
                "path": str(public_file),
                "old_str": "PUBLIC-FACT",
                "new_str": "modified",
            },
        },
        {
            "label": "deny-code",
            "name": "cordis_define",
            "arguments": {"pluginId": "forbidden", "code": {"host": "return 1"}},
        },
        {"label": "deny-shell", "name": "bash", "arguments": {"command": "echo forbidden"}},
    ]
    patch = loaded["patch"]
    probe = Path(__file__).resolve().parents[2] / "examples/dsh/rsi_closed/probe.mjs"
    patch.append(
        {
            "insert": [
                {
                    "id": "rsi-canary-probe",
                    "name": probe.as_uri(),
                    "config": {
                        "report": str(report),
                        "calls": calls,
                        "forbiddenText": private_text,
                        "candidateSha256": loaded["selection"]["candidate_sha256"],
                        "policySha256": loaded["policy_sha256"],
                    },
                }
            ]
        }
    )
    patch_path = target / "canary.patch.json"
    _write(patch_path, patch)
    config = DeepSeekHarnessConfig(
        provider="deepseek-official",
        model="unused-no-model",
        profile="sdk-minimal",
        patches=(str(patch_path),),
        cwd=str(target),
        runtime_cwd=str(target),
        dsh_bin=exe,
        dsh_home=str(target / "home"),
        initialize_timeout_seconds=60,
        shutdown_timeout_seconds=10,
        base_url="http://127.0.0.1:1",
        api_key="unused-no-model",
        env={"DSH_TELEMETRY_DISABLED": "1"},
    )
    with DeepSeekHarness(config):
        deadline = time.monotonic() + 30
        while not report.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("RSI trusted runtime probe did not finish")
            time.sleep(0.1)
    value = json.loads(report.read_text())
    value.update(
        active_sha256=active_sha,
        stage=label,
        selection_loaded_in_new_python=True,
        policy_sha256=loaded["policy_sha256"],
        patch_sha256=_sha(patch_path.read_bytes()),
        probe_sha256=_sha(probe.read_bytes()),
        raw_probe_sha256=_sha(report.read_bytes()),
        read_file_hashes=loaded["read_files"],
    )
    if (
        value.get("candidateSha256") != loaded["selection"]["candidate_sha256"]
        or value.get("policySha256") != loaded["policy_sha256"]
    ):
        raise ValueError("Probe candidate identity mismatch")
    return value


def run(output, exe=None):
    output = Path(output).absolute()
    if exe:
        runtime = Path(exe)
    else:
        from deepseek_harness_runtime import bundled_runtime_path

        runtime = Path(bundled_runtime_path())
    runtime_digest = _sha(runtime.read_bytes())
    packages = {}
    for label, package in {"sdk": "deepseek-harness-sdk", "runtime": "deepseek-harness-runtime-bin"}.items():
        try:
            packages[label] = version(package)
        except PackageNotFoundError:
            if not exe:
                raise
            packages[label] = "source-checkout-no-distribution-metadata"
    fixed = not exe and runtime_digest == RUNTIME_SHA256 and set(packages.values()) == {"0.1.3a2"}
    if not exe and not fixed:
        raise ValueError("Fixed runtime version/hash mismatch")
    _private_directory(output)
    public = output / "public.txt"
    private = output / "private.txt"
    public.write_text("PUBLIC-FACT\n")
    private_text = "CANARY-SECRET-" + uuid.uuid4().hex
    private.write_text(private_text)
    public.chmod(0o600)
    private.chmod(0o600)
    if any(path.stat().st_mode & 0o777 != 0o600 for path in (public, private)):
        raise ValueError("Canary input permissions not private")
    identity = "canary-" + uuid.uuid4().hex
    pins = {
        key: _sha((identity + "-SYNTHETIC-" + key).encode())
        for key in ["model_sha256", "base_harness_sha256", "devset_sha256", "verifier_sha256"]
    }
    pins.update(
        runtime_sha256=runtime_digest, evolution_run_id=identity, case_ids=["synthetic-a", "synthetic-b"], max_tokens=2
    )
    registry_root = output / "synthetic-selection-only"
    parent_spec = {"schema": "dsh.rsi-profile.v1", "profile": "sdk-minimal", "allowed_tools": ["str_replace_editor"]}
    initial = initialize(registry_root, parent_spec, pins)
    registry = Registry(registry_root, initial["pins_sha256"])
    child = registry.register(
        {**parent_spec, "allowed_tools": ["cordis_inspect_list", "str_replace_editor"]}, initial["candidate_sha256"]
    )
    parent = stage(
        output,
        "parent",
        registry_root,
        initial["pins_sha256"],
        initial["active_sha256"],
        public,
        private,
        private_text,
        exe,
    )
    comparison = {
        "schema": "dsh.rsi-development-comparison.v1",
        "pins_sha256": initial["pins_sha256"],
        "parent_sha256": initial["candidate_sha256"],
        "candidate_sha256": child,
        "cases": [
            {
                "case_id": name,
                **{
                    side: {
                        "finished": True,
                        "eligible": True,
                        "reward": float(side == "candidate"),
                        "tokens": 1,
                        "receipt_sha256": _sha((identity + "-SYNTHETIC-" + name + side).encode()),
                    }
                    for side in ["parent", "candidate"]
                },
            }
            for name in pins["case_ids"]
        ],
    }
    receipt = registry_root / "synthetic-comparison-not-student.json"
    _write(receipt, comparison)
    selected = registry.promote(child, receipt, _sha(receipt.read_bytes()), initial["active_sha256"])
    candidate = stage(
        output,
        "candidate",
        registry_root,
        initial["pins_sha256"],
        selected["active_sha256"],
        public,
        private,
        private_text,
        exe,
    )
    restored = registry.rollback(selected["active_sha256"])
    rollback = stage(
        output,
        "rollback",
        registry_root,
        initial["pins_sha256"],
        restored["active_sha256"],
        public,
        private,
        private_text,
        exe,
    )
    stages = [parent, candidate, rollback]
    errors = []
    for index, value in enumerate(stages):
        results = value.get("results", [])
        if len(results) != 6 or [r.get("isError") for r in results] != [False, index != 1, True, True, True, True]:
            errors.append(value["stage"] + ": unexpected actual tool results")
        elif not results[0]["expectedTextPresent"] or (index == 1 and not results[1]["expectedTextPresent"]):
            errors.append(value["stage"] + ": missing successful observation")
        if len(results) == 6 and any(not results[i]["policyDenied"] for i in [2, 3, 4]):
            errors.append(value["stage"] + ": expected explicit policy denial")
        if len(results) == 6 and index != 1 and not results[1]["policyDenied"]:
            errors.append(value["stage"] + ": inspect not denied by selected policy")
        if not {"str_replace_editor", "cordis_inspect_list", "cordis_define"} <= set(value.get("inventory", [])):
            errors.append(value["stage"] + ": missing actual fixed tool inventory")
        if any(r.get("forbiddenTextPresent") for r in results):
            errors.append(value["stage"] + ": secret leakage")
        if any(name in value.get("inventory", []) for name in ["bash", "pwsh"]):
            errors.append(value["stage"] + ": shell remains registered")
    if not all(value.get("inventory") == parent.get("inventory") for value in stages):
        errors.append("Unexpected global inventory change")
    if public.read_text() != "PUBLIC-FACT\n":
        errors.append("Public source mutated")
    report = {
        "schema": "dsh.rsi-runtime-policy-canary.v1",
        "training": False,
        "model_evaluation": False,
        "synthetic_selection_comparison": True,
        "fixed_runtime_verified": fixed,
        "runtime_sha256": runtime_digest,
        "runtime_packages": packages,
        "policy_sha256": POLICY_SHA256,
        "stages": stages,
        "passed": not errors,
        "errors": errors,
        "scope": "actual SDK tool calls; synthetic registry transition; no student rollout or RL admission",
    }
    _write(output / "result.json", report)
    if errors:
        raise ValueError("RSI runtime policy canary failed; see result.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--exe", help="Explicit source-wrapper diagnostic; never counts as fixed Linux runtime verification"
    )
    args = parser.parse_args()
    run(args.output, args.exe)
    print(json.dumps({"report": str(args.output.absolute() / "result.json")}))


if __name__ == "__main__":
    main()
