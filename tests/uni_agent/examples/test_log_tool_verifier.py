import copy
import hashlib
import json

import pytest

from examples.dsh.capability_tasks.log_tool.oracle import evaluate
from tests.uni_agent.tasks.test_dsh_evolution_v3_live_verifier import _call, _result, _terminal

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def valid():
    calls = [
        dict(
            records=[dict(timestamp=str(i), service="api", severity="ERROR", message=f"u{i}@example.com")],
            severity="ERROR",
            service="api",
        )
        for i in (1, 2)
    ]
    events = []

    def add(name, args, value):
        cid = str(len(events))
        events.extend([_call(cid, name, args), _result(cid, value)])

    query = dict(platform="host", provider="Tool", method="listTools")

    def inventory(names):
        return dict(**query, data={"tools": [{"name": name} for name in names]})

    add("cordis_inspect_self", {}, dict(mode="plugins", plugins=[]))
    add("cordis_inspect_query", query, inventory([]))
    add(
        "cordis_define",
        dict(plugin=dict(kind="new", idPrefix="log"), name="Log", purpose="filter", code={"host": "code"}),
        "Defined log-1/pkg-1 (Log); it is not running yet. Use cordis_run to activate it.",
    )
    add(
        "cordis_run",
        dict(pluginId="log-1", packageId="pkg-1", mode="run"),
        "log-1/pkg-1 is starting asynchronously (run-1).",
    )
    add(
        "cordis_inspect_self",
        dict(pluginId="log-1"),
        dict(
            mode="plugin",
            pluginId="log-1",
            state="running",
            currentPackageId="pkg-1",
            activeRun=dict(packageId="pkg-1", pluginRunId="run-1"),
        ),
    )
    add("cordis_inspect_query", query, inventory(["filter_redact_logs"]))
    for call in calls:
        add("filter_redact_logs", call, evaluate(**call))
    add("cordis_stop", dict(pluginId="log-1"), "Dynamic Plugin log-1 is stopped; its definition and versions remain.")
    add("cordis_inspect_query", query, inventory([]))
    add("cordis_undefine", dict(pluginId="log-1"), "Removed dynamic Plugin log-1 and all of its Packages.")
    add("cordis_inspect_self", {}, dict(mode="plugins", plugins=[]))
    return _terminal(events), dict(calls=calls)


def test_valid_bound_lifecycle(valid, tmp_path):
    from examples.dsh.capability_tasks.log_tool.verifier import verify_trace

    events, fixture = valid
    raw = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
    path = tmp_path / "trace.jsonl"
    path.write_bytes(raw)
    result = verify_trace(path, "sha256:" + hashlib.sha256(raw).hexdigest(), fixture=fixture)
    assert result["passed"], result
    assert result["plugin_run_id"] == "run-1"
    assert result["hidden_inputs_verified"] is False


@pytest.mark.parametrize(
    "mutation", ["duplicate", "wrong-plugin", "wrong-run", "bad-output", "failed", "no-cleanup", "orphan"]
)
def test_rejects_mutated_evidence(valid, mutation):
    from examples.dsh.capability_tasks.log_tool.verifier import evaluate_events

    events, fixture = copy.deepcopy(valid)
    if mutation == "duplicate":
        events[2:2] = copy.deepcopy(events[:2])
    elif mutation == "wrong-plugin":
        events[16]["data"]["arguments"] = json.dumps(dict(pluginId="other"))
    elif mutation == "wrong-run":
        value = json.loads(events[9]["data"]["message"]["content"][0]["content"][0]["text"])
        value["activeRun"]["pluginRunId"] = "other"
        events[9] = _result("8", value)
    elif mutation == "bad-output":
        events[13] = _result("12", [])
    elif mutation == "failed":
        events[17] = _result("16", "stopped", error=True)
    elif mutation == "no-cleanup":
        events[-3:-1] = []
    else:
        events.insert(0, _result("unknown", {}))
    assert not evaluate_events(events, fixture=fixture)["passed"]


@pytest.mark.parametrize(
    "mutation", ["missing-success", "duplicate-input", "not-revoked", "wrong-package", "swapped-result"]
)
def test_additional_rejections(valid, mutation):
    from examples.dsh.capability_tasks.log_tool.verifier import evaluate_events

    events, fixture = copy.deepcopy(valid)
    if mutation == "missing-success":
        del events[13]["data"]["message"]["content"][0]["isError"]
    elif mutation == "duplicate-input":
        events[14]["data"]["arguments"] = events[12]["data"]["arguments"]
        events[15] = _result("14", evaluate(**fixture["calls"][0]))
    elif mutation == "not-revoked":
        events[19] = _result(
            "18",
            dict(
                platform="host", provider="Tool", method="listTools", data={"tools": [{"name": "filter_redact_logs"}]}
            ),
        )
    elif mutation == "wrong-package":
        events[6]["data"]["arguments"] = json.dumps(dict(pluginId="log-1", packageId="other", mode="run"))
    else:
        events[13], events[15] = events[15], events[13]
    assert not evaluate_events(events, fixture=fixture)["passed"]


def test_hash_mismatch_raises_instead_of_scoring_zero(valid, tmp_path):
    from examples.dsh.capability_tasks.log_tool.verifier import verify_trace

    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in valid[0]))
    with pytest.raises(RuntimeError, match="hash|match"):
        verify_trace(path, "sha256:" + "0" * 64, fixture=valid[1])


@pytest.mark.parametrize("kind", ["business", "cleanup", "tool-error", "duplicate"])
def test_trusted_task_failures_remain_reward_zero_eligible(valid, kind):
    from examples.dsh.capability_tasks.log_tool.verifier import evaluate_events

    events, fixture = copy.deepcopy(valid)
    if kind == "business":
        events[13] = _result("12", [])
    elif kind == "cleanup":
        events[-3:-1] = []
    elif kind == "tool-error":
        events[13] = _result("12", "invalid student arguments", error=True)
    else:
        events[2:2] = copy.deepcopy(events[:2])
    result = evaluate_events(events, fixture=fixture)
    assert result["passed"] is False
    assert result["eligible"] is (kind != "duplicate")


def test_missing_public_call_is_eligible_failure_even_with_two_distinct_records(valid):
    from examples.dsh.capability_tasks.log_tool.verifier import evaluate_events

    events, fixture = copy.deepcopy(valid)
    fixture["calls"].append(dict(fixture["calls"][0], severity=None))
    result = evaluate_events(events, fixture=fixture)
    assert result["passed"] is False
    assert result["eligible"] is True
    assert "missing-public-fixture-call" in result["reasons"]


@pytest.mark.parametrize("query_input,passed", [({}, True), ({"unexpected": 1}, False)])
def test_optional_empty_inventory_input_is_equivalent(valid, query_input, passed):
    from examples.dsh.capability_tasks.log_tool.verifier import evaluate_events

    events, fixture = copy.deepcopy(valid)
    for event in events:
        if event["type"] == "tool/call" and event["data"]["name"] == "cordis_inspect_query":
            args = json.loads(event["data"]["arguments"])
            args["input"] = query_input
            event["data"]["arguments"] = json.dumps(args)
    assert evaluate_events(events, fixture=fixture)["passed"] is passed
