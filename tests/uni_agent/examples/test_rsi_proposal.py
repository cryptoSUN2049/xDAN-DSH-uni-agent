"""CPU contract tests; no student evidence or registration from synthetic fixtures."""

import json

import pytest

from examples.dsh.rsi_closed import proposal

PARENT = {"schema": "dsh.rsi-profile.v1", "profile": "sdk-minimal", "allowed_tools": ["str_replace_editor"]}
CHILD = {**PARENT, "allowed_tools": ["cordis_inspect_list", "str_replace_editor"]}


def test_parser_retains_exact_raw_output():
    raw = "  " + json.dumps(CHILD) + "\n"
    parsed = proposal.parse_response(raw, PARENT)
    assert parsed["spec"] == CHILD
    assert parsed["changed"]
    assert parsed["raw_response_sha256"] != parsed["content_sha256"]


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{}\n```",
        "{",
        "[]",
        '{"schema":1,"schema":2}',
        '{"schema":NaN}',
        json.dumps({**CHILD, "promote": True}),
        json.dumps({**CHILD, "allowed_tools": ["bash"]}),
        json.dumps({**CHILD, "allowed_tools": ["str_replace_editor"] * 2}),
    ],
)
def test_parser_does_not_repair_or_expand_student_output(raw):
    with pytest.raises(ValueError):
        proposal.parse_response(raw, PARENT)


def test_no_change_is_not_a_candidate():
    assert not proposal.parse_response(json.dumps(PARENT), PARENT)["changed"]


def test_wrong_sdk_source_rejected(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("deepseek_harness.api")
    fake.__file__ = __file__
    fake.final_response = lambda events: "fabricated"
    package = types.ModuleType("deepseek_harness")
    package.api = fake
    monkeypatch.setitem(sys.modules, "deepseek_harness", package)
    monkeypatch.setitem(sys.modules, "deepseek_harness.api", fake)
    with pytest.raises(RuntimeError, match="SDK"):
        proposal.sdk_final_response([])


@pytest.fixture
def scored_input(monkeypatch):
    from examples.dsh.rsi_closed.prepare_worker_eval import canonical_hash

    diagnostics = {"cases": []}
    contract = {
        "schema": "dsh.rsi-proposal.v1",
        "pair_id": "unit",
        "parent_active_sha256": "sha256:" + "1" * 64,
        "parent_candidate_sha256": "sha256:" + "2" * 64,
        "parent_content_sha256": canonical_hash(PARENT),
        "pins_sha256": "sha256:" + "3" * 64,
        "model_sha256": "sha256:" + "4" * 64,
        "runtime_sha256": proposal.RUNTIME_SHA256,
        "worker_devset_sha256": "sha256:" + "5" * 64,
        "diagnostics": diagnostics,
        "diagnostics_sha256": canonical_hash(diagnostics),
        "parent_spec": PARENT,
        "messages": proposal.messages(diagnostics),
        "sdk_api_sha256": proposal.SDK_API_SHA256,
    }
    raw = json.dumps(CHILD)
    events = [
        {"type": "assistant/message", "data": {"response": raw}},
        {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
    ]
    # Explicit test SDK substitute; production always imports and hashes the pinned real SDK.
    monkeypatch.setattr(proposal, "sdk_final_response", lambda ev: ev[0]["data"]["response"])
    return contract, {"prompt": contract["messages"], "response": raw, "finished": True}, events


def test_proposal_format_reward_is_not_promotion(scored_input):
    report = proposal.score(*scored_input)
    assert report["reward"] == 1
    assert not report["extra_info"]["promotion_verified"]


@pytest.mark.parametrize("fault", ["response", "prompt", "diagnostics", "sdk-pin"])
def test_proposal_identity_mismatch_fails(scored_input, fault):
    contract, envelope, events = scored_input
    if fault == "response":
        envelope["response"] = json.dumps(PARENT)
    elif fault == "prompt":
        envelope["prompt"] = []
    elif fault == "diagnostics":
        contract["diagnostics"] = {"forged": True}
    else:
        contract["sdk_api_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(RuntimeError):
        proposal.score(contract, envelope, events)


@pytest.mark.parametrize(
    "raw,eligible", [(json.dumps(PARENT), True), ("{", True), (json.dumps({**CHILD, "promote": True}), False)]
)
def test_proposal_failure_never_receives_format_credit(scored_input, raw, eligible):
    contract, envelope, events = scored_input
    envelope["response"] = events[0]["data"]["response"] = raw
    value = proposal.score(contract, envelope, events)
    assert value["reward"] == 0
    assert value["eligible"] is eligible
