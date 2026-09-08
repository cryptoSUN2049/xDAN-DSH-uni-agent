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


def test_explicit_prompt_preserves_utf8_and_newlines(tmp_path):
    import hashlib

    from deployment.checks.dsh_log_tool_smoke import load_prompt

    raw = "  筛选日志\r\n保留末尾\n".encode()
    path = tmp_path / "prompt.txt"
    path.write_bytes(raw)
    prompt = load_prompt(path)
    assert prompt["initial_prompt"].encode() == raw
    assert prompt["initial_prompt_sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert prompt["prompt_source"] == "file"
    path.write_text(" \n\t")
    with pytest.raises(ValueError, match="blank"):
        load_prompt(path)


def test_default_prompt_retains_diagnostic_scope():
    from deployment.checks.dsh_log_tool_smoke import load_prompt

    prompt = load_prompt(None)
    assert prompt["initial_prompt"] == "Execute the scripted-policy integration smoke. No model capability claim."
    assert prompt["prompt_source"] == "default-diagnostic"


def test_sdk_and_report_receive_same_prompt(tmp_path, monkeypatch):
    """Wiring test with a fake SDK; does not claim a runtime integration result."""
    import json
    import sys
    import types
    import urllib.request

    from deployment.checks.dsh_log_tool_smoke import run
    from examples.dsh.capability_tasks.log_tool import verifier

    raw = "业务任务\r\n精确原文\n"
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_bytes(raw.encode())
    fixture = tmp_path / "fixture.json"
    fixture.write_text('{"calls": []}')
    seen = []

    class Harness:
        def __init__(self, config):
            self.config = config

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def run(self, prompt):
            seen.append(prompt)
            request = urllib.request.Request(
                self.config.base_url,
                data=json.dumps({"messages": [{"role": "user", "content": prompt}]}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                response.read()
            return types.SimpleNamespace(events=[], session_id="test", finish_reason="completed")

    monkeypatch.setitem(
        sys.modules,
        "deepseek_harness",
        types.SimpleNamespace(
            DeepSeekHarness=Harness,
            DeepSeekHarnessConfig=types.SimpleNamespace,
        ),
    )
    monkeypatch.setattr(verifier, "verify_trace", lambda *args, **kwargs: {"passed": True})
    output = tmp_path / "output"
    report = run(fixture, output, prompt_file=prompt_file)
    assert seen == [raw]
    assert report["initial_prompt"] == raw
    assert report["policy_origin"] == "scripted"
    requests = json.loads((output / "requests.json").read_text())
    assert requests[0]["messages"][0]["content"] == raw
    assert json.loads((output / "report.json").read_text())["initial_prompt"] == raw


def test_invalid_prompt_fails_before_output_or_sdk(tmp_path):
    from deployment.checks.dsh_log_tool_smoke import run

    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff")
    output = tmp_path / "never-created"
    with pytest.raises(UnicodeDecodeError):
        run(tmp_path / "not-read.json", output, prompt_file=path)
    assert not output.exists()
