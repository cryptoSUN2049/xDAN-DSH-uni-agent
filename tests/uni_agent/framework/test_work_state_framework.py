import json

import pytest

from tests.uni_agent.framework.test_native_memory_framework import run
from tests.uni_agent.framework.test_native_memory_framework import wired as native_wired
from uni_agent.framework.memory_chain import NativeMemoryFramework, audit_memory_chain_crosswalk

wired = native_wired


@pytest.mark.asyncio
async def test_stage_hooks_keep_original_loop_and_sample_fields(wired, monkeypatch):
    framework, _, queue, _ = wired
    calls = []
    for name in ("_prepare_writer", "_freeze_reader", "_validate_stage"):
        original = getattr(framework, name)

        def hook(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            if _name == "_prepare_writer":
                assert kwargs["sample_fields"]["uid"] == "group-1"
            return _original(*args, **kwargs)

        monkeypatch.setattr(framework, name, hook)
    result = await run(framework, "val")
    assert result["num_success_sessions"] == 1 and len(queue.batches) == 1
    assert calls.count("_prepare_writer") == calls.count("_freeze_reader") == 1
    assert calls.count("_validate_stage") >= 4
    assert framework.contract_id == "legacy-memory-v1"


@pytest.mark.asyncio
async def test_crosswalk_explicit_contract_and_legacy_readback(wired):
    framework, *_ = wired
    await run(framework, "val")
    path = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(path.read_text())
    assert record["contract_id"] == NativeMemoryFramework.contract_id == "legacy-memory-v1"
    assert audit_memory_chain_crosswalk(path)["consumption_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("contract", ["unknown", "work-state-v1"])
async def test_record_cannot_choose_wider_contract_than_chain(wired, contract):
    framework, *_ = wired
    await run(framework, "val")
    path = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(path.read_text())
    record["contract_id"] = contract
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="contract|credit"):
        audit_memory_chain_crosswalk(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("partition", ["train", "val"])
@pytest.mark.parametrize("budget", [None, 8192])
async def test_real_workstate_zero_quality_chain_reuses_original_tq(wired, tmp_path, monkeypatch, partition, budget):
    import asyncio
    from types import SimpleNamespace

    from examples.dsh.capabilities.memory_verifier import canonical, sha
    from examples.dsh.capabilities.work_state import stage
    from examples.dsh.capabilities.work_state.tasks import make_task
    from tests.uni_agent.examples.test_work_state_stage import execute_synthetic_stage
    from uni_agent.framework import framework as framework_module
    from uni_agent.framework.work_state import NativeWorkStateFramework

    original_framework, manager, queue, _ = wired
    task = make_task("WS01", 0, 8)
    manifest = tmp_path / "workstate-dataset.json"
    manifest.write_bytes(
        canonical(
            {
                "schema": "dsh.work-state-dataset.v1",
                "tasks": {
                    task["task_id"]: {
                        "family": "WS01",
                        "variant": 0,
                        "seed": 8,
                        "split": "train" if partition == "train" else "validation",
                    }
                },
            }
        )
    )
    op = original_framework._memory_operator
    operator = stage.WorkStateOperator(
        **{**vars(op), "family": "work-state-v1"},
        task_manifest=manifest,
        task_manifest_sha256=sha(manifest.read_bytes()),
        max_generated_tokens=budget,
    )
    config = original_framework.test_full_config
    config.actor_rollout_ref.rollout.custom.agent_framework.memory_operator = {
        k: str(v) if hasattr(v, "__fspath__") else v for k, v in vars(operator).items()
    }
    framework = NativeWorkStateFramework.from_config(config=config, gateway_manager=manager)
    specs, executions = {}, []
    for name in ("prepare_writer_stage", "freeze_and_prepare_reader"):
        original = getattr(stage, name)

        def capture(*args, _original=original, **kwargs):
            spec = _original(*args, **kwargs)
            specs[str(spec.task_config_path)] = spec
            return spec

        monkeypatch.setattr(stage, name, capture)

    async def remote(**kwargs):
        spec = specs[kwargs["runner_kwargs"]["task_config_path"]]
        result = await asyncio.to_thread(execute_synthetic_stage, spec, bad_memory=True)
        manager.by_session[spec.gateway_session_id] = result.trajectories
        executions.append(result)
        return result.task_result

    monkeypatch.setattr(framework_module, "_run_agent_runner_ray_task", SimpleNamespace(remote=remote))
    fields = {
        "uid": "group-workstate",
        "raw_prompt": [],
        "agent_name": "task",
        "tools_kwargs": {"task": {"metadata": {"work_state_task_id": task["task_id"]}}},
    }
    count = 4 if partition == "train" else 1
    result = await framework._run_prompt_rollouts(
        sample_fields=fields, sample_index=0, global_steps=7, partition_id=partition, num_sessions=count
    )
    assert result["num_success_sessions"] == count, result
    assert len(executions) == 2 * count and all(e.task_result.reward == 0 for e in executions)
    assert len(queue.batches) == 1 and len(queue.batches[0]["keys"]) == 2 * count
    crosswalk = next(operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(crosswalk.read_text())
    assert record["contract_id"] == "work-state-v1"
    assert audit_memory_chain_crosswalk(crosswalk)["terminal_rewards"] == [0.0] * count
    assert [i["role"] for i in record["items"]] == ["A", "B"] * count
    assert len(manager.created) == len(manager.finalized) == 2 * count
    assert all(kwargs.get("max_generated_tokens") == budget for _, kwargs in manager.created)
    assert not manager.aborted
    # Original strict memory admission remains immutable, independent of a sample claim.
    assert NativeMemoryFramework.contract_id == "legacy-memory-v1"


@pytest.mark.asyncio
async def test_pre_contract_legacy_crosswalk_still_reads(wired):
    from examples.dsh.capabilities.memory_verifier import canonical, sha

    framework, *_ = wired
    await run(framework, "val")
    path = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(path.read_text())
    del record["contract_id"]
    for reference in record["chains"]:
        from pathlib import Path

        receipt_path = Path(reference["receipt_path"])
        receipt = json.loads(receipt_path.read_text())
        del receipt["contract_id"]
        receipt["receipt_id"] = sha(canonical({k: v for k, v in receipt.items() if k != "receipt_id"}))
        receipt_path.write_bytes(canonical(receipt))
        reference["receipt_sha256"] = sha(receipt_path.read_bytes())
    path.write_bytes(canonical(record))
    assert audit_memory_chain_crosswalk(path)["keys"] == ["group-1_0_0", "group-1_0_1"]
