import asyncio

import pytest
from fastapi import HTTPException

from tests.uni_agent.gateway.test_session_multiple_chains_on_cpu import _run
from tests.uni_agent.support import FakeTokenizer
from uni_agent.gateway.session import GatewaySession, MessageCodec, SessionHandle
from verl.workers.rollout.replica import TokenOutput


def session(budget):
    return GatewaySession(SessionHandle("budget"), MessageCodec(FakeTokenizer()), max_generated_tokens=budget)


class Backend:
    def __init__(self, fault=None):
        self.caps = []
        self.fault = fault

    async def generate(self, request_id, *, prompt_ids, sampling_params, **kwargs):
        cap = sampling_params["max_tokens"]
        self.caps.append(cap)
        await asyncio.sleep(0)
        if self.fault == "error":
            raise RuntimeError("unknown backend completion")
        count = cap + 1 if self.fault == "overflow" else min(3, cap)
        return TokenOutput(token_ids=[65] * count, stop_reason="completed")


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "8"])
def test_budget_rejects_invalid(budget):
    with pytest.raises(ValueError, match="max_generated_tokens"):
        session(budget)


@pytest.mark.asyncio
async def test_budget_counts_backend_only_and_cannot_be_overridden():
    s, b = session(5), Backend()
    messages = [{"role": "user", "content": "task"}]
    first = await _run(s, b, messages, max_tokens=3)
    messages += [first.assistant_msg, {"role": "user", "content": "tool feedback " * 100}]
    await _run(s, b, messages, max_tokens=999)
    end = await _run(s, b, [{"role": "user", "content": "new chain"}], max_tokens=999)
    assert b.caps == [3, 2]
    assert end.finish_reason == "length" and end.completion_tokens == 0
    assert s._generated_tokens == 5


@pytest.mark.asyncio
async def test_concurrent_budget_requests_do_not_overallocate():
    s, b = session(5), Backend()
    results = await asyncio.gather(
        *[_run(s, b, [{"role": "user", "content": str(i)}], max_tokens=99) for i in range(3)]
    )
    assert b.caps == [5, 2]
    assert sum(r.completion_tokens for r in results) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["error", "overflow"])
async def test_unknown_or_excess_backend_output_blocks_retry(fault):
    s, b = session(5), Backend(fault)
    with pytest.raises(HTTPException):
        await _run(s, b, [{"role": "user", "content": "task"}], max_tokens=5)
    b.fault = None
    with pytest.raises(HTTPException):
        await _run(s, b, [{"role": "user", "content": "retry"}], max_tokens=5)
    assert len(b.caps) == 1


@pytest.mark.asyncio
async def test_rollback_does_not_refund_completion_budget():
    s, b = session(5), Backend()
    messages = [{"role": "user", "content": "task"}]
    await _run(s, b, messages, max_tokens=3)
    await _run(s, b, messages, max_tokens=99)
    assert b.caps == [3, 2]
    assert s._generated_tokens == 5


@pytest.mark.asyncio
async def test_backend_parameter_mutation_cannot_change_saved_cap():
    class Mutating(Backend):
        async def generate(self, request_id, *, sampling_params, **kwargs):
            cap = sampling_params.pop("max_tokens")
            return TokenOutput(token_ids=[65] * (cap + 1), stop_reason="completed")

    s = session(2)
    with pytest.raises(HTTPException, match="Backend exceeded"):
        await _run(s, Mutating(), [{"role": "user", "content": "task"}], max_tokens=2)
    assert s._generated_tokens == 3 and s._generation_budget_failed


@pytest.mark.asyncio
async def test_cancelled_unknown_backend_cannot_retry():
    started = asyncio.Event()

    class Hanging(Backend):
        async def generate(self, **kwargs):
            started.set()
            await asyncio.Event().wait()

    s = session(5)
    task = asyncio.create_task(_run(s, Hanging(), [{"role": "user", "content": "task"}], max_tokens=5))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(HTTPException, match="cannot continue"):
        await _run(s, Backend(), [{"role": "user", "content": "retry"}], max_tokens=5)


@pytest.mark.asyncio
async def test_post_generation_failure_does_not_refund():
    s, b = session(5), Backend()
    s._sampling_params["logprobs"] = True
    with pytest.raises(RuntimeError, match="omitted logprobs"):
        await _run(s, b, [{"role": "user", "content": "task"}], max_tokens=3)
    assert s._generated_tokens == 3
    with pytest.raises(HTTPException):
        await _run(s, b, [{"role": "user", "content": "retry"}], max_tokens=5)
    assert len(b.caps) == 1


@pytest.mark.asyncio
async def test_budget_evidence_is_gateway_owned_and_forks_share_ledger():
    s, b = session(5), Backend()
    s._metadata.update(max_generated_tokens=999, session_generated_tokens_at_materialization=0)
    await _run(s, b, [{"role": "system", "content": "first"}, {"role": "user", "content": "task"}], max_tokens=3)
    await _run(s, b, [{"role": "system", "content": "second"}, {"role": "user", "content": "fork"}], max_tokens=5)
    trajectories = await s.finalize()
    assert b.caps == [3, 2]
    assert all(t.extra_fields["max_generated_tokens"] == 5 for t in trajectories)
    assert all(t.extra_fields["session_generated_tokens_at_materialization"] == 5 for t in trajectories)


@pytest.mark.asyncio
async def test_budget_exhaustion_reason_and_dump_are_persisted(tmp_path):
    import json

    from tests.uni_agent.framework.test_gateway_stage_execution import build

    s, b = session(3), Backend()
    prompt = [{"role": "user", "content": "task"}]
    first = await _run(s, b, prompt, max_tokens=3)
    end = await _run(s, b, prompt + [first.assistant_msg, {"role": "user", "content": "continue"}], max_tokens=3)
    trajectories = await s.finalize()
    assert end.finish_reason == "length"
    assert trajectories[0].extra_fields["materialization_reason"] == "max_generated_tokens"
    framework, _, args = build(tmp_path, trajectories=trajectories)
    result = await framework._execute_gateway_stage(**args, stage_session_id="dump-budget")
    summary = json.loads((result.run_dir / "trajectory.json").read_text())["trajectories"][0]
    assert summary["max_generated_tokens"] == 3
    assert summary["session_generated_tokens_at_materialization"] == 3


@pytest.mark.asyncio
async def test_pre_backend_invalid_request_poison_is_explicit(monkeypatch):
    s, b = session(3), Backend()

    async def invalid(*args):
        raise ValueError("invalid request")

    monkeypatch.setattr(s, "_prepare_generation_inputs", invalid)
    with pytest.raises(ValueError, match="invalid request"):
        await _run(s, b, [{"role": "user", "content": "task"}])
    with pytest.raises(HTTPException, match="cannot continue"):
        await _run(s, b, [{"role": "user", "content": "retry"}])
    assert s._generated_tokens == 0 and b.caps == []


@pytest.mark.asyncio
async def test_generated_limit_wins_when_sequence_limit_is_also_exhausted():
    s, b = session(3), Backend()
    prompt = [{"role": "user", "content": "task"}]
    first = await _run(s, b, prompt, max_tokens=3)
    # Bind sequence capacity to the already consumed sequence, so both limits
    # are exhausted on the same continuation without guessing tokenizer length.
    chain = s.active_chains[0]
    s._trajectory_capacity = len(chain.buffer.prompt_ids) + len(chain.buffer.response_ids)
    outcome = await _run(s, b, prompt + [first.assistant_msg, {"role": "user", "content": "next"}])
    assert outcome.finish_reason == "length" and len(b.caps) == 1
    assert (await s.finalize())[0].extra_fields["materialization_reason"] == "max_generated_tokens"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "budget,stop_reason,expected",
    [(3, "length", "max_generated_tokens"), (3, "stop", None), (5, "length", None), (None, "length", None)],
)
async def test_exact_backend_cap_records_reason_without_extra_request(budget, stop_reason, expected):
    class TerminalBackend(Backend):
        async def generate(self, **kwargs):
            return TokenOutput(token_ids=[65] * 3, stop_reason=stop_reason)

    s = session(budget)
    outcome = await _run(s, TerminalBackend(), [{"role": "user", "content": "task"}], max_tokens=3)
    trajectories = await s.finalize()
    assert trajectories[0].extra_fields.get("materialization_reason") == expected
    assert outcome.completion_tokens == 3
    assert outcome.finish_reason == ("length" if stop_reason == "length" else "stop")


@pytest.mark.asyncio
async def test_exact_cap_reason_does_not_leak_to_other_chain():
    class LengthBackend(Backend):
        async def generate(self, **kwargs):
            return TokenOutput(token_ids=[65, 65], stop_reason="length")

    s = session(5)
    await _run(s, Backend(), [{"role": "system", "content": "one"}, {"role": "user", "content": "task"}], max_tokens=3)
    await _run(
        s, LengthBackend(), [{"role": "system", "content": "two"}, {"role": "user", "content": "other"}], max_tokens=2
    )
    trajectories = await s.finalize()
    assert len(trajectories) == 2
    assert trajectories[0].extra_fields.get("materialization_reason") is None
    assert trajectories[1].extra_fields["materialization_reason"] == "max_generated_tokens"
