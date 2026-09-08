"""Real SDK/tool-runtime canary with no model, GPU, Docker or external API calls."""

import argparse
import hashlib
import json
import os
import time
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from examples.dsh.memory_closed.profile import build_memory_patch
from uni_agent.tasks.dsh.memory_artifacts import freeze_memory_artifact, load_memory_artifact

SOURCE_VERSION = "dsh:b2369692ea530007075ebcd18d39fdba0bbd3982"


def sdk_version():
    try:
        return version("deepseek-harness-sdk")
    except PackageNotFoundError:
        return "source-checkout-no-distribution-metadata"


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def call(label, command, path, *, expected=None, **kwargs):
    return {
        "label": label,
        "name": "str_replace_editor",
        "arguments": {"command": command, "path": str(path), **kwargs},
        "expectedText": expected,
    }


def stage(root, role, chain, reads, write, calls, forbidden, exe):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    run_dir = root / role
    run_dir.mkdir(mode=0o700)
    report = run_dir / "probe.json"
    session = role + "-" + uuid.uuid4().hex
    patch = build_memory_patch(
        role=role,
        chain_id=chain,
        session_id=session,
        source_version=SOURCE_VERSION,
        read_files=reads,
        write_file=write,
    )
    probe = Path(__file__).resolve().parents[2] / "examples/dsh/memory_closed/probe.mjs"
    patch.append(
        {
            "insert": [
                {
                    "id": "memory-policy-canary",
                    "name": probe.as_uri(),
                    "config": {"report": str(report), "calls": calls, "forbiddenText": forbidden},
                }
            ]
        }
    )
    patch_path = run_dir / "closed.patch.json"
    patch_path.write_text(json.dumps(patch))
    patch_path.chmod(0o600)
    config = DeepSeekHarnessConfig(
        provider="deepseek-official",
        model="unused-no-model",
        profile="sdk-minimal",
        patches=(str(patch_path),),
        cwd=str(run_dir),
        runtime_cwd=str(run_dir),
        dsh_bin=exe,
        dsh_home=str(run_dir / "home"),
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
                raise TimeoutError("No trusted runtime probe receipt")
            time.sleep(0.1)
    value = json.loads(report.read_text())
    if value.get("tools") != ["str_replace_editor"]:
        raise ValueError("Unexpected closed profile tool inventory")
    if any(item["forbiddenTextPresent"] for item in value["results"]):
        raise ValueError("Forbidden content leaked")
    value["policy_config_sha256"] = digest(json.dumps(patch[:3], sort_keys=True).encode())
    return session, value


def run(output: Path, exe=None):
    output = output.absolute()
    if output.parent.resolve() != output.parent:
        raise ValueError("Use canonical output parent (on Mac /private/tmp, not /tmp)")
    output.mkdir(mode=0o700)
    inputs = output / "a-inputs"
    inputs.mkdir(mode=0o700)
    secret = inputs / "secret.txt"
    secret_text = "A-SECRET-" + uuid.uuid4().hex
    secret.write_text(secret_text)
    memory = inputs / "memory.txt"
    memory_text = "Remember deployment region: eu-west-test"
    chain = uuid.uuid4().hex
    writer, a = stage(
        output,
        "writer",
        chain,
        [secret, memory],
        memory,
        [
            call("write-memory", "create", memory, file_text=memory_text),
            call("read-memory", "view", memory, expected=memory_text),
            call("deny-input-write", "str_replace", secret, old_str=secret_text, new_str="changed"),
        ],
        None,
        exe,
    )
    if [r["isError"] for r in a["results"]] != [False, False, True] or not a["results"][1]["expectedTextPresent"]:
        raise ValueError("Writer tool policy did not behave as required")
    receipt = freeze_memory_artifact(
        source_root=inputs,
        relative_path="memory.txt",
        expected_source_sha256=digest(memory.read_bytes()),
        source_version=SOURCE_VERSION,
        chain_id=chain,
        writer_session_id=writer,
        max_bytes=4096,
        output_dir=output / "frozen",
    )
    handoff = output / "frozen/memory.bin"
    alias = output / "alias"
    alias.symlink_to(secret)
    hard = output / "hard"
    os.link(secret, hard)
    calls = [
        call("read-handoff", "view", handoff, expected=memory_text),
        call("deny-A-secret", "view", secret),
        call("deny-handoff-write", "str_replace", handoff, old_str=memory_text, new_str="changed"),
        call("deny-directory", "view", inputs),
        call("deny-relative", "view", "../a-inputs/secret.txt"),
        call("deny-symlink", "view", alias),
        call("deny-hardlink", "view", hard),
    ]
    for name in ["bash", "cordis_define", "run_code", "future_tool"]:
        calls.append({"label": "deny-" + name, "name": name, "arguments": {}})
    reader, b = stage(output, "reader", chain, [handoff], None, calls, secret_text, exe)
    loaded = load_memory_artifact(
        directory=output / "frozen",
        expected_manifest_sha256=receipt.manifest_sha256,
        chain_id=chain,
        writer_session_id=writer,
        source_version=SOURCE_VERSION,
        reader_session_id=reader,
        max_bytes=4096,
    )
    if (
        not b["results"][0]["expectedTextPresent"]
        or b["results"][0]["isError"]
        or not all(r["isError"] and r["policyDenied"] for r in b["results"][1:])
    ):
        raise ValueError("Reader tool policy did not behave as required")
    policy = Path(__file__).resolve().parents[2] / "examples/dsh/memory_closed/policy.mjs"
    result = {
        "schema": "dsh.closed-memory-policy-canary.v1",
        "status": "passed",
        "scope": "real SDK tools; no model or training; closed trusted tool composition only",
        "runtime_mode": "mutable-source-wrapper-development-only" if exe else "installed-sdk-runtime",
        "sdk_version": sdk_version(),
        "requested_source_version": SOURCE_VERSION,
        "runtime_source_verified_by_this_script": False,
        "policy_sha256": digest(policy.read_bytes()),
        "chain_id": chain,
        "writer_session_id": writer,
        "reader_session_id": reader,
        "identity_scope": "controller-stage identities; no model agent sessions created",
        "frozen_manifest_sha256": receipt.manifest_sha256,
        "loaded_handoff_matches": loaded.content == memory_text.encode(),
        "writer": a,
        "reader": b,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", help="Development-only source executable override")
    args = parser.parse_args()
    result = run(args.output, args.exe)
    print(json.dumps({"status": result["status"], "result": str(args.output / "result.json")}))
