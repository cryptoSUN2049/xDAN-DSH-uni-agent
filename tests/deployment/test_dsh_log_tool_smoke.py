import pytest

from deployment.checks.dsh_log_tool_smoke import ScriptedPolicy


def test_first_call_and_budget():
    policy = ScriptedPolicy([{"records": []}])
    chunks = policy.respond({"messages": [{"role": "user", "content": "start"}]})
    assert chunks[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "cordis_inspect_self"
    with pytest.raises(ValueError, match="tool result"):
        policy.respond({"messages": [{"role": "user", "content": "start"}]})


def test_define_ids_must_come_from_exact_real_result():
    policy = ScriptedPolicy([{"records": []}])
    policy.step = 3
    with pytest.raises(ValueError, match="define"):
        policy.respond({"messages": [{"role": "tool", "content": "Failed: no plugin"}]})
    policy.step = 3
    chunks = policy.respond(
        {
            "messages": [
                {
                    "role": "tool",
                    "content": "Defined P/Q (log); it is not running yet. Use cordis_run to activate this Package.",
                }
            ]
        }
    )
    import json

    args = json.loads(chunks[1]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"])
    assert args == {"pluginId": "P", "packageId": "Q", "mode": "run"}


def test_request_budget_rejects_retries_after_completion():
    policy = ScriptedPolicy([])
    policy.step = 10
    body = {"messages": [{"role": "tool", "content": "{}"}]}
    assert policy.respond(body)[0]["choices"][0]["finish_reason"] == "stop"
    with pytest.raises(ValueError, match="budget"):
        policy.respond(body)


def test_script_uses_every_fixture_input_and_cleanup_order():
    import json

    calls = [{"records": [], "severity": None}, {"records": [], "severity": "ERROR"}]
    policy = ScriptedPolicy(calls)
    policy.plugin, policy.package = "actual-plugin", "actual-package"
    policy.step = 6
    functions = []
    for _ in range(6):
        result = policy.respond({"messages": [{"role": "tool", "content": "[]"}]})
        functions.append(result[1]["choices"][0]["delta"]["tool_calls"][0]["function"])
    assert [f["name"] for f in functions] == [
        "filter_redact_logs",
        "filter_redact_logs",
        "cordis_stop",
        "cordis_inspect_query",
        "cordis_undefine",
        "cordis_inspect_self",
    ]
    assert [json.loads(f["arguments"]) for f in functions[:2]] == calls
    assert json.loads(functions[2]["arguments"]) == {"pluginId": "actual-plugin"}


def test_source_sdk_without_distribution_metadata_is_explicit(monkeypatch):
    import importlib.metadata

    from deployment.checks.dsh_log_tool_smoke import sdk_version

    def absent(_name):
        raise importlib.metadata.PackageNotFoundError("deepseek-harness-sdk")

    monkeypatch.setattr(importlib.metadata, "version", absent)
    assert sdk_version() is None
