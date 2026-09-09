"""Real fixed SDK/tool canary. Controller oracle; never a student rollout or RL receipt."""

import argparse
import json
import time
import uuid
from pathlib import Path

from deployment.checks.dsh_memory_policy_canary import call, digest, sdk_version
from examples.dsh.capabilities.work_state.bundle import pack_bundle, unpack_bundle
from examples.dsh.capabilities.work_state.profile import build_work_state_patch
from examples.dsh.capabilities.work_state.scoring import score_task
from examples.dsh.capabilities.work_state.tasks import make_task, oracle_memory, oracle_outputs
from uni_agent.tasks.dsh.memory_artifacts import freeze_memory_artifact, load_memory_artifact

ROOT = Path(__file__).resolve().parents[2]
DENIED = "WORK_STATE_POLICY_DENIED"


def validate_probe(report, expected):
    if report.get("tools") != ["str_replace_editor"] or len(report.get("results", [])) != len(expected):
        raise ValueError("Incomplete real tool probe")
    for result, item in zip(report["results"], expected, strict=True):
        if (
            result.get("label") != item["label"]
            or bool(result.get("isError")) != item["error"]
            or result.get("expectedTextPresent") is not item["denied"]
            or result.get("forbiddenTextPresent") is not False
        ):
            raise ValueError("Real tool contract mismatch: " + item["label"])


def probe(root, role, chain, reads, writes, missing, calls, exe, hidden, session_id=None):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    directory = root / (role + "-runtime")
    directory.mkdir(mode=0o700)
    session = session_id or role + "-" + uuid.uuid4().hex
    report = directory / "probe.json"
    patch = build_work_state_patch(
        role=role,
        chain_id=chain,
        session_id=session,
        source_version=digest((ROOT / "examples/dsh/capabilities/work_state/tasks.py").read_bytes()),
        read_files=reads,
        write_files=writes,
        read_missing=missing,
    )
    # The old probe's policyDenied boolean is intentionally ignored: expectedText
    # explicitly checks this contract's WORK_STATE_POLICY_DENIED marker.
    patch.append(
        dict(
            insert=[
                dict(
                    id="work-state-operator-canary",
                    name=(ROOT / "examples/dsh/memory_closed/probe.mjs").as_uri(),
                    config=dict(report=str(report), calls=[x["call"] for x in calls], forbiddenText=hidden),
                )
            ]
        )
    )
    patch_path = directory / "probe.patch.json"
    patch_path.write_text(json.dumps(patch))
    with DeepSeekHarness(
        DeepSeekHarnessConfig(
            provider="deepseek-official",
            model="unused-no-model",
            profile="sdk-minimal",
            patches=(str(patch_path),),
            cwd=str(directory),
            runtime_cwd=str(directory),
            dsh_bin=str(exe),
            dsh_home=str(directory / "home"),
            initialize_timeout_seconds=60,
            shutdown_timeout_seconds=10,
            base_url="http://127.0.0.1:1",
            api_key="unused-no-model",
            env={"DSH_TELEMETRY_DISABLED": "1"},
        )
    ):
        deadline = time.monotonic() + 30
        while not report.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("No runtime probe output")
            time.sleep(0.1)
    value = json.loads(report.read_text())
    validate_probe(value, calls)
    return session, value


def action(label, command, path, *, error=False, denied=False, **kwargs):
    return dict(label=label, error=error, denied=denied, call=call(label, command, path, expected=DENIED, **kwargs))


def scenario(root, exe, family, variant):
    task = make_task(family, variant, seed=7)
    root.mkdir(mode=0o700)
    memory = root / "a-memory"
    memory.mkdir(mode=0o700)
    source = root / "a-source.json"
    source.write_text(json.dumps(task["writer_files"]))
    hidden = root / "controller-secret.txt"
    secret = "PRIVATE-" + uuid.uuid4().hex
    hidden.write_text(secret)
    chain = "canary-" + uuid.uuid4().hex
    writes = [memory / name for name in task["memory_paths"]]
    calls = [action("read-source", "view", source), action("view-new-index", "view", memory / "index.md", error=True)]
    for name, raw in oracle_memory(task).items():
        calls.append(action("create-" + name, "create", memory / name, file_text=raw.decode()))
    calls += [
        action("deny-source-write", "create", source, error=True, denied=True, file_text="bad"),
        action("deny-hidden-read", "view", hidden, error=True, denied=True),
    ]
    writer_id, a = probe(root, "writer", chain, [source, *writes], writes, [], calls, exe, secret)
    raw = pack_bundle(memory, task["memory_paths"])
    packed = root / "bundle.json"
    packed.write_bytes(raw)
    source_version = digest(json.dumps(task, sort_keys=True).encode())
    receipt = freeze_memory_artifact(
        source_root=root,
        relative_path="bundle.json",
        expected_source_sha256=digest(raw),
        source_version=source_version,
        chain_id=chain,
        writer_session_id=writer_id,
        max_bytes=196608,
        output_dir=root / "frozen",
    )
    reader_id = "reader-precheck-" + uuid.uuid4().hex
    loaded = load_memory_artifact(
        directory=root / "frozen",
        expected_manifest_sha256=receipt.manifest_sha256,
        chain_id=chain,
        writer_session_id=writer_id,
        source_version=source_version,
        reader_session_id=reader_id,
        max_bytes=196608,
    )
    # freeze/load returns an object containing the exact persisted bytes.
    frozen_raw = loaded.content
    if digest(frozen_raw) != receipt.content_sha256:
        raise ValueError("Frozen bytes changed")
    del loaded
    unpacked = root / "b-memory"
    inventory = unpack_bundle(frozen_raw, unpacked, task["memory_paths"])
    public = root / "b-request.json"
    public.write_text(json.dumps(task["reader_files"]))
    result = root / "b-results"
    result.mkdir(mode=0o700)
    writes = [result / name for name in task["result_paths"]]
    reads = [public, *writes, *[unpacked / name for name in task["memory_paths"]]]
    missing = [unpacked / name for name in inventory["missing"]]
    calls = [
        action("read-public", "view", public),
        action("view-index", "view", unpacked / "index.md", error="index.md" in inventory["missing"]),
        action("view-new-result", "view", result / "config.json", error=True),
    ]
    for name in inventory["files"]:
        if name != "index.md":
            calls.append(action("read-" + name, "view", unpacked / name))
    for name, content in oracle_outputs(task).items():
        calls.append(action("write-" + name, "create", result / name, file_text=content.decode()))
    calls += [
        action("deny-A-read", "view", source, error=True, denied=True),
        action("deny-index-write", "create", unpacked / "index.md", error=True, denied=True, file_text="bad"),
    ]
    _, b = probe(root, "reader", chain, reads, writes, missing, calls, exe, secret, session_id=reader_id)
    if pack_bundle(unpacked, task["memory_paths"]) != frozen_raw:
        raise ValueError("Reader changed frozen state")
    scored = score_task(task, {name: (result / name).read_bytes() for name in task["result_paths"]})
    if scored["reward"] != 1:
        raise ValueError("Controller solution did not solve real artifacts")
    return dict(
        task_id=task["task_id"],
        family=family,
        variant=variant,
        writer=a,
        reader=b,
        frozen_sha256=receipt.content_sha256,
        score=scored,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    output, exe = args.output.absolute(), args.runtime.resolve()
    lock = json.loads((ROOT / "deployment/versions/g1-deployment-lock.json").read_text())
    if digest(exe.read_bytes()) != lock["dsh"]["runtime_binary_sha256"]:
        raise ValueError("Runtime pin mismatch")
    if output.parent.resolve() != output.parent:
        raise ValueError("Use canonical output parent")
    output.mkdir(mode=0o700)
    results = [
        scenario(output / f"{family}-v{variant}", exe, family, variant)
        for family in ("WS01", "WS03", "WS05", "WS06")
        for variant in (0, 1)
    ]
    report = dict(
        schema="dsh.work-state-runtime-canary.v1",
        passed=True,
        scope="Controller oracle, real SDK tools/freeze/business checks; no student or RL receipt",
        sdk_version=sdk_version(),
        runtime_sha256=digest(exe.read_bytes()),
        scenarios=results,
    )
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(passed=True, scenarios=len(results), output=str(output / "result.json"))))


if __name__ == "__main__":
    main()
