import json
from types import SimpleNamespace

import pytest

from examples.dsh.capabilities.context_tasks import prepare
from examples.dsh.capabilities.context_verifier import bundle_digest, score, verify
from examples.dsh.evolution_verifier import _sha256_bytes
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result


def episode(root, case):
    contract = json.loads((root / case / "contract.json").read_text())
    events, citations = [], []
    for i, source in enumerate(contract["sources"]):
        text = (root / case / source["path"]).read_text()
        events.extend(
            [
                _call(
                    str(i), "str_replace_editor", {"command": "view", "path": str(root / case / source["path"])}, seq=i
                ),
                _result(str(i), text),
            ]
        )
    for ref in contract["required_evidence"]:
        quote = (root / case / ref["source"]).read_text().splitlines()[ref["line"] - 1]
        citations.append({**ref, "quote": quote})
    events.append({"type": "turn/end", "data": {"reason": {"kind": "completed"}}})
    value = "3" if case.endswith("present") else None
    answer = {"status": "answer" if value else "insufficient_evidence", "value": value, "citations": citations}
    return contract, events, answer


@pytest.mark.parametrize("case", ["directed-present", "directed-missing", "conflict-present", "conflict-missing"])
def test_context_positive_and_missing(tmp_path, case):
    prepare(tmp_path / "data")
    c, events, answer = episode(tmp_path / "data", case)
    result = score(c, tmp_path / "data" / case, events, json.dumps(answer), True)
    assert result["reward"] == 1
    assert result["eligible"] is True
    assert result["extra_info"]["context_switch_verified"] is False


@pytest.mark.parametrize("mutation", ["wrong", "citation", "no_content", "no_read"])
def test_context_safe_mistake_zero(tmp_path, mutation):
    prepare(tmp_path / "data")
    c, events, answer = episode(tmp_path / "data", "conflict-present")
    if mutation == "wrong":
        answer["value"] = "9"
    elif mutation == "citation":
        answer["citations"][0]["quote"] = "invented"
    elif mutation == "no_content":
        events[1] = _result("0", "not the file contents")
    else:
        events = events[-1:]
    result = score(c, tmp_path / "data" / "conflict-present", events, json.dumps(answer), True)
    assert result["reward"] == 0
    assert result["eligible"] is True


@pytest.mark.parametrize(
    "args", [{"command": "create", "path": "sources/current.txt"}, {"command": "view", "path": "../contract.json"}]
)
def test_context_unsafe_rejected(tmp_path, args):
    prepare(tmp_path / "data")
    c, events, answer = episode(tmp_path / "data", "directed-present")
    events[0] = _call("0", "str_replace_editor", args, seq=0)
    result = score(c, tmp_path / "data" / "directed-present", events, json.dumps(answer), True)
    assert result["reward"] == 0
    assert result["eligible"] is False


def test_context_missing_pair_and_source_tamper(tmp_path):
    prepare(tmp_path / "data")
    root = tmp_path / "data" / "directed-present"
    c, events, answer = episode(tmp_path / "data", root.name)
    with pytest.raises(RuntimeError, match="Missing tool result"):
        score(c, root, [events[0], events[-1]], json.dumps(answer), True)
    (root / "sources/current.txt").write_text("max_attempts=9\n")
    with pytest.raises(RuntimeError, match="source hash"):
        score(c, root, events, json.dumps(answer), True)


def test_context_fresh_envelope(tmp_path, monkeypatch):
    prepare(tmp_path / "data")
    case = tmp_path / "data" / "directed-present"
    _, events, answer = episode(tmp_path / "data", case.name)
    trace = "".join(json.dumps(e) + "\n" for e in events).encode()
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_bytes(trace)
    metadata = json.loads((tmp_path / "data" / "tasks.jsonl").read_text().splitlines()[0])["metadata"]
    metadata["environment_digest"] = _sha256_bytes(b"env")
    env = {
        "schema": "dsh.uni-agent.task-result.v1",
        "metadata": metadata,
        "response": json.dumps(answer),
        "finished": True,
        "dsh": {"dsh_session_id": "session-1", "trace_sha256": _sha256_bytes(trace)},
    }
    raw = json.dumps(env).encode()
    path = tmp_path / "result.json"
    path.write_bytes(raw)
    values = {
        "DSH_TASK_RESULT_PATH": str(path),
        "DSH_ARTIFACT_SHA256": _sha256_bytes(raw),
        "DSH_TRACE_PATH": str(trace_path),
        "DSH_TRACE_SHA256": _sha256_bytes(trace),
        "DSH_DSH_SESSION_ID": "session-1",
        "DSH_TASK_WORKDIR": str(tmp_path),
    }
    for key in [
        "task_id",
        "task_version",
        "environment_digest",
        "verifier_id",
        "verifier_version",
        "verifier_code_digest",
    ]:
        values["DSH_" + key.upper()] = metadata[key]
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    result = verify()
    assert result["reward"] == 1
    assert result["fresh"] is True
    assert metadata["verifier_code_digest"] == bundle_digest()
    from uni_agent.tasks.dsh.task import _task_result

    task, receipt = _task_result(
        result,
        SimpleNamespace(finished=True, info={**env["dsh"], "gateway_session_id": "gateway-1"}),
        identity={**metadata, "split": "diagnostic"},
        artifact_sha256=_sha256_bytes(raw),
        verifier_command=["python", "-m", "examples.dsh.capabilities.context_verifier"],
        verifier_stdout=json.dumps(result),
    )
    assert task.reward == 1
    assert receipt["schema"] == "dsh.verifier-receipt.v1"
    assert receipt["verifier"]["id"] == metadata["verifier_id"]
    monkeypatch.setenv("DSH_DSH_SESSION_ID", "different")
    with pytest.raises(RuntimeError):
        verify()


def test_context_partial_line_cannot_prove_read(tmp_path):
    prepare(tmp_path / "data")
    c, events, answer = episode(tmp_path / "data", "directed-present")
    events[1] = _result("0", "authority=current\nmax_attempts=30\n")
    assert score(c, tmp_path / "data/directed-present", events, json.dumps(answer), True)["reward"] == 0


def test_context_numbered_runtime_view(tmp_path):
    prepare(tmp_path / "data")
    c, events, answer = episode(tmp_path / "data", "directed-present")
    for i, source in enumerate(c["sources"]):
        lines = (tmp_path / "data/directed-present" / source["path"]).read_text().splitlines()
        text = "Runtime file view:\n" + "\n".join(f"{n:6d}  {line}" for n, line in enumerate(lines, 1))
        events[2 * i + 1] = _result(str(i), text)
    assert score(c, tmp_path / "data/directed-present", events, json.dumps(answer), True)["reward"] == 1


def test_context_unfinished_cannot_admit(tmp_path):
    prepare(tmp_path / "data")
    c, events, answer = episode(tmp_path / "data", "directed-present")
    value = score(c, tmp_path / "data/directed-present", events, json.dumps(answer), False)
    assert value["reward"] == 0 and value["eligible"] is False
