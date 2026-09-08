import json

import pytest

from examples.dsh.rsi_closed.worker_tasks import prepare
from examples.dsh.rsi_closed.worker_verifier import score
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result


@pytest.fixture
def cases(tmp_path):
    output = tmp_path / "cases"
    rows = prepare(output)
    return output, rows


def episode(cases, kind):
    output, _ = cases
    case = "inspect-discovery" if kind == "inspection" else "file-constraint"
    root = output / case
    contract = json.loads((root / "contract.json").read_text())
    if kind == "inspection":
        text = json.dumps({"providers": [{"platform": "host", "id": "Tool", "methods": [{"name": "listTools"}]}]})
        call = _call("a", "cordis_inspect_list", {}, seq=0)
        answer = {
            "status": "answer",
            "platform": "host",
            "provider": "Tool",
            "method": "listTools",
        }
    else:
        text = (root / "sources/constraints.txt").read_text()
        call = _call(
            "a", "str_replace_editor", {"command": "view", "path": str(root / "sources/constraints.txt")}, seq=0
        )
        answer = {
            "status": "answer",
            "value": "3",
            "citation": {
                "source": "sources/constraints.txt",
                "line": 2,
                "quote": "max_attempts=3",
            },
        }
    events = [call, _result("a", text), {"type": "turn/end", "data": {"reason": {"kind": "completed"}}}]
    return root, contract, events, answer


@pytest.mark.parametrize("kind", ["inspection", "file"])
def test_real_evidence_contract_positive(cases, kind):
    root, contract, events, answer = episode(cases, kind)
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["reward"] == 1
    assert value["eligible"] is True
    assert value["extra_info"]["scope"] == "rsi-worker-development"


def test_inspection_policy_denial_is_business_zero(cases):
    root, contract, events, answer = episode(cases, "inspection")
    events[1] = _result("a", "RSI_POLICY_DENIED", error=True)
    answer.update(status="unavailable", platform=None, provider=None, method=None)
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["reward"] == 0 and value["eligible"] is True


@pytest.mark.parametrize("fault", ["route", "denied", "no-call", "unknown-tool"])
def test_inspection_fabrication_and_unsafe_rejected(cases, fault):
    root, contract, events, answer = episode(cases, "inspection")
    if fault == "route":
        answer["method"] = "fake"
    elif fault == "denied":
        events[1] = _result("a", "RSI_POLICY_DENIED", error=True)
    elif fault == "no-call":
        events = events[-1:]
    else:
        events[0] = _call("a", "cordis_define", {}, seq=0)
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["reward"] == 0 and value["eligible"] is False


@pytest.mark.parametrize("fault", ["write", "path", "quote", "source", "failed-result"])
def test_file_hard_rejections(cases, fault):
    root, contract, events, answer = episode(cases, "file")
    if fault == "write":
        events[0] = _call(
            "a", "str_replace_editor", {"command": "create", "path": str(root / "sources/constraints.txt")}, seq=0
        )
    elif fault == "path":
        events[0] = _call("a", "str_replace_editor", {"command": "view", "path": str(root / "secret.txt")}, seq=0)
    elif fault == "quote":
        answer["citation"]["quote"] = "fabricated"
    elif fault == "source":
        answer["citation"]["source"] = "secret.txt"
    else:
        events[1] = _result("a", "unreadable", error=True)
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["reward"] == 0 and value["eligible"] is False


def test_wrong_value_real_evidence_safe_zero(cases):
    root, contract, events, answer = episode(cases, "file")
    answer["value"] = "9"
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["reward"] == 0 and value["eligible"] is True


@pytest.mark.parametrize("fault", ["source", "runtime", "missing-pair"])
def test_integrity_failure(cases, fault):
    root, contract, events, answer = episode(cases, "file")
    if fault == "source":
        (root / "sources/constraints.txt").write_text("tampered")
    elif fault == "runtime":
        contract["runtime_sha256"] = "sha256:" + "0" * 64
    else:
        events.pop(1)
    with pytest.raises((RuntimeError, ValueError)):
        score(contract, root, events, json.dumps(answer), True)


def test_preparer_is_two_unique_development_tasks(cases):
    root, rows = cases
    assert len(rows) == len({row["metadata"]["task_id"] for row in rows}) == 2
    assert all(row["metadata"]["split"] == "validation" for row in rows)
    assert (root / "manifest.json").is_file()
    with pytest.raises(FileExistsError):
        prepare(root)


@pytest.mark.parametrize("kind", ["inspection", "file"])
def test_no_action_unavailable_is_valid_unsolved(cases, kind):
    root, contract, events, _ = episode(cases, kind)
    answer = (
        {"status": "unavailable", "platform": None, "provider": None, "method": None}
        if kind == "inspection"
        else {"status": "unavailable", "value": None, "citation": None}
    )
    value = score(contract, root, events[-1:], json.dumps(answer), True)
    assert value["eligible"] is True and value["reward"] == 0
    assert value["extra_info"]["matched_call_ids"] == []


def test_control_plane_matches_hidden_call_id(cases):
    root, contract, events, answer = episode(cases, "inspection")
    assert "call_id" not in json.dumps(answer)
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["extra_info"]["matched_call_ids"] == ["a"]
    assert value["reward"] == 1


def test_numbered_file_result_and_incomplete_turn(cases):
    root, contract, events, answer = episode(cases, "file")
    lines = (root / "sources/constraints.txt").read_text().splitlines()
    events[1] = _result("a", "File view:\n" + "\n".join(f"{i:6d}  {line}" for i, line in enumerate(lines, 1)))
    assert score(contract, root, events, json.dumps(answer), True)["reward"] == 1
    events[-1]["data"]["reason"] = {"kind": "max-tokens"}
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["reward"] == 0 and value["eligible"] is False


@pytest.mark.parametrize("response", ["not-json", "[]", '{"status":"answer","status":"unavailable"}'])
def test_malformed_response_is_unsolved(cases, response):
    root, contract, events, _ = episode(cases, "inspection")
    value = score(contract, root, events, response, True)
    assert value["reward"] == 0 and value["eligible"] is True


def test_malformed_successful_runtime_result_is_integrity_failure(cases):
    root, contract, events, answer = episode(cases, "inspection")
    events[1] = _result("a", "not a provider response")
    with pytest.raises(RuntimeError, match="Malformed successful"):
        score(contract, root, events, json.dumps(answer), True)


def test_fresh_envelope_integrates_existing_receipt(cases, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from examples.dsh.evolution_verifier import _sha256_bytes
    from examples.dsh.rsi_closed.worker_verifier import RUNTIME_SHA256, verify
    from uni_agent.tasks.dsh.task import _task_result

    root, _, events, answer = episode(cases, "inspection")
    trace = "".join(json.dumps(event) + "\n" for event in events).encode()
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_bytes(trace)
    metadata = cases[1][0]["metadata"]
    envelope = {
        "schema": "dsh.uni-agent.task-result.v1",
        "metadata": metadata,
        "response": json.dumps(answer),
        "finished": True,
        "dsh": {"dsh_session_id": "worker-session", "trace_sha256": _sha256_bytes(trace)},
    }
    raw = json.dumps(envelope).encode()
    artifact = tmp_path / "result.json"
    artifact.write_bytes(raw)
    values = {
        "DSH_TASK_RESULT_PATH": str(artifact),
        "DSH_ARTIFACT_SHA256": _sha256_bytes(raw),
        "DSH_TRACE_PATH": str(trace_path),
        "DSH_TRACE_SHA256": _sha256_bytes(trace),
        "DSH_DSH_SESSION_ID": "worker-session",
        "DSH_TASK_WORKDIR": str(cases[0]),
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
    assert result["reward"] == 1 and result["fresh"] is True
    task, receipt = _task_result(
        result,
        SimpleNamespace(finished=True, info={**envelope["dsh"], "gateway_session_id": "gateway-worker"}),
        identity=metadata,
        artifact_sha256=_sha256_bytes(raw),
        verifier_command=["python", "-m", "examples.dsh.rsi_closed.worker_verifier"],
        verifier_stdout=json.dumps(result),
    )
    assert task.reward == 1 and receipt["schema"] == "dsh.verifier-receipt.v1"
    assert receipt["verifier"]["id"] == metadata["verifier_id"]
    for key, wrong in [
        ("DSH_DSH_SESSION_ID", "wrong"),
        ("DSH_ENVIRONMENT_DIGEST", "sha256:" + "0" * 64),
        ("DSH_VERIFIER_CODE_DIGEST", "sha256:" + "1" * 64),
    ]:
        with monkeypatch.context() as scoped:
            scoped.setenv(key, wrong)
            with pytest.raises(RuntimeError):
                verify()
    assert metadata["environment_digest"] == RUNTIME_SHA256


def test_rows_pass_existing_task_identity_contract(cases):
    from types import SimpleNamespace

    from uni_agent.tasks.dsh.task import _task_identity

    for row in cases[1]:
        config = SimpleNamespace(
            metadata=row["metadata"],
            environment_digest=None,
            verifier_id=None,
            verifier_version=None,
            verifier_code_digest=None,
        )
        identity = _task_identity(config)
        assert identity["split"] == "validation"
        assert row["metadata"]["dataset_role"] == "development"


def ranged_file_episode(cases, bounds):
    root, contract, events, answer = episode(cases, "file")
    args = json.loads(events[0]["data"]["arguments"])
    args["view_range"] = bounds
    events[0] = _call("a", "str_replace_editor", args, seq=0)
    return root, contract, events, answer


@pytest.mark.parametrize("bounds", [None, [1, -1], [1, 3], [1, 4]])
def test_worker_full_ranges_include_runtime_trailing_empty_line(cases, bounds):
    root, contract, events, answer = ranged_file_episode(cases, bounds)
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["eligible"] is True and value["reward"] == 1


@pytest.mark.parametrize("full_result", [False, True])
def test_worker_partial_range_is_safe_without_full_read_credit(cases, full_result):
    root, contract, events, answer = ranged_file_episode(cases, [2, 2])
    if not full_result:
        events[1] = _result("a", "     2  max_attempts=3")
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["eligible"] is True and value["reward"] == 0
    assert value["extra_info"]["successful_call_ids"] == []
    assert value["extra_info"]["matched_call_ids"] == ["a"]


@pytest.mark.parametrize(
    "bounds", [[], [1], [1, 2, 3], [0, 2], [True, 3], [1, False], [3, 2], [1, -2], "1,3", [1, 5], [5, -1]]
)
def test_worker_invalid_or_out_of_bounds_ranges_rejected(cases, bounds):
    root, contract, events, answer = ranged_file_episode(cases, bounds)
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["eligible"] is False and value["reward"] == 0


def test_worker_full_range_still_requires_actual_full_result(cases):
    root, contract, events, answer = ranged_file_episode(cases, [1, -1])
    events[1] = _result("a", "     2  max_attempts=3")
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["eligible"] is True and value["reward"] == 0


def test_worker_range_cannot_substitute_for_quoted_line(cases):
    root, contract, events, answer = ranged_file_episode(cases, [1, 1])
    events[1] = _result("a", "     1  scope=release-check")
    value = score(contract, root, events, json.dumps(answer), True)
    assert value["eligible"] is False and value["reward"] == 0
    answer = {"status": "unavailable", "value": None, "citation": None}
    assert score(contract, root, events, json.dumps(answer), True)["eligible"] is True
