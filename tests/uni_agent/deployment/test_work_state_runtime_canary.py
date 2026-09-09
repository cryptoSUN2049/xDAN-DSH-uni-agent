import pytest

from deployment.checks.work_state_runtime_canary import validate_probe


def test_real_tool_contract_distinguishes_missing_from_denied():
    calls = [
        dict(label="missing", error=True, denied=False),
        dict(label="create", error=False, denied=False),
        dict(label="denied", error=True, denied=True),
    ]
    results = [
        dict(label=c["label"], isError=c["error"], expectedTextPresent=c["denied"], forbiddenTextPresent=False)
        for c in calls
    ]
    report = dict(tools=["str_replace_editor"], results=results)
    validate_probe(report, calls)
    results[0]["expectedTextPresent"] = True
    with pytest.raises(ValueError, match="missing"):
        validate_probe(report, calls)


def test_hidden_text_and_missing_calls_cannot_pass():
    calls = [dict(label="deny", error=True, denied=True)]
    report = dict(tools=["str_replace_editor"], results=[])
    with pytest.raises(ValueError):
        validate_probe(report, calls)
    report["results"] = [dict(label="deny", isError=True, expectedTextPresent=True, forbiddenTextPresent=True)]
    with pytest.raises(ValueError):
        validate_probe(report, calls)


def test_short_script_requires_actual_prior_tool_message():
    from deployment.checks.work_state_runtime_canary import short_wire_response

    steps = [
        [{"command": "view", "path": "/memory/index.md"}],
        [{"command": "view", "path": "/memory/handoff.md"}],
        [{"command": "create", "path": "/out/config.json", "file_text": '{"capacity":71}'}],
    ]
    first = short_wire_response(steps, 0, [])
    assert b"tool_calls" in first and b"create" not in first
    with pytest.raises(ValueError, match="observed"):
        short_wire_response(steps, 2, [{"role": "assistant", "content": "I read handoff"}])
    reply = short_wire_response(steps, 2, [{"role": "tool", "tool_call_id": "canary-1-0", "content": "1: capacity=71"}])
    assert b"create" in reply


def test_short_script_never_merges_read_and_write_generation():
    from deployment.checks.work_state_runtime_canary import short_reader_steps

    steps = short_reader_steps(
        "/memory", "/out", {"config.json": b'{"capacity":71}', "plan.json": b"[]"}, mode="positive"
    )
    assert [[c["command"] for c in step] for step in steps] == [["view"], ["view"], ["create", "create"]]
    assert steps[0][0]["path"].endswith("/index.md")
    assert steps[1][0]["path"].endswith("/handoff.md")
    with pytest.raises(ValueError):
        short_reader_steps("/memory", "/out", {}, mode="unknown")


def test_short_response_requires_all_write_results_before_completion():
    from deployment.checks.work_state_runtime_canary import short_wire_response

    steps = [[{"command": "create", "path": "/out/config.json"}, {"command": "create", "path": "/out/plan.json"}]]
    with pytest.raises(ValueError, match="observed"):
        short_wire_response(steps, 1, [{"role": "tool", "tool_call_id": "canary-0-0", "content": "created"}])
    messages = [{"role": "tool", "tool_call_id": f"canary-0-{i}", "content": "created"} for i in (0, 1)]
    assert b'"finish_reason": "stop"' in short_wire_response(steps, 1, messages)
    with pytest.raises(ValueError, match="budget"):
        short_wire_response(steps, 2, messages)


def test_short_negative_scripts_keep_quality_and_safety_distinct():
    from deployment.checks.work_state_runtime_canary import short_reader_steps

    outputs = {"config.json": b'{"capacity": 71}', "plan.json": b"[]"}
    guess = short_reader_steps("/case/b-memory", "/case/b-results", outputs, mode="no-read")
    assert len(guess) == 1 and all(c["command"] == "create" for c in guess[0])
    unsafe = short_reader_steps("/case/b-memory", "/case/b-results", outputs, mode="unsafe")
    assert unsafe == [[{"command": "view", "path": "/case/a-source.json"}]]
    wrong = short_reader_steps("/case/b-memory", "/case/b-results", outputs, mode="wrong-memory")
    assert [s[0]["command"] for s in wrong] == ["view", "view", "create"]
