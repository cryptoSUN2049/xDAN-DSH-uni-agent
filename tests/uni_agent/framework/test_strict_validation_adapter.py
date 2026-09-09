import ast
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from omegaconf import OmegaConf

from uni_agent.framework import entry
from uni_agent.framework.entry import AgentFrameworkRolloutAdapter, StrictSyncValidationRolloutAdapter
from verl.utils import tensordict_utils as tu


def prompts(validate):
    batch = tu.get_tensordict({"raw_prompt": np.array([[]], dtype=object), "uid": np.array(["u"])})
    tu.assign_non_tensor_data(batch, "validate", validate)
    return batch


@pytest.fixture
def transport(monkeypatch):
    ref = object()
    calls = []
    worker = SimpleNamespace(generate_sequences=SimpleNamespace(remote=lambda batch: calls.append("submit") or ref))
    monkeypatch.setattr(entry, "build_gateway_manager", lambda **kw: object())
    monkeypatch.setattr(entry, "AgentFrameworkWorker", SimpleNamespace(remote=lambda **kw: worker))
    monkeypatch.setattr(entry.ray, "get", lambda obj, **kw: calls.append(("get", obj, kw)))
    monkeypatch.setattr(entry.ray, "cancel", lambda obj, **kw: calls.append(("cancel", obj, kw)))
    config = OmegaConf.create(
        {
            "trainer": {"v1": {"trainer_mode": "sync"}},
            "actor_rollout_ref": {
                "rollout": {
                    "custom": {
                        "agent_framework": {"fail_on_rollout_error": True, "strict_validation_timeout_seconds": 30}
                    }
                }
            },
        }
    )
    return config, calls, ref


def test_val_waits_same_ref_and_train_remains_fireforget(transport):
    config, calls, ref = transport
    adapter = StrictSyncValidationRolloutAdapter.create(config=config, llm_client=object())
    assert isinstance(adapter, StrictSyncValidationRolloutAdapter)
    adapter.generate_sequences(prompts(True))
    assert calls == ["submit", ("get", ref, {"timeout": 30})]
    calls.clear()
    adapter.generate_sequences(prompts(False))
    assert calls == ["submit"]


def test_original_adapter_stays_fireforget_for_val(transport):
    config, calls, _ = transport
    adapter = AgentFrameworkRolloutAdapter.create(config=config, llm_client=object())
    adapter.generate_sequences(prompts(True))
    assert calls == ["submit"]


def test_fixed_verl_validation_does_not_sample_after_actor_failure(transport, monkeypatch):
    config, calls, _ = transport
    adapter = StrictSyncValidationRolloutAdapter.create(config=config, llm_client=object())

    def fail(*args, **kwargs):
        raise RuntimeError("ValueError:Writer failed quality gate")

    monkeypatch.setattr(entry.ray, "get", fail)
    file = Path("verl/verl/trainer/ppo/v1/trainer_base.py")
    tree = ast.parse(file.read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_validate")
    scope = dict(
        defaultdict=defaultdict,
        np=np,
        tu=tu,
        uuid=SimpleNamespace(uuid4=lambda: "u"),
        tq=SimpleNamespace(kv_batch_put=lambda **kw: None),
    )
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(file), "exec"), scope)
    trainer = SimpleNamespace(
        val_dataloader=[{"raw_prompt": np.array([[]], dtype=object)}],
        global_steps=0,
        agent_loop_manager=adapter,
        replay_buffer=SimpleNamespace(sample=lambda **kw: calls.append("sample")),
    )
    with pytest.raises(RuntimeError, match="Writer failed quality gate"):
        scope["_validate"](trainer)
    assert calls == ["submit"]


def test_timeout_only_cancels_owned_ref_and_does_not_claim_cleanup(transport, monkeypatch):
    config, calls, ref = transport
    adapter = StrictSyncValidationRolloutAdapter.create(config=config, llm_client=object())

    def timeout(*args, **kwargs):
        raise entry.ray.exceptions.GetTimeoutError("timed out")

    monkeypatch.setattr(entry.ray, "get", timeout)
    with pytest.raises(TimeoutError, match="cleanup unconfirmed"):
        adapter.generate_sequences(prompts(True))
    assert calls == ["submit", ("cancel", ref, {"force": False})]


@pytest.mark.parametrize(
    "mode,strict,timeout",
    [("fully_async", True, 30), ("sync", False, 30), ("sync", True, 0), ("sync", True, float("inf"))],
)
def test_invalid_opt_in_configuration_rejected_before_worker(transport, mode, strict, timeout):
    config, calls, _ = transport
    config.trainer.v1.trainer_mode = mode
    af = config.actor_rollout_ref.rollout.custom.agent_framework
    af.fail_on_rollout_error = strict
    af.strict_validation_timeout_seconds = timeout
    with pytest.raises(ValueError):
        StrictSyncValidationRolloutAdapter.create(config=config, llm_client=object())
    assert calls == []


def test_timeout_preserved_when_cancel_request_fails(transport, monkeypatch):
    config, calls, _ = transport
    adapter = StrictSyncValidationRolloutAdapter.create(config=config, llm_client=object())

    def timeout(*args, **kwargs):
        raise entry.ray.exceptions.GetTimeoutError("timeout")

    def cancel_fails(*args, **kwargs):
        raise RuntimeError("transport unavailable")

    monkeypatch.setattr(entry.ray, "get", timeout)
    monkeypatch.setattr(entry.ray, "cancel", cancel_fails)
    with pytest.raises(TimeoutError, match="cancellation_requested=False; cleanup unconfirmed") as error:
        adapter.generate_sequences(prompts(True))
    assert isinstance(error.value.__cause__, entry.ray.exceptions.GetTimeoutError)
    assert calls == ["submit"]


def test_driver_cancellation_is_not_recast_as_success(transport, monkeypatch):
    import asyncio

    config, calls, _ = transport
    adapter = StrictSyncValidationRolloutAdapter.create(config=config, llm_client=object())

    def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(entry.ray, "get", cancelled)
    with pytest.raises(asyncio.CancelledError):
        adapter.generate_sequences(prompts(True))
    assert calls == ["submit"]


def test_opt_in_requires_initialized_worker():
    with pytest.raises(RuntimeError, match="initialized"):
        StrictSyncValidationRolloutAdapter().generate_sequences(prompts(True))
