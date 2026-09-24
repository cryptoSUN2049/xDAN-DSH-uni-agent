"""Protocol acceptance tests with mocked HTTP; no model service or network needed."""

import json
import threading

import pytest

from examples.performance_9b import mimo_identity_probe as module


class Response:
    status = 200

    def __init__(self, message, finish="stop"):
        self.payload = {"choices": [{"finish_reason": finish, "message": message}]}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return json.dumps(self.payload).encode()


def probe(tmp_path):
    return module.Probe("http://127.0.0.1:8019", "apus-9b-probe", tmp_path)


def test_four_groups_run_at_most_three_concurrently_and_return_fixed_order(tmp_path, monkeypatch):
    lock, barrier = threading.Lock(), threading.Barrier(3)
    state = {"active": 0, "peak": 0, "requests": 0}

    def respond(request, timeout):
        body = json.loads(request.data)
        assert timeout > 0
        assert body["max_tokens"] == 4096
        assert body["temperature"] == 0
        assert body["chat_template_kwargs"]["enable_thinking"] is True
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            state["requests"] += 1
            initial_wave = state["requests"] <= 3
        try:
            if initial_wave:
                barrier.wait(timeout=5)
            return Response({"role": "assistant", "content": "Model unknown.", "reasoning": "Check provenance."})
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(module.urllib.request, "urlopen", respond)
    results, multi_turn = module.identity_suite(probe(tmp_path))
    assert len(module.SYSTEMS) == 4
    assert len(results) == state["requests"] == 88
    assert state["peak"] == 3
    expected = []
    for system_name in module.SYSTEMS:
        expected.extend(f"{system_name}_{question}" for question in module.QUESTIONS)
        expected.extend([f"{system_name}_multiturn_1", f"{system_name}_multiturn_2"])
    assert [record["name"] for record, _ in results] == expected
    assert list(multi_turn) == [f"{name}_multiturn" for name in module.SYSTEMS]
    assert all(item["followup_sent"] for item in multi_turn.values())
    for name in module.SYSTEMS:
        saved = json.loads((tmp_path / f"{name}_multiturn_2.json").read_text())
        assert saved["prompt_kind"] == "multiturn"
        assert saved["turn_index"] == 2
        assert saved["request"]["messages"][-2]["content"] == "Model unknown."
        assert saved["request"]["messages"][-2]["reasoning_content"] == "Check provenance."
        assert json.loads(saved["raw_response"]) == saved["response"]


def test_truncated_first_turn_never_sends_followup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response({"content": "Partial answer"}, finish="length"),
    )
    results, multi_turn = module.identity_suite(probe(tmp_path))
    assert len(results) == 84
    assert all(info["truncated"] and not info["completed"] for _, info in results)
    assert all(not item["followup_sent"] for item in multi_turn.values())
    assert not list(tmp_path.glob("*_multiturn_2.json"))


def call_message(name="add", arguments=None, reasoning_field="reasoning"):
    return {
        "role": "assistant",
        "content": None,
        reasoning_field: "Use the calculator.",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps({"a": 137, "b": 286} if arguments is None else arguments),
                },
            }
        ],
    }


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("shell", {"a": 137, "b": 286}),
        ("add", {"a": "137", "b": 286}),
        ("add", {"a": True, "b": 286}),
        ("add", {"a": float("nan"), "b": 286}),
        ("add", {"a": float("inf"), "b": 286}),
        ("add", {"a": {"command": "anything"}, "b": 286}),
    ],
)
def test_tool_rejects_unknown_names_and_non_numeric_or_nonfinite_arguments(tmp_path, monkeypatch, name, arguments):
    requests = []

    def respond(request, **_kwargs):
        requests.append(json.loads(request.data))
        return Response(call_message(name, arguments), finish="tool_calls")

    monkeypatch.setattr(module.urllib.request, "urlopen", respond)
    result = module.tool_loop(probe(tmp_path))
    assert result["passed"] is False
    assert result["tool_executed"] is False
    assert len(requests) == 1
    assert not (tmp_path / "tool_2.json").exists()


@pytest.mark.parametrize("reasoning_field", ["reasoning", "reasoning_content"])
@pytest.mark.parametrize("finish", ["stop", "length"])
def test_real_add_result_is_replayed_and_reasoning_is_mapped(tmp_path, monkeypatch, reasoning_field, finish):
    requests = []
    first_message = call_message(reasoning_field=reasoning_field)

    def respond(request, **_kwargs):
        body = json.loads(request.data)
        requests.append(body)
        if len(requests) == 1:
            return Response(first_message, finish="tool_calls")
        assistant, tool = body["messages"][-2:]
        assert assistant["reasoning_content"] == "Use the calculator."
        assert assistant["tool_calls"] == first_message["tool_calls"]
        assert isinstance(assistant["tool_calls"][0]["function"]["arguments"], str)
        assert tool["role"] == "tool" and tool["tool_call_id"] == "call-1"
        assert json.loads(tool["content"]) == {"result": 423}
        return Response({"role": "assistant", "content": "The result is 423."}, finish=finish)

    monkeypatch.setattr(module.urllib.request, "urlopen", respond)
    result = module.tool_loop(probe(tmp_path))
    assert len(requests) == 2
    assert result["tool_executed"] is True
    assert result["actual_result"] == 423
    assert result["passed"] is (finish == "stop")
    assert result["final_observation"]["truncated"] is (finish == "length")
