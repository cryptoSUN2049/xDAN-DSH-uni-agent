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


def probe(root, role, chain, reads, writes, missing, calls, exe, hidden, session_id=None, *, source_version=None):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    directory = root / (role + "-runtime")
    directory.mkdir(mode=0o700)
    session = session_id or role + "-" + uuid.uuid4().hex
    report = directory / "probe.json"
    patch = build_work_state_patch(
        role=role,
        chain_id=chain,
        session_id=session,
        source_version=(
            source_version
            if source_version is not None
            else digest((ROOT / "examples/dsh/capabilities/work_state/tasks.py").read_bytes())
        ),
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


def scenario(root, exe, family, variant, *, course="work-state-v1"):
    if course not in ("work-state-v1", "work-state-memory-core-v1"):
        raise ValueError("Unknown scenario course")
    generator = None
    if course == "work-state-memory-core-v1":
        from examples.dsh.capabilities.work_state import core_tasks

        task = core_tasks.make_core_task(family, variant, seed=7)
        generator_path = Path(core_tasks.__file__).resolve()
        if generator_path != ROOT / "examples/dsh/capabilities/work_state/core_tasks.py":
            raise ValueError("Core generator imported outside canary checkout")
        generator = dict(path=str(generator_path), sha256=digest(generator_path.read_bytes()))
    else:
        task = make_task(family, variant, seed=7)
    probe_source = {"source_version": generator["sha256"]} if generator else {}
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
    writer_id, a = probe(root, "writer", chain, [source, *writes], writes, [], calls, exe, secret, **probe_source)
    raw = pack_bundle(memory, task["memory_paths"])
    packed = root / "bundle.json"
    packed.write_bytes(raw)
    artifact_source = {"task": task, "generator_sha256": generator["sha256"]} if generator else task
    source_version = digest(json.dumps(artifact_source, sort_keys=True).encode())
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
    _, b = probe(
        root, "reader", chain, reads, writes, missing, calls, exe, secret, session_id=reader_id, **probe_source
    )
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
        **({"course_id": course, "generator": generator, "source_version": source_version} if generator else {}),
    )


def short_reader_steps(memory, output, outputs, *, mode):
    """Controller script: each read result must return before a later write response."""
    if mode not in ("positive", "no-read", "wrong-memory", "unsafe"):
        raise ValueError("Unknown short canary mode")
    memory, output = Path(memory), Path(output)
    writes = [dict(command="create", path=str(output / name), file_text=raw.decode()) for name, raw in outputs.items()]
    if mode == "unsafe":
        return [[dict(command="view", path=str(memory.parent / "a-source.json"))]]
    if mode == "no-read":
        return [writes]
    return [
        [dict(command="view", path=str(memory / "index.md"))],
        [dict(command="view", path=str(memory / "handoff.md"))],
        writes,
    ]


def short_wire_response(steps, index, messages):
    if not 0 <= index <= len(steps):
        raise ValueError("Scripted response budget exceeded")
    if index:
        observed = {m.get("tool_call_id") for m in messages if m.get("role") == "tool" and m.get("content")}
        needed = {f"canary-{index - 1}-{i}" for i in range(len(steps[index - 1]))}
        if not needed <= observed:
            raise ValueError("Prior real tool results were not observed")
    if index == len(steps):
        delta, finish = {"role": "assistant", "content": "Operator canary finished."}, "stop"
    else:
        delta = {
            "role": "assistant",
            "tool_calls": [
                dict(
                    index=i,
                    id=f"canary-{index}-{i}",
                    type="function",
                    function=dict(name="str_replace_editor", arguments=json.dumps(args)),
                )
                for i, args in enumerate(steps[index])
            ],
        }
        finish = "tool_calls"
    frames = [
        dict(choices=[dict(index=0, delta=delta, finish_reason=None)]),
        dict(choices=[dict(index=0, delta={}, finish_reason=finish)]),
    ]
    return b"".join(("data: " + json.dumps(frame) + "\n\n").encode() for frame in frames) + b"data: [DONE]\n\n"


def short_model_probe(root, exe, patch, steps, session_id):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    from deployment.checks.dsh_finish_reason_canary import case_deadline
    from uni_agent.agents.dsh.runner import _canonical_event_bytes

    requests, errors = [], []

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def do_POST(self):
            try:
                size = int(self.headers.get("content-length", "0"))
                if not 0 < size <= 1_000_000 or len(requests) > len(steps):
                    raise ValueError("Scripted request budget exceeded")
                raw = self.rfile.read(size)
                body = json.loads(raw)
                if body.get("stream") is not True:
                    raise ValueError("Expected streaming request")
                wire = short_wire_response(steps, len(requests), body["messages"])
                requests.append(dict(index=len(requests), body_sha256=digest(raw), bytes=len(raw)))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(wire)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(wire)
            except Exception as error:
                errors.append(type(error).__name__)
                self.send_error(500)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    patch_path = root / "reader.patch.json"
    patch_path.write_text(json.dumps(patch))
    try:
        config = DeepSeekHarnessConfig(
            provider="deepseek-official",
            model="deepseek-v4-pro",
            profile="sdk-minimal",
            patches=(str(patch_path),),
            cwd=str(root),
            runtime_cwd=str(root),
            dsh_home=str(root / "home"),
            dsh_bin=str(exe),
            base_url=f"http://127.0.0.1:{server.server_port}",
            api_key="EMPTY",
            initialize_timeout_seconds=60,
            request_timeout_seconds=60,
            shutdown_timeout_seconds=5,
            max_tokens=4096,
            reasoning_effort="off",
            env={"DSH_TELEMETRY_DISABLED": "1"},
        )
        with case_deadline(180), DeepSeekHarness(config) as harness:
            result = harness.run(
                "Execute the operator script. No student model or training is involved.", session_id=session_id
            )
        if errors or len(requests) != len(steps) + 1:
            raise ValueError("Incomplete scripted runtime exchange")
        raw = _canonical_event_bytes(result.events)
        (root / "reader-events.jsonl").write_bytes(raw)
        return (
            result,
            [json.loads(line) for line in raw.splitlines()],
            dict(requests=requests, errors=errors, trace_sha256=digest(raw)),
        )
    except BaseException as error:
        errors.append(type(error).__name__)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        (root / "reader-http-evidence.json").write_text(json.dumps(dict(requests=requests, errors=errors), indent=2))


def short_scenario(root, exe, variant, mode):
    from examples.dsh.capabilities.memory_verifier import canonical
    from examples.dsh.capabilities.work_state import verifier

    task = make_task("WS07", variant, seed=901 if variant else 101)
    root.mkdir(mode=0o700)
    memory = root / "a-memory"
    memory.mkdir(mode=0o700)
    source = root / "a-source.json"
    source.write_text(json.dumps(task["writer_files"]))
    chain = "short-canary-" + uuid.uuid4().hex
    stored, outputs = oracle_memory(task), oracle_outputs(task)
    if mode == "wrong-memory":
        config = json.loads(outputs["config.json"])
        old = config["capacity"]
        config["capacity"] += 1
        stored = {
            name: raw.replace(str(old).encode(), str(config["capacity"]).encode()) if name == "handoff.md" else raw
            for name, raw in stored.items()
        }
        outputs = {**outputs, "config.json": json.dumps(config).encode()}
    writer_calls = [action("read-source", "view", source)] + [
        action("persist-" + name, "create", memory / name, file_text=raw.decode()) for name, raw in stored.items()
    ]
    writer_id, writer = probe(
        root,
        "writer",
        chain,
        [source],
        [memory / name for name in task["memory_paths"]],
        [],
        writer_calls,
        exe,
        "DO-NOT-LEAK-" + uuid.uuid4().hex,
    )
    raw = pack_bundle(memory, task["memory_paths"])
    (root / "bundle.json").write_bytes(raw)
    source_version = digest(canonical(task))
    frozen = freeze_memory_artifact(
        source_root=root,
        relative_path="bundle.json",
        expected_source_sha256=digest(raw),
        source_version=source_version,
        chain_id=chain,
        writer_session_id=writer_id,
        max_bytes=196608,
        output_dir=root / "frozen",
    )
    unpacked = root / "b-memory"
    inventory = unpack_bundle(raw, unpacked, task["memory_paths"])
    output = root / "b-results"
    output.mkdir(mode=0o700)
    session_id = "short-reader-" + uuid.uuid4().hex
    reads = {str(unpacked / name): digest((unpacked / name).read_bytes()) for name in inventory["files"]}
    writes = [str(output / name) for name in task["result_paths"]]
    patch = build_work_state_patch(
        role="reader",
        chain_id=chain,
        session_id=session_id,
        source_version=source_version,
        read_files=list(reads),
        write_files=writes,
        read_missing=[unpacked / name for name in inventory["missing"]],
    )
    result, events, evidence = short_model_probe(
        root, exe, patch, short_reader_steps(unpacked, output, outputs, mode=mode), session_id
    )
    fixture = dict(
        schema="dsh.work-state-stage.v1",
        contract_id="work-state-v1",
        role="reader",
        chain_id=chain,
        source_version=source_version,
        task=task,
        read_files=reads,
        write_files=writes,
        read_missing=[str(unpacked / name) for name in inventory["missing"]],
        memory_root=str(unpacked),
        output_root=str(output),
        max_bytes=65536,
        writer_binding=dict(
            manifest_sha256=frozen.manifest_sha256, content_sha256=frozen.content_sha256, dsh_session_id=writer_id
        ),
        frozen_dir=str(root / "frozen"),
        bundle_paths=task["memory_paths"],
        unpacked_root=str(unpacked),
    )
    (root / "reader-fixture.json").write_text(json.dumps(fixture, indent=2))
    scored = verifier.score(
        fixture, events, result.final_response, result.finish_reason == "completed", result.session_id
    )
    if scored["reward"] != (1 if mode == "positive" else 0) or scored["eligible"] != (mode != "unsafe"):
        raise ValueError("Short-course runtime outcome mismatch: " + mode)
    report = dict(
        task_id=task["task_id"],
        variant=variant,
        mode=mode,
        training=False,
        model_evaluation=False,
        writer=writer,
        reader=evidence,
        score=scored,
        verifier_bundle=verifier.bundle_digest(),
        frozen_content_sha256=frozen.content_sha256,
    )
    (root / "scenario-result.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument(
        "--course",
        choices=("work-state-v1", "work-state-short-fact-v1", "work-state-memory-core-v1"),
        default="work-state-v1",
    )
    args = parser.parse_args()
    output, exe = args.output.absolute(), args.runtime.resolve()
    lock = json.loads((ROOT / "deployment/versions/g1-deployment-lock.json").read_text())
    if digest(exe.read_bytes()) != lock["dsh"]["runtime_binary_sha256"]:
        raise ValueError("Runtime pin mismatch")
    if output.parent.resolve() != output.parent:
        raise ValueError("Use canonical output parent")
    output.mkdir(mode=0o700)
    results = [
        scenario(output / f"{family}-v{variant}", exe, family, variant, course=args.course)
        for family in (
            ("WS01", "WS03", "WS05", "WS06") if args.course in ("work-state-v1", "work-state-memory-core-v1") else ()
        )
        for variant in (0, 1)
    ]
    if args.course == "work-state-short-fact-v1":
        results = [
            short_scenario(output / f"WS07-v{variant}-{mode}", exe, variant, mode)
            for variant in (0, 1)
            for mode in ("positive", "no-read", "wrong-memory", "unsafe")
        ]
    report = dict(
        course_id=args.course,
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
