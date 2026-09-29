import asyncio
import hashlib
import json
import struct
from copy import deepcopy

import pytest
from fastapi import HTTPException

from tests.uni_agent.gateway.test_session_generation_budget import Backend, session
from tests.uni_agent.gateway.test_session_multiple_chains_on_cpu import _run
from verl.workers.rollout.replica import TokenOutput

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class LengthBackend(Backend):
    async def generate(self, *, sampling_params, **kwargs):
        count = min(3, sampling_params["max_tokens"])
        return TokenOutput(token_ids=[65] * count, log_probs=[-0.1] * count, stop_reason="length")


def check_proof(trajectories):
    proof = trajectories[0].extra_fields["gateway_budget_proof"]
    assert proof["schema"] == "uni-agent.gateway-budget-proof.v1"
    assert proof["session_id"] == "budget"
    assert proof["phase"] == "FINALIZED"
    assert proof["inflight_requests"] == 0
    assert proof["accounting_failed"] is False
    assert proof["limits_sha256"] == digest(proof["limits"])
    assert proof["proof_sha256"] == digest({k: v for k, v in proof.items() if k != "proof_sha256"})
    assert len(proof["trajectories"]) == len(trajectories)
    for trajectory, entry in zip(trajectories, proof["trajectories"], strict=True):
        assert trajectory.extra_fields["gateway_budget_proof"] == proof
        assert entry["chain_id"] == trajectory.chain_id
        tokens = {key: getattr(trajectory, key) for key in ("prompt_ids", "response_ids", "response_mask")}
        tokens["response_logprobs"] = (
            [struct.unpack("<f", struct.pack("<f", value))[0] for value in trajectory.response_logprobs]
            if trajectory.response_logprobs is not None
            else None
        )
        assert entry["token_sha256"] == digest(tokens)
        assert entry["model_token_count"] == sum(trajectory.response_mask)
    return proof


@pytest.mark.asyncio
async def test_generated_budget_proof_exact_terminal():
    s = session(3)
    await _run(s, LengthBackend(), [{"role": "user", "content": "task"}], max_tokens=99)
    proof = check_proof(await s.finalize())
    assert proof["generated_tokens"] == 3
    assert proof["exhaustion_reason"] == "max_generated_tokens"
    event = proof["exhaustion_events"][0]
    assert event["effective_max_tokens"] == 3 and event["output_tokens"] == 3
    assert event["denied"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,backend", [(9, LengthBackend), (3, Backend)])
async def test_single_call_length_or_natural_stop_is_not_budget_terminal(budget, backend):
    s = session(budget)
    await _run(s, backend(), [{"role": "user", "content": "task"}], max_tokens=3)
    proof = check_proof(await s.finalize())
    assert proof["exhaustion_reason"] is None
    assert proof["exhaustion_events"] == []


@pytest.mark.asyncio
async def test_exact_context_terminal_proof():
    s = session(100)
    messages = [{"role": "user", "content": "task"}]
    s._trajectory_capacity = len(s._codec.build_initial_tokens(messages)) + 2
    await _run(s, LengthBackend(), messages, max_tokens=99)
    proof = check_proof(await s.finalize())
    event = proof["exhaustion_events"][0]
    assert proof["exhaustion_reason"] == "max_trajectory_length"
    assert event["input_tokens"] + event["output_tokens"] == proof["limits"]["trajectory_capacity"]


@pytest.mark.asyncio
async def test_denied_context_proof_records_attempted_input_not_retained_prefix():
    s = session(100)
    messages = [{"role": "user", "content": "task"}]
    s._trajectory_capacity = len(s._codec.build_initial_tokens(messages)) + 10
    first = await _run(s, Backend(), messages, max_tokens=3)
    await _run(s, Backend(), messages + [first.assistant_msg, {"role": "user", "content": "feedback " * 100}])
    trajectories = await s.finalize()
    proof = check_proof(trajectories)
    event = proof["exhaustion_events"][0]
    assert event["denied"] is True and event["output_tokens"] == 0
    assert event["input_tokens"] > proof["limits"]["trajectory_capacity"]
    assert len(trajectories[0].prompt_ids) + len(trajectories[0].response_ids) < event["input_tokens"]


@pytest.mark.asyncio
async def test_denied_new_chain_and_prior_exhaustion_are_all_bound():
    s = session(5)
    s._trajectory_capacity = 100
    await _run(s, Backend(), [{"role": "user", "content": "task"}], max_tokens=3)
    await _run(s, Backend(), [{"role": "system", "content": "huge " * 100}, {"role": "user", "content": "fork"}])
    await _run(s, LengthBackend(), [{"role": "system", "content": "new"}, {"role": "user", "content": "other"}])
    trajectories = await s.finalize()
    proof = check_proof(trajectories)
    assert [e["reason"] for e in proof["exhaustion_events"]] == ["max_trajectory_length", "max_generated_tokens"]
    assert proof["exhaustion_events"][0]["chain_id"] is None
    trajectories[0].extra_fields["gateway_budget_proof"]["generated_tokens"] = 999
    assert trajectories[1].extra_fields["gateway_budget_proof"]["generated_tokens"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["error", "overflow"])
async def test_failed_accounting_cannot_finalize_proof(fault):
    s = session(5)
    with pytest.raises(HTTPException):
        await _run(s, Backend(fault), [{"role": "user", "content": "task"}], max_tokens=5)
    with pytest.raises(RuntimeError, match="budget accounting"):
        await s.finalize()


@pytest.mark.asyncio
async def test_inflight_and_cancelled_generation_cannot_finalize_proof():
    started = asyncio.Event()

    class Hanging(Backend):
        async def generate(self, **kwargs):
            started.set()
            await asyncio.Event().wait()

    s = session(5)
    task = asyncio.create_task(_run(s, Hanging(), [{"role": "user", "content": "task"}]))
    await started.wait()
    with pytest.raises(RuntimeError, match="in-flight"):
        await s.finalize()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(RuntimeError, match="budget accounting"):
        await s.finalize()


@pytest.mark.asyncio
async def test_proof_ignores_metadata_and_counts_rollback_work():
    s = session(5)
    s._metadata["gateway_budget_proof"] = {"generated_tokens": 0}
    messages = [{"role": "user", "content": "task"}]
    await _run(s, Backend(), messages, max_tokens=3)
    await _run(s, LengthBackend(), messages + [{"role": "user", "content": "retry format"}], max_tokens=9)
    proof = check_proof(await s.finalize())
    assert proof["generated_tokens"] == 5
    assert proof["limits"]["max_generated_tokens"] == 5
    assert s.snapshot_state()["rollback_dropped_trainable_tokens_total"] == 3
    assert proof["trajectories"][0]["model_token_count"] == 2


@pytest.mark.asyncio
async def test_unbudgeted_session_retains_old_output_contract():
    s = session(None)
    await _run(s, LengthBackend(), [{"role": "user", "content": "task"}], max_tokens=3)
    assert all("gateway_budget_proof" not in t.extra_fields for t in await s.finalize())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "bool-count",
        "bool-limit",
        "bool-request",
        "bool-index",
        "future-index",
        "event",
        "chain",
        "session",
        "token",
        "missing",
    ],
)
async def test_validator_rejects_forged_proof_even_with_rehashed_body(change):
    from uni_agent.gateway.session.types import validate_gateway_budget_proof

    s = session(3)
    await _run(s, LengthBackend(), [{"role": "user", "content": "task"}], max_tokens=3)
    trajectories = await s.finalize()
    proof = deepcopy(check_proof(trajectories))
    if change == "bool-count":
        proof["generated_tokens"] = True
    elif change == "bool-request":
        proof["request_count"] = True
    elif change == "bool-index":
        proof["exhaustion_events"][0]["request_index"] = True
    elif change == "future-index":
        proof["exhaustion_events"][0]["request_index"] = 2
    elif change == "bool-limit":
        proof["limits"]["max_generated_tokens"] = True
        proof["limits_sha256"] = digest(proof["limits"])
    elif change == "event":
        proof["exhaustion_events"][0]["generated_tokens"] = 2
    elif change == "chain":
        proof["trajectories"][0]["chain_id"] = 2
    elif change == "session":
        proof["session_id"] = "other"
    elif change == "token":
        trajectories[0].response_ids[0] += 1
    elif change == "missing":
        proof["trajectories"] = []
    proof["proof_sha256"] = digest({k: v for k, v in proof.items() if k != "proof_sha256"})
    with pytest.raises(ValueError):
        validate_gateway_budget_proof(proof, trajectories, session_id="budget")


@pytest.mark.asyncio
async def test_validator_accepts_float32_roundtrip_and_rejects_policy_mismatch():
    from uni_agent.gateway.session.types import validate_gateway_budget_proof

    s = session(3)
    s._sampling_params["logprobs"] = True
    await _run(s, LengthBackend(), [{"role": "user", "content": "task"}], max_tokens=3)
    trajectories = await s.finalize()
    proof = check_proof(trajectories)
    trajectories[0].response_logprobs = [
        struct.unpack("<f", struct.pack("<f", x))[0] for x in trajectories[0].response_logprobs
    ]
    assert validate_gateway_budget_proof(proof, trajectories, session_id="budget") == proof
    with pytest.raises(ValueError):
        validate_gateway_budget_proof(
            proof,
            trajectories,
            session_id="budget",
            expected_limits={"max_generated_tokens": 4, "trajectory_capacity": None},
        )


@pytest.mark.asyncio
async def test_validator_requires_all_chains_online_but_checks_selected_chain_offline():
    from uni_agent.gateway.session.types import validate_gateway_budget_proof

    s = session(5)
    await _run(s, Backend(), [{"role": "system", "content": "one"}, {"role": "user", "content": "task"}], max_tokens=3)
    await _run(s, LengthBackend(), [{"role": "system", "content": "two"}, {"role": "user", "content": "task"}])
    trajectories = await s.finalize()
    proof = check_proof(trajectories)
    with pytest.raises(ValueError, match="missing finalized chains"):
        validate_gateway_budget_proof(proof, trajectories[:1], session_id="budget")
    assert (
        validate_gateway_budget_proof(proof, trajectories[:1], session_id="budget", require_all_chains=False) == proof
    )
    trajectories[0].response_ids[0] += 1
    with pytest.raises(ValueError, match="token evidence differs"):
        validate_gateway_budget_proof(proof, trajectories[:1], session_id="budget", require_all_chains=False)


@pytest.mark.asyncio
async def test_aborted_session_never_emits_budget_proof():
    s = session(3)
    await _run(s, LengthBackend(), [{"role": "user", "content": "task"}], max_tokens=3)
    await s.abort()
    with pytest.raises(RuntimeError, match="aborted"):
        await s.finalize()


@pytest.mark.asyncio
async def test_prior_branch_exhaustion_cannot_prove_later_single_call_length():
    from uni_agent.gateway.session.types import validate_gateway_budget_proof

    s = session(100)
    s._trajectory_capacity = 100
    await _run(s, Backend(), [{"role": "user", "content": "task"}], max_tokens=3)
    await _run(s, Backend(), [{"role": "system", "content": "huge " * 100}, {"role": "user", "content": "fork"}])
    await _run(
        s, LengthBackend(), [{"role": "system", "content": "new"}, {"role": "user", "content": "other"}], max_tokens=3
    )
    trajectories = await s.finalize()
    proof = check_proof(trajectories)
    assert proof["request_count"] == 3
    assert proof["exhaustion_events"][0]["request_index"] == 2
    assert proof["exhaustion_reason"] is None
    assert validate_gateway_budget_proof(proof, trajectories, session_id="budget") == proof
    forged = deepcopy(proof)
    forged["exhaustion_reason"] = "max_trajectory_length"
    forged["proof_sha256"] = digest({k: v for k, v in forged.items() if k != "proof_sha256"})
    with pytest.raises(ValueError, match="terminal reason"):
        validate_gateway_budget_proof(forged, trajectories, session_id="budget")
