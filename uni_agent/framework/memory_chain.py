"""Resident DSH memory stages; original strict grouping and TQ writer stay authoritative."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

import numpy as np
from omegaconf import OmegaConf

from examples.dsh.capabilities.memory_credit import ChainOutcome, FrozenBinding, StageOutcome, validate_credit_group
from examples.dsh.capabilities.memory_training_stage import (
    GroupContext,
    OperatorSpec,
    StageSpec,
    freeze_and_prepare_reader,
    prepare_writer_stage,
    validate_stage_execution,
)
from examples.dsh.capabilities.memory_verifier import canonical, read_regular, sha
from uni_agent.framework.framework import GatewayAgentFramework, GatewayStageExecution
from uni_agent.framework.trajectory_identity import trajectory_tq_key


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def expected_sync_policy_version(global_steps, partition):
    """Pinned VERL sync: training update k samples k-1; validation samples k."""
    _require(partition in ("train", "val"), "Invalid memory partition")
    _require(
        type(global_steps) is int and global_steps >= (1 if partition == "train" else 0),
        "Invalid sync scheduling step",
    )
    return global_steps - (1 if partition == "train" else 0)


def _write_new(path, value):
    with path.open("xb") as output:
        output.write(canonical(value))


def _token_digest(trajectory):
    # Match serialized stage NPZ types; this is a measurement, never retokenization.
    return sha(
        canonical(
            {
                "prompt_ids": np.asarray(trajectory.prompt_ids, dtype=np.int32).tolist(),
                "response_ids": np.asarray(trajectory.response_ids, dtype=np.int32).tolist(),
                "response_mask": np.asarray(trajectory.response_mask, dtype=np.int8).tolist(),
                "response_logprobs": np.asarray(trajectory.response_logprobs, dtype=np.float32).tolist(),
            }
        )
    )


def audit_memory_chain_crosswalk(path):
    """Check new mapping against original stage files; does NOT claim trainer consumption."""
    record = json.loads(read_regular(path))
    _require(record["schema"] == "uni-agent.memory-chain-crosswalk.v1", "Wrong chain crosswalk schema")
    _require(record["partition"] in ("train", "val"), "Wrong partition")
    expected_version = expected_sync_policy_version(record["global_steps"], record["partition"])
    _require(record["expected_policy_version"] == expected_version, "Wrong expected policy version")
    keys, rewards, covered = [], [], []
    chain_ids, siblings, sessions = set(), set(), set()
    for chain in record["chains"]:
        receipt = json.loads(read_regular(chain["receipt_path"]))
        _require(sha(canonical(receipt)) == chain["receipt_sha256"], "Chain receipt hash changed")
        body = {k: v for k, v in receipt.items() if k != "receipt_id"}
        _require(receipt["receipt_id"] == sha(canonical(body)), "Chain receipt identity changed")
        _require(receipt["credit_rule"] == "terminal-reader-grpo-v1", "Wrong credit rule")
        _require(
            receipt["chain_id"] not in chain_ids and receipt["sibling"] not in siblings, "Duplicate chain or sibling"
        )
        chain_ids.add(receipt["chain_id"])
        siblings.add(receipt["sibling"])
        _require(
            receipt["partition"] == record["partition"]
            and receipt["uid"] == record["uid"]
            and receipt["run_id"] == record["run_id"]
            and receipt["weight_version"] == expected_version,
            "Chain scope mismatch",
        )
        frozen = receipt["frozen"]
        manifest_raw = read_regular(receipt["frozen_manifest_path"])
        _require(
            sha(manifest_raw) == frozen["manifest_sha256"]
            and sha(read_regular(receipt["frozen_content_path"])) == frozen["content_sha256"],
            "Frozen artifact hash changed",
        )
        manifest = json.loads(manifest_raw)
        _require(
            manifest["chain_id"] == receipt["chain_id"] == frozen["memory_chain_id"]
            and manifest["writer_session_id"] == frozen["writer_session_id"]
            and manifest["source_version"] == frozen["source_version"]
            and manifest["content_sha256"] == frozen["content_sha256"],
            "Frozen artifact binding mismatch",
        )
        own = [item for item in record["items"] if item["chain_id"] == receipt["chain_id"]]
        _require(own == receipt["items"] and own and own[-1]["role"] == "B", "Chain mapping changed")
        roles = [item["role"] for item in own]
        count_a = roles.count("A")
        _require(
            0 < count_a < len(own) and roles == ["A"] * count_a + ["B"] * (len(own) - count_a),
            "Expected nonempty A then B stages",
        )
        for role in ("A", "B"):
            stage_items = [item for item in own if item["role"] == role]
            stage_ids = {item["gateway_session_id"] for item in stage_items}
            _require(len(stage_ids) == 1 and not stage_ids & sessions, "Reused stage session")
            sessions.update(stage_ids)
            expected_receipt = receipt["writer_receipt_sha256" if role == "A" else "reader_receipt_sha256"]
            _require(
                all(item["stage_receipt_id"] == expected_receipt for item in stage_items),
                "Stage receipt differs from chain binding",
            )
            _require(
                [item["stage_index"] for item in stage_items] == list(range(len(stage_items))), "Wrong stage indices"
            )
        covered.extend(own)
        _require(own[-1]["stage_reward"] == receipt["terminal_reward"], "Terminal reward changed")
        for index, item in enumerate(own):
            _require(item["tq_key"] == trajectory_tq_key(record["uid"], receipt["sibling"], index), "TQ key changed")
        rewards.append(receipt["terminal_reward"])
    _require(covered == record["items"], "Crosswalk items are not exactly partitioned by chains")
    _require(siblings == set(range(4 if record["partition"] == "train" else 1)), "Wrong sibling identities")
    for item in record["items"]:
        version = item["version_evidence"]
        _require(
            type(record["global_steps"]) is int
            and record["global_steps"] >= 0
            and all(
                type(version[name]) is int and version[name] == expected_version
                for name in ("min_global_steps", "max_global_steps")
            )
            and type(version["generation_count"]) is int
            and version["generation_count"] > 0
            and type(version["versioned_generation_count"]) is int
            and version["versioned_generation_count"] == version["generation_count"]
            and version["version_evidence_complete"] is True,
            "Incomplete actual version evidence",
        )
        raw = read_regular(item["stage_npz_path"], 64_000_000)
        meta_raw = read_regular(item["stage_json_path"], 8_000_000)
        _require(
            sha(raw) == item["stage_npz_sha256"] and sha(meta_raw) == item["stage_json_sha256"],
            "Stage dump hash changed",
        )
        meta = json.loads(meta_raw)
        _require(meta["schema"] == "uni-agent.gateway-stage-dump.v1", "Expected stage-only dump")
        _require(meta["gateway_session_id"] == item["gateway_session_id"], "Stage session changed")
        index = item["stage_index"]
        entry = meta["trajectories"][index]
        _require("transfer_queue_key" not in entry, "Stage dump claims TQ consumption")
        _require(entry["reward_score"] == item["stage_reward"], "Original stage reward changed")
        stage_receipt_raw = read_regular(item["stage_receipt_path"])
        _require(sha(stage_receipt_raw) == item["stage_receipt_file_sha256"], "Original receipt file hash changed")
        stage_receipt = json.loads(stage_receipt_raw)
        stage_body = {k: v for k, v in stage_receipt.items() if k != "receipt_id"}
        _require(
            stage_receipt["receipt_id"] == sha(canonical(stage_body)) == item["stage_receipt_id"],
            "Original receipt ID changed",
        )
        _require(
            stage_receipt["reward"] == item["stage_reward"]
            and stage_receipt["finished"] is True
            and stage_receipt["eligible"] is True
            and stage_receipt["fresh"] is True,
            "Original stage receipt not admitted",
        )
        _require(
            stage_receipt["dsh_session_id"] == "dsh-" + item["gateway_session_id"]
            and entry["reward_info"]["dsh"]["receipt_sha256"] == stage_receipt["receipt_id"],
            "Dump/receipt session binding changed",
        )
        _require(meta["trajectory_npz_sha256"] == sha(raw), "Stage metadata NPZ hash changed")
        with np.load(io.BytesIO(raw), allow_pickle=False) as arrays:
            measured = {
                name: arrays[f"traj{index}_{name}"].tolist()
                for name in ("prompt_ids", "response_ids", "response_mask", "response_logprobs")
            }
        _require(sha(canonical(measured)) == item["token_sha256"], "Stage token digest changed")
        keys.append(item["tq_key"])
    _require(len(keys) == len(set(keys)), "Duplicate TQ keys")
    _require(len(record["chains"]) == (4 if record["partition"] == "train" else 1), "Wrong chain group size")
    return {"keys": keys, "terminal_rewards": rewards, "consumption_verified": False}


@dataclass(frozen=True)
class _PendingChain:
    writer_spec: StageSpec
    writer_execution: GatewayStageExecution
    reader_spec: StageSpec
    reader_execution: GatewayStageExecution
    outcome: ChainOutcome


class NativeMemoryFramework(GatewayAgentFramework):
    def __init__(self, *args, memory_operator=None, memory_run_id=None, **kwargs):
        for flag in (
            "fail_on_rollout_error",
            "require_finished_episode",
            "require_verifier_reward",
            "require_trajectory_dump",
        ):
            _require(kwargs.get(flag) is True, f"NativeMemoryFramework requires {flag}=True")
        _require(
            not kwargs.get("reward_loop_worker_handles") and not kwargs.get("custom_reward_function_configured"),
            "Memory terminal credit cannot use reward workers",
        )
        _require(
            kwargs.get("trajectory_postprocessor") is None and not kwargs.get("trajectory_postprocessor_pass_context"),
            "Use mandatory StageSpec validator instead of a static trajectory postprocessor",
        )
        for config in kwargs["runner_registry"].values():
            _require(
                not any(
                    config.runner_kwargs.get(name) is not None
                    for name in (
                        "harbor_route_registration",
                        "dsh_episode_workdir_root",
                        "dsh_episode_source_root",
                        "dsh_episode_files",
                    )
                ),
                "Memory stages cannot copy episode inputs or inject Harbor routing",
            )
            _require(
                config.dispatch_mode == "ray_task" and config.trajectory_selection == "all",
                "Memory stages require ray_task and trajectory_selection=all",
            )
            _require(
                config.runner_fqn == "uni_agent.framework.task_runner.run_task",
                "Memory stages require real task runner",
            )
        super().__init__(*args, **kwargs)
        rollout = self._rollout_config
        _require(
            rollout is not None
            and rollout.n == 4
            and rollout.val_kwargs.n == 1
            and rollout.calculate_log_probs is True,
            "Memory requires n4 train, n1 val and calculate_log_probs=True",
        )
        _require(self._log_dir is not None, "Memory requires stage dump log_dir")
        self._memory_operator = memory_operator
        self._memory_run_id = memory_run_id
        self._pending = {}

    @classmethod
    def from_config(cls, *, config, gateway_manager, processor=None, reward_loop_worker_handles=None):
        for name, expected in {
            "trainer.use_v1": True,
            "trainer.v1.trainer_mode": "sync",
            "algorithm.adv_estimator": "grpo",
            "algorithm.use_kl_in_reward": False,
        }.items():
            _require(OmegaConf.select(config, name) == expected, f"Memory requires {name}={expected}")
        instance = super().from_config(
            config=config,
            gateway_manager=gateway_manager,
            processor=processor,
            reward_loop_worker_handles=reward_loop_worker_handles,
        )
        af = config.actor_rollout_ref.rollout.custom.agent_framework
        spec = dict(OmegaConf.to_container(af.memory_operator, resolve=True))
        for name in ("root", "runner_python", "runtime_executable"):
            spec[name] = Path(spec[name])
        instance._memory_operator = OperatorSpec(**spec)
        instance._memory_run_id = str(af.memory_run_id)
        return instance

    async def _run_prompt_rollouts(self, *, sample_fields, sample_index, global_steps, partition_id, num_sessions):
        _require(isinstance(self._memory_operator, OperatorSpec) and self._memory_run_id, "Memory operator is required")
        _require(
            partition_id in ("train", "val") and num_sessions == (4 if partition_id == "train" else 1),
            "Invalid memory group size",
        )
        expected_sync_policy_version(global_steps, partition_id)
        key = (partition_id, str(sample_fields.get("uid")), global_steps)
        _require(key not in self._pending, "Memory group scope is already active")
        self._pending[key] = {}
        try:
            return await super()._run_prompt_rollouts(
                sample_fields=sample_fields,
                sample_index=sample_index,
                global_steps=global_steps,
                partition_id=partition_id,
                num_sessions=num_sessions,
            )
        finally:
            self._pending.pop(key, None)

    async def _stage(
        self,
        spec,
        *,
        sample_fields,
        sample_index,
        session_index,
        global_steps,
        partition_id,
        group_size,
        runner_name,
        runner_config,
        sampling_params,
    ):
        kwargs = {
            **runner_config.runner_kwargs,
            "task_config_path": str(spec.task_config_path),
            "dsh_trace_root": str(spec.trace_root),
            "dsh_result_root": str(spec.result_root),
        }
        fields = {
            **sample_fields,
            "raw_prompt": spec.raw_prompt,
            "tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": spec.metadata}},
        }
        return await self._execute_gateway_stage(
            sample_fields=fields,
            sample_index=sample_index,
            session_index=session_index,
            global_steps=global_steps,
            partition_id=partition_id,
            group_size=group_size,
            runner_name=runner_name,
            runner_config=replace(runner_config, runner_kwargs=kwargs),
            sampling_params=sampling_params,
            stage_session_id=spec.gateway_session_id,
            dump_consumption_crosswalk=False,
        )

    @staticmethod
    def _outcome(spec, execution):
        receipt, envelope, scored, fixture = validate_stage_execution(spec, execution)
        binding = fixture.get("writer_binding", {})
        return StageOutcome(
            run_id=spec.context.run_id,
            partition=spec.context.partition,
            group_uid=spec.context.group_uid,
            sibling=spec.context.sibling,
            memory_chain_id=spec.chain_id,
            role="A" if spec.role == "writer" else "B",
            gateway_session_id=spec.gateway_session_id,
            dsh_session_id=receipt["dsh_session_id"],
            source_version=fixture["source_version"],
            checkpoint_identity=spec.operator.checkpoint_identity,
            receipt_sha256=execution.task_result.reward_info["dsh"]["receipt_sha256"],
            finished=receipt["finished"],
            eligible=receipt["eligible"],
            reward=receipt["reward"],
            trajectories=tuple(execution.trajectories),
            parent_receipt_sha256=binding.get("receipt_id"),
            frozen_manifest_sha256=binding.get("manifest_sha256"),
            frozen_content_sha256=binding.get("content_sha256"),
        )

    async def _run_agent_episode(
        self,
        *,
        sample_fields,
        sample_index,
        session_index,
        global_steps,
        partition_id,
        group_size,
        runner_name,
        runner_config,
        sampling_params,
    ):
        uid = str(sample_fields["uid"])
        context = GroupContext(self._memory_run_id, partition_id, uid, session_index, global_steps)
        chain_id = "memory-" + uuid4().hex
        writer = await asyncio.to_thread(
            prepare_writer_stage,
            self._memory_operator,
            context,
            chain_id=chain_id,
            gateway_session_id="memory-A-" + uuid4().hex,
        )
        args = dict(
            sample_fields=sample_fields,
            sample_index=sample_index,
            session_index=session_index,
            global_steps=global_steps,
            partition_id=partition_id,
            group_size=group_size,
            runner_name=runner_name,
            runner_config=runner_config,
            sampling_params=sampling_params,
        )
        a = await self._stage(writer, **args)
        reader = await asyncio.to_thread(
            freeze_and_prepare_reader, writer, a, reader_gateway_session_id="memory-B-" + uuid4().hex
        )
        b = await self._stage(reader, **args)
        wa, rb = await asyncio.to_thread(self._outcome, writer, a), await asyncio.to_thread(self._outcome, reader, b)
        # Verify the persisted receipt ID; legacy dsh.receipt_sha256 is this ID, not the file hash.
        writer_receipt = validate_stage_execution(writer, a)[0]
        reader_fixture = validate_stage_execution(reader, b)[3]
        binding = reader_fixture["writer_binding"]
        _require(
            binding["receipt_id"] == writer_receipt["receipt_id"]
            and binding["trace_sha256"] == writer_receipt["trace_sha256"]
            and binding["dsh_session_id"] == wa.dsh_session_id
            and binding["gateway_session_id"] == wa.gateway_session_id,
            "Actual writer binding mismatch",
        )
        frozen = FrozenBinding(
            chain_id,
            wa.dsh_session_id,
            rb.dsh_session_id,
            wa.source_version,
            wa.receipt_sha256,
            rb.frozen_manifest_sha256,
            rb.frozen_content_sha256,
        )
        chain = ChainOutcome(wa, rb, frozen)
        pending = self._pending[(partition_id, uid, global_steps)]
        _require(session_index not in pending, "Duplicate memory sibling")
        pending[session_index] = _PendingChain(writer, a, reader, b, chain)
        return list(wa.trajectories + rb.trajectories), sample_fields

    def _prepare_crosswalk(self, uid, pending, assignments, partition_id, global_steps):
        group = self._memory_operator.root / "groups" / uuid4().hex
        group.mkdir(parents=True, mode=0o700)
        items, chains = [], []
        for assignment in assignments:
            saved = pending[assignment.sibling]
            own = []
            index = 0
            for role, spec, execution in (
                ("A", saved.writer_spec, saved.writer_execution),
                ("B", saved.reader_spec, saved.reader_execution),
            ):
                _require(execution.run_dir is not None, "Memory requires stage dumps")
                npz, meta = execution.run_dir / "trajectory.npz", execution.run_dir / "trajectory.json"
                dsh = execution.task_result.reward_info["dsh"]
                artifact_key = hashlib.sha256(f"{dsh['dsh_session_id']}\0{dsh['trace_sha256']}".encode()).hexdigest()[
                    :24
                ]
                receipt_path = spec.result_root / artifact_key / "verifier-receipt.json"
                for stage_index, trajectory in enumerate(execution.trajectories):
                    own.append(
                        dict(
                            chain_id=assignment.memory_chain_id,
                            role=role,
                            stage_index=stage_index,
                            gateway_session_id=execution.session_id,
                            tq_key=assignment.tq_keys[index],
                            stage_reward=trajectory.reward_score,
                            stage_receipt_path=str(receipt_path),
                            stage_receipt_file_sha256=sha(read_regular(receipt_path)),
                            stage_receipt_id=dsh["receipt_sha256"],
                            token_sha256=_token_digest(trajectory),
                            version_evidence={
                                name: trajectory.extra_fields[name]
                                for name in (
                                    "min_global_steps",
                                    "max_global_steps",
                                    "generation_count",
                                    "versioned_generation_count",
                                    "version_evidence_complete",
                                )
                            },
                            stage_npz_path=str(npz),
                            stage_json_path=str(meta),
                            stage_npz_sha256=sha(read_regular(npz, 64_000_000)),
                            stage_json_sha256=sha(read_regular(meta, 8_000_000)),
                        )
                    )
                    index += 1
            body = dict(
                schema="dsh.memory-chain-credit.v1",
                credit_rule=assignment.credit_rule,
                status="admitted-not-consumed",
                chain_id=assignment.memory_chain_id,
                run_id=self._memory_run_id,
                partition=partition_id,
                uid=uid,
                sibling=assignment.sibling,
                weight_version=assignment.weight_version,
                checkpoint_identity=assignment.checkpoint_identity,
                terminal_reward=assignment.reward,
                writer_receipt_sha256=assignment.writer_receipt_sha256,
                reader_receipt_sha256=assignment.reader_receipt_sha256,
                frozen=vars(assignment.frozen),
                frozen_manifest_path=str(saved.writer_spec.root / "frozen/manifest.json"),
                frozen_content_path=str(saved.writer_spec.root / "frozen/memory.bin"),
                items=own,
            )
            body["receipt_id"] = sha(canonical(body))
            receipt_path = group / f"chain-{assignment.sibling}.json"
            _write_new(receipt_path, body)
            chains.append(dict(receipt_path=str(receipt_path), receipt_sha256=sha(read_regular(receipt_path))))
            items.extend(own)
        path = group / "crosswalk.json"
        _write_new(
            path,
            dict(
                schema="uni-agent.memory-chain-crosswalk.v1",
                status="prepared-not-consumed",
                run_id=self._memory_run_id,
                uid=uid,
                partition=partition_id,
                global_steps=global_steps,
                expected_policy_version=expected_sync_policy_version(global_steps, partition_id),
                chains=chains,
                items=items,
            ),
        )
        return path

    async def _write_prompt_trajectories_to_tq(self, *, uid, session_outcomes, global_steps, partition_id):
        pending = self._pending[(partition_id, uid, global_steps)]
        _require(len(pending) == len(session_outcomes), "Incomplete memory pending group")
        for sibling, trajectories, fields in session_outcomes:
            saved = pending[sibling]
            for spec, execution in (
                (saved.writer_spec, saved.writer_execution),
                (saved.reader_spec, saved.reader_execution),
            ):
                await asyncio.to_thread(validate_stage_execution, spec, execution)
            original = saved.outcome.writer.trajectories + saved.outcome.reader.trajectories
            _require(
                len(trajectories) == len(original) and all(a is b for a, b in zip(trajectories, original, strict=True)),
                "Memory trajectory identity/order changed",
            )
        assignments = validate_credit_group(
            [p.outcome for p in pending.values()],
            expected_version=expected_sync_policy_version(global_steps, partition_id),
            expected_group_uid=uid,
            expected_run_id=self._memory_run_id,
            expected_partition=partition_id,
        )
        path = await asyncio.to_thread(self._prepare_crosswalk, uid, pending, assignments, partition_id, global_steps)
        audit = await asyncio.to_thread(audit_memory_chain_crosswalk, path)
        expected = [key for assignment in assignments for key in assignment.tq_keys]
        _require(audit["keys"] == expected, "Final memory crosswalk differs from TQ keys")
        await super()._write_prompt_trajectories_to_tq(
            uid=uid, session_outcomes=session_outcomes, global_steps=global_steps, partition_id=partition_id
        )
        _write_new(
            path.with_name("submission.json"),
            dict(status="tq-write-returned-not-consumed", keys=expected, crosswalk_sha256=sha(read_regular(path))),
        )
