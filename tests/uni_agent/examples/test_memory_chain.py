import json
import sys

import pytest

from examples.dsh.capabilities.memory_chain import admit_writer_and_freeze, prepare_writer
from examples.dsh.capabilities.memory_verifier import score
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result


@pytest.fixture(params=["constraints", "updates"])
def prepared(tmp_path, request):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"test runtime")
    runtime.chmod(0o700)
    from examples.dsh.capabilities.memory_chain import sha

    return prepare_writer(
        output_dir=tmp_path / "chain",
        chain_id="chain-1",
        family=request.param,
        runtime_executable=runtime,
        environment_digest=sha(runtime.read_bytes()),
        runner_python=sys.executable,
        model_path="/operator/pinned-model",
        checkpoint_identity="test-checkpoint",
    )


def writer_episode(prepared):
    fixture = json.loads(open(prepared["writer"]["fixture_path"]).read())
    source = fixture["source_path"]
    memory = fixture["memory_path"]
    from pathlib import Path

    Path(memory).write_text(json.dumps(fixture["expected_memory"]))
    events = [
        _call("read", "str_replace_editor", {"command": "view", "path": source}, seq=0),
        _result("read", Path(source).read_text()),
        _call(
            "write",
            "str_replace_editor",
            {"command": "create", "path": memory, "file_text": Path(memory).read_text()},
            seq=1,
        ),
        _result("write", "created"),
        {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
    ]
    return fixture, events


def test_writer_prompt_v2_public_operation_contract_without_fact_answers(prepared):
    from pathlib import Path

    import pyarrow.parquet as pq

    from examples.dsh.capabilities.memory_tasks import writer_prompt

    fixture = json.loads(Path(prepared["writer"]["fixture_path"]).read_text())
    assert fixture["prompt_revision"] == "2"
    assert prepared["writer_prompt_revision"] == "2"
    prompt = writer_prompt(fixture)
    assert "read-only" in prompt
    assert "even a no-op edit" in prompt
    assert 'command="view"' in prompt
    assert 'command="create"' in prompt
    assert "serialized JSON string" in prompt
    assert "escape" in prompt
    assert fixture["source_path"] in prompt and fixture["memory_path"] in prompt
    for fact in fixture["expected_memory"]["facts"].values():
        assert fact not in prompt
    staged = pq.read_table(Path(prepared["root"]) / "writer/eval.parquet").to_pylist()[0]
    assert staged["prompt"][0]["content"] == prompt


def test_writer_true_tools_and_safe_wrong_memory(prepared):
    fixture, events = writer_episode(prepared)
    assert score(fixture, events, "done", True, "dsh-A")["reward"] == 1
    from pathlib import Path

    Path(fixture["memory_path"]).write_text('{"wrong":true}')
    result = score(fixture, events, "done", True, "dsh-A")
    assert result["eligible"] is True and result["reward"] == 0


def test_writer_unfinished_cannot_freeze(prepared):
    with pytest.raises((ValueError, FileNotFoundError)):
        admit_writer_and_freeze(prepared["manifest_path"])
    from pathlib import Path

    assert not (Path(prepared["root"]) / "frozen").exists()
    assert not (Path(prepared["root"]) / "reader").exists()


def record_synthetic_stage(stage, events, response, gateway, *, finished=True):
    """Only CPU fixture construction, never evidence of a student/model run."""
    from pathlib import Path

    from examples.dsh.capabilities.memory_chain import write_new
    from examples.dsh.capabilities.memory_verifier import VERIFIER_ID, bundle_digest, canonical, sha

    run = Path(stage["run_root"])
    trace_dir = run / "artifacts/traces/test"
    result_dir = run / "artifacts/results/test"
    trace_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    trace = trace_dir / "session.jsonl"
    write_new(trace, b"".join(canonical(event) for event in events))
    fixture = json.loads(Path(stage["fixture_path"]).read_text())
    result = score(fixture, events, response, finished, "dsh-" + gateway)
    envelope = {
        "schema": "dsh.uni-agent.task-result.v1",
        "metadata": stage["metadata"],
        "response": response,
        "finished": finished,
        "dsh": {
            "dsh_session_id": "dsh-" + gateway,
            "gateway_session_id": gateway,
            "trace_sha256": sha(trace.read_bytes()),
            "trace_path": str(trace),
        },
    }
    write_new(result_dir / "agent-result.json", envelope)
    receipt = {
        "schema": "dsh.verifier-receipt.v1",
        "issuer": {"kind": "trusted-verifier", "id": "uni-agent-dsh"},
        "task_id": stage["metadata"]["task_id"],
        "task_version": "1",
        "dsh_session_id": "dsh-" + gateway,
        "artifact_sha256": sha(canonical(envelope)),
        "trace_sha256": sha(trace.read_bytes()),
        "environment_digest": stage["metadata"]["environment_digest"],
        "verifier": {"id": VERIFIER_ID, "version": "1", "code_digest": bundle_digest()},
        "fresh": True,
        "issued_at": "2026-09-09T01:00:01+00:00",
        "evidence": [stage["metadata"]["fixture_sha256"], sha(trace.read_bytes())],
        **{key: result[key] for key in ("reward", "accuracy", "eligible", "finished")},
    }
    receipt["receipt_id"] = sha(canonical(receipt))
    write_new(result_dir / "verifier-receipt.json", receipt)
    supervision = run / "supervision"
    supervision.mkdir()
    write_new(supervision / "supervisor-result.json", {"exit_code": 0})
    write_new(
        run / "process-exit.json",
        {
            "exit_code": 0,
            "argv_sha256": stage["files"][stage["argv_path"]],
            "chain_id": stage["chain_id"],
            "role": stage["role"],
            "run_root": str(run),
            "manifest_sha256": sha(Path(stage["manifest_path"]).read_bytes()),
            "supervisor_sha256": sha((supervision / "supervisor-result.json").read_bytes()),
        },
    )
    uid = "uid-" + gateway
    write_new(
        run / "inference-evidence.json",
        {
            "status": "completed",
            "started_at": "2026-09-09T01:00:00+00:00",
            "finished_at": "2026-09-09T01:00:02+00:00",
            "samples": [{"uid": uid, "metadata": stage["metadata"]}],
            "readback": {"scores": [result["reward"]], "uid_status": {uid: "finished"}, "final_keys": [uid + "_0_0"]},
        },
    )
    return run, result_dir


def reader_episode(stage):
    from pathlib import Path

    fixture = json.loads(Path(stage["fixture_path"]).read_text())
    events = []
    for i, name in enumerate(("memory_path", "question_path")):
        path = fixture[name]
        events.extend(
            [
                _call(str(i), "str_replace_editor", {"command": "view", "path": path}, seq=i),
                _result(str(i), Path(path).read_text()),
            ]
        )
    events.append({"type": "turn/end", "data": {"reason": {"kind": "completed"}}})
    return fixture, events, json.dumps(fixture["expected_answer"])


def test_cpu_full_chain_then_no_reuse(prepared):
    from pathlib import Path

    from examples.dsh.capabilities.memory_chain import finalize_chain

    _, a_events = writer_episode(prepared)
    record_synthetic_stage(prepared["writer"], a_events, "done", "A")
    stage = admit_writer_and_freeze(prepared["manifest_path"])
    _, events, answer = reader_episode(stage)
    record_synthetic_stage(stage, events, answer, "B")
    report = finalize_chain(prepared["manifest_path"])
    assert report["status"] == "passed" and report["training"] is False
    assert report["credit_assignment"] == "none"
    assert report["writer"]["dsh_session_id"] != report["reader"]["dsh_session_id"]
    assert (Path(prepared["root"]) / "frozen/memory.bin").exists()
    with pytest.raises(ValueError, match="reused"):
        admit_writer_and_freeze(prepared["manifest_path"])
    with pytest.raises(FileExistsError):
        finalize_chain(prepared["manifest_path"])


@pytest.mark.parametrize("mutation", ["unfinished", "zero", "receipt_hash", "trace", "process", "stale", "sample"])
def test_writer_failures_never_freeze(prepared, mutation):
    from pathlib import Path

    fixture, events = writer_episode(prepared)
    if mutation == "zero":
        Path(fixture["memory_path"]).write_text('{"facts":{}}')
    run, results = record_synthetic_stage(prepared["writer"], events, "done", "A", finished=mutation != "unfinished")
    if mutation == "receipt_hash":
        p = results / "verifier-receipt.json"
        data = json.loads(p.read_text())
        data["reward"] = 0
        p.write_text(json.dumps(data))
    if mutation == "trace":
        (run / "artifacts/traces/test/session.jsonl").write_text("{}\n")
    if mutation == "process":
        (run / "process-exit.json").write_text('{"exit_code":1}')
    if mutation in {"stale", "sample"}:
        p = run / "inference-evidence.json"
        data = json.loads(p.read_text())
        if mutation == "stale":
            data["started_at"] = "2026-09-10T00:00:00+00:00"
        else:
            data["samples"][0]["metadata"]["task_id"] = "different-task"
        p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        admit_writer_and_freeze(prepared["manifest_path"])
    assert not (Path(prepared["root"]) / "frozen").exists()
    assert not (Path(prepared["root"]) / "reader").exists()


@pytest.mark.parametrize(
    "mutation",
    ["wrong_answer", "no_read", "reused_session", "wrong_manifest", "tampered_content", "unsafe", "unfinished"],
)
def test_reader_negative_semantics(prepared, mutation):
    from pathlib import Path

    _, events = writer_episode(prepared)
    record_synthetic_stage(prepared["writer"], events, "done", "A")
    stage = admit_writer_and_freeze(prepared["manifest_path"])
    fixture, events, answer = reader_episode(stage)
    if mutation == "wrong_answer":
        answer = "{}"
    elif mutation == "no_read":
        events = events[-1:]
    elif mutation == "wrong_manifest":
        fixture["writer_binding"]["manifest_sha256"] = "sha256:" + "0" * 64
    elif mutation == "tampered_content":
        Path(fixture["memory_path"]).write_text("tampered")
    elif mutation == "unsafe":
        events[0] = _call("0", "str_replace_editor", {"command": "view", "path": "/secret-A"}, seq=0)
    if mutation in {"reused_session", "wrong_manifest", "tampered_content"}:
        with pytest.raises(ValueError):
            score(fixture, events, answer, True, "dsh-A" if mutation == "reused_session" else "dsh-B")
    else:
        result = score(fixture, events, answer, mutation != "unfinished", "dsh-B")
        assert result["reward"] == 0
        assert result["eligible"] is (mutation not in {"unsafe", "unfinished"})


def test_verifier_process_interface_binds_envelope_and_fixture(prepared, monkeypatch):
    from pathlib import Path

    from examples.dsh.capabilities.memory_verifier import verify

    _, events = writer_episode(prepared)
    run, results = record_synthetic_stage(prepared["writer"], events, "done", "A")
    receipt = json.loads((results / "verifier-receipt.json").read_text())
    metadata = prepared["writer"]["metadata"]
    for field in (
        "task_id",
        "task_version",
        "environment_digest",
        "verifier_id",
        "verifier_version",
        "verifier_code_digest",
    ):
        monkeypatch.setenv("DSH_" + field.upper(), metadata[field])
    monkeypatch.setenv("DSH_TASK_WORKDIR", prepared["root"])
    monkeypatch.setenv("DSH_TASK_RESULT_PATH", str(results / "agent-result.json"))
    monkeypatch.setenv("DSH_ARTIFACT_SHA256", receipt["artifact_sha256"])
    monkeypatch.setenv("DSH_DSH_SESSION_ID", "dsh-A")
    monkeypatch.setenv("DSH_TRACE_PATH", str(run / "artifacts/traces/test/session.jsonl"))
    monkeypatch.setenv("DSH_TRACE_SHA256", receipt["trace_sha256"])
    result = verify()
    assert result["fresh"] is True and result["reward"] == 1
    assert metadata["fixture_sha256"] in result["evidence"]
    monkeypatch.setenv("DSH_DSH_SESSION_ID", "dsh-wrong")
    with pytest.raises(RuntimeError, match="session"):
        verify()
    assert Path(prepared["root"]).is_dir()


def test_run_stage_refuses_changed_inputs_without_launching(prepared, monkeypatch):
    from pathlib import Path

    from examples.dsh.capabilities import memory_chain

    Path(prepared["writer"]["argv_path"]).write_text('["dangerous-altered-command"]')
    launched = []
    monkeypatch.setattr(memory_chain.subprocess, "run", lambda *a, **kw: launched.append(a))
    with pytest.raises(ValueError, match="changed"):
        memory_chain.run_stage(prepared["manifest_path"], "writer")
    assert launched == []


def test_runtime_repin_and_output_reuse_are_rejected(prepared):
    from pathlib import Path

    Path(prepared["runtime_executable"]).write_bytes(b"different runtime")
    with pytest.raises(ValueError, match="Runtime changed"):
        admit_writer_and_freeze(prepared["manifest_path"])


def test_runtime_hash_allows_package_cache_hardlink_but_memory_contract_does_not(prepared, tmp_path):
    import os

    from examples.dsh.capabilities.memory_chain import _load_manifest

    os.link(prepared["runtime_executable"], tmp_path / "runtime-cache-link")
    assert _load_manifest(prepared["manifest_path"])["chain_id"] == prepared["chain_id"]


@pytest.mark.parametrize("outcome", ["success", "exit_failure", "wrong_runtime"])
def test_stage_launcher_waits_and_records_exit_without_training(prepared, monkeypatch, outcome):
    from pathlib import Path
    from types import SimpleNamespace

    from examples.dsh.capabilities import memory_chain

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "-c" in argv:
            runtime = prepared["runtime_executable"] if outcome != "wrong_runtime" else "/wrong"
            return SimpleNamespace(stdout=json.dumps([runtime, "0.1.3a2", "0.1.3a2"]))
        raise AssertionError("Only no-model preflight may use subprocess.run")

    def fake_supervise(argv, cwd, environment, root, health, **kwargs):
        calls.append(argv)
        assert argv[2] == "examples.inference.parallel_infer_verl"
        assert environment["DSH_RUNTIME_MODE"] == "exe"
        assert kwargs["wall_seconds"] == 1800 and kwargs["grace"] == 30
        result = {"exit_code": 0 if outcome == "success" else 1}
        memory_chain.write_new(root / "supervisor-result.json", result)
        return result

    monkeypatch.setattr(memory_chain.subprocess, "run", fake_run)
    monkeypatch.setattr(memory_chain, "supervise", fake_supervise)
    run = Path(prepared["writer"]["run_root"])
    if outcome == "wrong_runtime":
        with pytest.raises(ValueError, match="pin"):
            memory_chain.run_stage(prepared["manifest_path"], "writer")
        assert len(calls) == 1 and not (run / "process-exit.json").exists()
    elif outcome == "exit_failure":
        with pytest.raises(RuntimeError, match="Inference failed"):
            memory_chain.run_stage(prepared["manifest_path"], "writer")
        assert json.loads((run / "process-exit.json").read_text())["exit_code"] == 1
    else:
        result = memory_chain.run_stage(prepared["manifest_path"], "writer")
        assert result["exit_code"] == 0 and result["training"] is False
        with pytest.raises(ValueError, match="empty"):
            memory_chain.run_stage(prepared["manifest_path"], "writer")


def test_owned_supervisor_real_cpu_wall_timeout(tmp_path):
    import os

    from deployment.services.harbor_training_supervisor import supervise

    result = supervise(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        tmp_path,
        os.environ.copy(),
        tmp_path,
        lambda: None,
        wall_seconds=0.1,
        interval=0.02,
        grace=0.2,
    )
    assert result["reason"] == "wall-clock-deadline" and result["exit_code"] != 0
    with pytest.raises(ProcessLookupError):
        os.kill(result["pid"], 0)
