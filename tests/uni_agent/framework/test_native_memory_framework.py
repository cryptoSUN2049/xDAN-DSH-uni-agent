import ast
import asyncio
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from examples.dsh.capabilities.memory_training_stage import OperatorSpec
from examples.dsh.capabilities.memory_verifier import sha
from tests.uni_agent.examples.test_memory_training_stage import execute_synthetic_stage
from tests.uni_agent.framework.test_gateway_stage_execution import Manager
from uni_agent.framework import framework as framework_module
from uni_agent.framework import memory_chain as memory_module
from uni_agent.framework.framework import _RunnerConfig
from uni_agent.framework.memory_chain import NativeMemoryFramework, audit_memory_chain_crosswalk


class Queue:
    def __init__(self):
        self.batches, self.status, self.cleared = [], [], []
        self.fail = False

    async def async_kv_batch_put(self, **kwargs):
        self.batches.append(kwargs)
        if self.fail:
            raise RuntimeError("partial queue failure")

    async def async_kv_put(self, **kwargs):
        self.status.append(kwargs)

    def kv_clear(self, **kwargs):
        self.cleared.append(kwargs)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"runtime")
    runtime.chmod(0o700)
    operator = OperatorSpec(
        tmp_path / "chains", Path(sys.executable), runtime, sha(b"runtime"), "checkpoint", "constraints"
    )
    operator.root.mkdir()
    config = _RunnerConfig("uni_agent.framework.task_runner.run_task", {}, "ray_task", 0)
    manager = Manager([])
    manager.by_session = {}

    async def finalize(session_id):
        manager.finalized.append(session_id)
        return manager.by_session[session_id]

    manager.finalize_session = finalize
    rollout = dict(
        n=4,
        calculate_log_probs=True,
        temperature=0.7,
        top_p=1.0,
        top_k=-1,
        val_kwargs=dict(n=1, temperature=0.0, top_p=1.0, top_k=-1),
    )
    af = dict(
        agent_runners={
            "task": {
                "runner_fqn": config.runner_fqn,
                "runner_kwargs": {},
                "dispatch_mode": "ray_task",
                "trajectory_selection": "all",
            }
        },
        log_dir=str(tmp_path / "logs"),
        fail_on_rollout_error=True,
        require_finished_episode=True,
        require_verifier_reward=True,
        require_trajectory_dump=True,
        memory_run_id="memory-run",
        memory_operator={
            key: str(value) if isinstance(value, Path) else value for key, value in vars(operator).items()
        },
    )
    rollout["custom"] = {"agent_framework": af}
    full_config = OmegaConf.create(
        dict(
            actor_rollout_ref={"rollout": rollout},
            trainer={"use_v1": True, "v1": {"trainer_mode": "sync"}},
            algorithm={"adv_estimator": "grpo", "use_kl_in_reward": False},
        )
    )
    framework = NativeMemoryFramework.from_config(config=full_config, gateway_manager=manager)
    assert framework._memory_operator == operator
    framework.test_full_config = full_config
    specs, observations = {}, []
    for name in ("prepare_writer_stage", "freeze_and_prepare_reader"):
        original = getattr(memory_module, name)

        def record(*args, _original=original, **kwargs):
            spec = _original(*args, **kwargs)
            specs[str(spec.task_config_path)] = spec
            return spec

        monkeypatch.setattr(memory_module, name, record)

    async def remote(**kwargs):
        spec = specs[kwargs["runner_kwargs"]["task_config_path"]]
        assert kwargs["raw_prompt"] == spec.raw_prompt
        assert kwargs["tools_kwargs"]["task"]["metadata"] == spec.metadata
        assert kwargs["session"].session_id == spec.gateway_session_id
        if getattr(framework, "test_reader_error", False) and spec.role == "reader":
            raise RuntimeError("reader runner failure")
        result = await asyncio.to_thread(
            execute_synthetic_stage, spec, bad_memory=getattr(framework, "test_bad_writer", False)
        )
        # Fixed sync VERL publishes step k-1 before scheduling training update k.
        policy_version = spec.context.global_steps - (spec.context.partition == "train")
        policy_version += getattr(framework, "test_version_offset", 0)
        for trajectory in result.trajectories:
            trajectory.extra_fields.update(min_global_steps=policy_version, max_global_steps=policy_version)
        if getattr(framework, "test_bad_version", False) and spec.role == "reader":
            result.trajectories[0].extra_fields["version_evidence_complete"] = False
        manager.by_session[spec.gateway_session_id] = result.trajectories
        observations.append(result)
        return result.task_result

    monkeypatch.setattr(framework_module, "_run_agent_runner_ray_task", SimpleNamespace(remote=remote))
    queue = Queue()
    monkeypatch.setattr(framework_module, "tq", queue)
    return framework, manager, queue, observations


async def run(framework, partition="train"):
    return await framework._run_prompt_rollouts(
        sample_fields={"uid": "group-1", "raw_prompt": [], "agent_name": "task"},
        sample_index=0,
        global_steps=7,
        partition_id=partition,
        num_sessions=4 if partition == "train" else 1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("partition,count", [("train", 4), ("val", 1)])
async def test_resident_real_stage_contract_to_original_tq_batch(wired, partition, count):
    framework, manager, queue, observations = wired
    result = await run(framework, partition)
    assert result["num_success_sessions"] == count, result
    assert len(manager.created) == len(manager.finalized) == len(observations) == count * 2
    assert manager.aborted == []
    assert len(queue.batches) == 1
    keys = queue.batches[0]["keys"]
    assert keys == [f"group-1_{j}_{i}" for j in range(count) for i in range(2)]
    assert len(keys) == len(set(keys))
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    audit = audit_memory_chain_crosswalk(crosswalk)
    record = json.loads(crosswalk.read_text())
    assert record["global_steps"] == 7
    assert record["expected_policy_version"] == (6 if partition == "train" else 7)
    assert audit["keys"] == keys and audit["terminal_rewards"] == [1.0] * count
    assert framework._pending == {}
    assert all(x.trajectories[0].reward_score == 1 for x in observations)
    assert queue.status[-1]["tag"] == {"status": "finished"}


@pytest.mark.asyncio
async def test_missing_real_generation_version_rejects_entire_group(wired):
    framework, manager, queue, _ = wired
    framework.test_bad_version = True
    result = await run(framework)
    assert result["num_failed_uids"] == 1
    assert queue.batches == [] and framework._pending == {}
    assert queue.status[-1]["tag"] == {"status": "failure"}


@pytest.mark.asyncio
async def test_partial_tq_failure_uses_parent_cleanup_and_clears_pending(wired):
    framework, manager, queue, _ = wired
    queue.fail = True
    result = await run(framework)
    assert result["num_failed_uids"] == 1
    assert queue.cleared[0]["keys"] == ["group-1"] + [f"group-1_{j}_{i}" for j in range(4) for i in range(2)]
    assert framework._pending == {}


@pytest.mark.asyncio
async def test_crosswalk_rejects_modified_stage_npz(wired):
    framework, _, _, _ = wired
    await run(framework, "val")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(crosswalk.read_text())
    Path(record["items"][0]["stage_npz_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash|changed"):
        audit_memory_chain_crosswalk(crosswalk)


@pytest.mark.asyncio
async def test_terminal_reader_zero_does_not_rewrite_writer_reward(wired, monkeypatch):
    from tests.uni_agent.tasks.test_dsh_task import _HarnessTask

    original = _HarnessTask.build_agent

    def altered_reader(self):
        agent = original(self)
        original_run = agent.run

        async def run_agent(**kwargs):
            result = await original_run(**kwargs)
            if self.config.metadata["task_id"].endswith("/reader"):
                result.output["response"] = '{"status":"answer","facts":{},"source_version":"wrong"}'
            return result

        agent.run = run_agent
        return agent

    monkeypatch.setattr(_HarnessTask, "build_agent", altered_reader)
    framework, _, queue, observations = wired
    result = await run(framework, "val")
    assert result["num_success_sessions"] == 1, result
    assert [x.task_result.reward for x in observations] == [1.0, 0.0]
    assert [x.trajectories[0].reward_score for x in observations] == [1.0, 0.0]
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    assert audit_memory_chain_crosswalk(crosswalk)["terminal_rewards"] == [0.0]
    assert len(queue.batches) == 1
    fields = queue.batches[0]["fields"]
    assert [fields["rm_scores"][i].tolist() for i in range(2)] == [[1.0], [0.0]]
    assert [fields["responses"][i].tolist() for i in range(2)] == [[2], [2]]
    assert [fields["response_mask"][i].tolist() for i in range(2)] == [[1], [1]]
    assert [fields["loss_mask"][i].tolist() for i in range(2)] == [[1], [1]]
    assert fields["rollout_log_probs"][0].tolist() == pytest.approx([-0.1])


@pytest.mark.parametrize(
    "name,value",
    [
        ("trainer.use_v1", False),
        ("trainer.v1.trainer_mode", "colocate_async"),
        ("algorithm.adv_estimator", "gae"),
        ("algorithm.use_kl_in_reward", True),
    ],
)
def test_config_rejects_incompatible_training_before_framework_construction(name, value):
    config = OmegaConf.create(
        {
            "trainer": {"use_v1": True, "v1": {"trainer_mode": "sync"}},
            "algorithm": {"adv_estimator": "grpo", "use_kl_in_reward": False},
        }
    )
    OmegaConf.update(config, name, value)
    with pytest.raises(ValueError, match="Memory requires"):
        NativeMemoryFramework.from_config(config=config, gateway_manager=Manager([]))


@pytest.mark.asyncio
async def test_duplicate_active_scope_rejected_without_new_stage(wired):
    framework, manager, _, _ = wired
    key = ("train", "group-1", 7)
    existing = {}
    framework._pending[key] = existing
    with pytest.raises(ValueError, match="already active"):
        await run(framework)
    assert framework._pending[key] is existing
    assert manager.created == []
    framework._pending.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["duplicate-chain", "orphan-item", "wrong-scope", "reversed-roles"])
async def test_crosswalk_rejects_incomplete_or_ambiguous_chain_partition(wired, mutation):
    from examples.dsh.capabilities.memory_verifier import canonical

    framework, _, _, _ = wired
    await run(framework)
    path = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(path.read_text())
    if mutation == "duplicate-chain":
        record["chains"] = [record["chains"][0]] * 4
    elif mutation == "orphan-item":
        record["items"].append({**record["items"][0], "chain_id": "orphan", "tq_key": "group-1_9_0"})
    else:
        chain = record["chains"][0]
        receipt_path = Path(chain["receipt_path"])
        receipt = json.loads(receipt_path.read_text())
        if mutation == "wrong-scope":
            receipt["uid"] = "wrong-group"
        else:
            for item in record["items"]:
                if item["chain_id"] == receipt["chain_id"]:
                    item["role"] = "B"
            receipt["items"] = [x for x in record["items"] if x["chain_id"] == receipt["chain_id"]]
        receipt["receipt_id"] = sha(canonical({k: v for k, v in receipt.items() if k != "receipt_id"}))
        receipt_path.write_bytes(canonical(receipt))
        chain["receipt_sha256"] = sha(receipt_path.read_bytes())
    path.write_bytes(canonical(record))
    with pytest.raises(ValueError):
        audit_memory_chain_crosswalk(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["test_bad_writer", "test_reader_error"])
async def test_stage_failure_leaves_no_partial_group(wired, flag):
    framework, manager, queue, _ = wired
    setattr(framework, flag, True)
    result = await run(framework)
    assert result["num_failed_uids"] == 1
    assert framework._pending == {} and queue.batches == []
    if flag == "test_bad_writer":
        assert len(manager.created) == 4
        assert not list(framework._memory_operator.root.glob("*/frozen"))
    else:
        assert len(manager.created) == 8 and len(manager.aborted) == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("fail_on_rollout_error", False),
        ("require_finished_episode", False),
        ("require_verifier_reward", False),
        ("require_trajectory_dump", False),
        ("trajectory_postprocessor_fqn", "uni_agent.tasks.dsh.trajectory_audit.validate_trajectories"),
        ("agent_runners.task.dispatch_mode", "inline_async"),
        ("agent_runners.task.trajectory_selection", "longest"),
        ("agent_runners.task.runner_kwargs.dsh_episode_source_root", "/unapproved-source"),
    ],
)
def test_recipe_rejects_non_strict_or_alternate_stage_execution(wired, field, value):
    framework, manager, _, _ = wired
    config = OmegaConf.create(OmegaConf.to_container(framework.test_full_config))
    OmegaConf.update(config, "actor_rollout_ref.rollout.custom.agent_framework." + field, value)
    with pytest.raises(ValueError):
        NativeMemoryFramework.from_config(config=config, gateway_manager=manager)
    assert manager.created == []


@pytest.mark.asyncio
@pytest.mark.parametrize("partition,offset", [("train", 1), ("train", -1), ("val", -1), ("val", 1)])
async def test_wrong_actual_sync_policy_version_is_not_rewritten(wired, partition, offset):
    framework, _, queue, observations = wired
    framework.test_version_offset = offset
    result = await run(framework, partition)
    assert result["num_failed_uids"] == 1 and queue.batches == []
    expected_actual = (6 if partition == "train" else 7) + offset
    assert all(t.extra_fields["max_global_steps"] == expected_actual for x in observations for t in x.trajectories)


def test_pinned_sync_hooks_and_fit_order_bind_policy_version():
    root = Path(__file__).resolve().parents[3] / "verl/verl/trainer/ppo/v1"
    sync = ast.parse((root / "trainer_sync.py").read_text())
    cls = next(n for n in sync.body if isinstance(n, ast.ClassDef) and n.name == "PPOTrainerSync")
    hooks = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("on_init_end", "on_step_end")]
    scope = {"marked_timer": lambda *a, **k: nullcontext()}
    exec(compile(ast.Module(body=hooks, type_ignores=[]), "fixed_sync_hooks", "exec"), scope)
    published = []
    trainer = SimpleNamespace(
        global_steps=0, timing_raw={}, checkpoint_manager=SimpleNamespace(update_weights=published.append)
    )
    scope["on_init_end"](trainer)
    assert published[-1] == memory_module.expected_sync_policy_version(0, "val")
    trainer.global_steps += 1
    assert published[-1] == memory_module.expected_sync_policy_version(1, "train")
    scope["on_step_end"](trainer)
    assert published[-1] == memory_module.expected_sync_policy_version(1, "val")
    base = ast.parse((root / "trainer_base.py").read_text())
    fit = next(n for n in ast.walk(base) if isinstance(n, ast.FunctionDef) and n.name == "fit")
    increment = min(
        n.lineno for n in ast.walk(fit) if isinstance(n, ast.AugAssign) and ast.unparse(n.target) == "self.global_steps"
    )
    calls = [n for n in ast.walk(fit) if isinstance(n, ast.Call)]
    line = lambda name: min(n.lineno for n in calls if ast.unparse(n.func) == "self." + name)
    post_validation = max(n.lineno for n in calls if ast.unparse(n.func) == "self._validate")
    assert increment < line("step") < line("on_step_end") < post_validation


@pytest.mark.parametrize("step,partition", [(0, "train"), (-1, "val"), (True, "train"), (1, "other")])
def test_invalid_sync_schedule_rejected(step, partition):
    with pytest.raises(ValueError):
        memory_module.expected_sync_policy_version(step, partition)
