from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.uni_agent.support import FakeTokenizer
from uni_agent.gateway.session.codec import MessageCodec


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["length", "max_tokens", "aborted", "abort"])
@pytest.mark.parametrize("text", ['<tool_call>{"name":"write"}</tool_call>', "<tool_call>{", "ordinary text"])
async def test_terminal_reason_cannot_trigger_tool_parser(monkeypatch, reason, text):
    codec = MessageCodec(FakeTokenizer(), tool_parser_name="hermes")

    async def parser(*args, **kwargs):
        pytest.fail("Terminal generation must not invoke the tool parser")

    monkeypatch.setattr(codec, "_extract_tool_calls", parser)
    if reason in ("abort", "aborted"):
        with pytest.raises(HTTPException) as caught:
            await codec.decode_response(list(map(ord, text)), tools=[{"name": "write"}], stop_reason=reason)
        assert caught.value.status_code == 409
    else:
        message, finish = await codec.decode_response(
            list(map(ord, text)), tools=[{"name": "write"}], stop_reason=reason
        )
        assert finish == "length" and message == {"role": "assistant", "content": text}


@pytest.mark.asyncio
async def test_natural_stop_keeps_tool_calls(monkeypatch):
    codec = MessageCodec(FakeTokenizer(), tool_parser_name="hermes")

    async def parser(*args, **kwargs):
        return "", [SimpleNamespace(name="write", arguments="{}")]

    monkeypatch.setattr(codec, "_extract_tool_calls", parser)
    message, finish = await codec.decode_response([65], tools=[{"name": "write"}], stop_reason="completed")
    assert finish == "tool_calls" and len(message["tool_calls"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["length", "aborted", "abort"])
async def test_real_gateway_http_terminal_state(monkeypatch, reason):
    import json

    import httpx

    from tests.uni_agent.support import SequencedBackend
    from uni_agent.gateway.config import GatewayActorConfig
    from uni_agent.gateway.gateway import _GatewayActor

    text = '<tool_call>{"name":"write","arguments":{}}</tool_call>'

    class Backend(SequencedBackend):
        async def generate(self, *args, **kwargs):
            result = await super().generate(*args, **kwargs)
            result.stop_reason = reason
            return result

    backend = Backend([text])
    actor = _GatewayActor(GatewayActorConfig(tokenizer=FakeTokenizer(), tool_parser_name="hermes"), backend)
    actor._server_base_url = "http://test"
    await actor.create_session("terminal")

    async def parser(*args, **kwargs):
        pytest.fail("Terminal output must not call parser")

    monkeypatch.setattr(actor._codec, "_extract_tool_calls", parser)
    request = {
        "messages": [{"role": "user", "content": "run"}],
        "tools": [{"type": "function", "function": {"name": "write", "parameters": {}}}],
        "stream": True,
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=actor._app), base_url="http://test") as client:
        response = await client.post("/sessions/terminal/v1/chat/completions", json=request)
        if reason == "length":
            assert response.status_code == 200 and response.text.endswith("data: [DONE]\n\n")
            chunks = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
            assert chunks[-1]["choices"][0]["finish_reason"] == "length"
            assert all("tool_calls" not in c["choices"][0]["delta"] for c in chunks)
            trajectories = await actor.finalize_session("terminal")
            assert trajectories[0].response_ids == list(map(ord, text))
        else:
            assert response.status_code == 409 and "aborted" in response.text
            state = await actor.get_session_state("terminal")
            assert state["phase"] == "ABORTED" and state["num_active_chains"] == 0
            again = await client.post("/sessions/terminal/v1/chat/completions", json=request)
            assert again.status_code == 409 and len(backend.calls) == 1
            with pytest.raises(RuntimeError, match="aborted"):
                await actor.finalize_session("terminal")
