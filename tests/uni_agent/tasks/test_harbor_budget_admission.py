"""Real Gateway proof and Framework-private admission/dump binding regressions."""

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import replace

import pytest
import pytest_asyncio
from omegaconf import OmegaConf

from examples.dsh.ops.audit_qwen3_4b_online_rl import _load_dump_trajectory
from tests.uni_agent.framework.test_gateway_stage_execution import build
from tests.uni_agent.gateway.test_session_budget_proof import LengthBackend
from tests.uni_agent.gateway.test_session_generation_budget import session
from tests.uni_agent.gateway.test_session_multiple_chains_on_cpu import _run
from uni_agent.gateway.session.types import budget_json_sha256
from uni_agent.tasks.harbor_dsh.budget_admission import bind_budget_dump, record_budget_admission
from uni_agent.tasks.harbor_dsh.registration import validate_registered_trajectories

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest_asyncio.fixture
async def evidence(tmp_path):
    gateway = session(3)
    gateway._trajectory_capacity = 100
    gateway._sampling_params["logprobs"] = True
    await _run(gateway, LengthBackend(), [{"role": "user", "content": "task"}], max_tokens=99)
    trajectory = (await gateway.finalize())[0]
    receipt_id = "sha256:" + "1" * 64
    trajectory = replace(
        trajectory,
        finished=False,
        reward_score=1.0,
        reward_metrics={"verifier_reward": 1.0},
        extra_fields={
            **trajectory.extra_fields,
            "dsh_reward_info": {
                "reward": 1.0,
                "verifier_reward": 1.0,
                "finished": False,
                "harbor_dsh": {"receipt_sha256": receipt_id, "job_id": "job-1"},
            },
        },
    )
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    directory = root / "job-1"
    directory.mkdir(mode=0o700)
    context = dict(
        gateway_session_id="budget",
        partition_id="train",
        global_steps=1,
        group_uid="group-1",
        group_size=4,
        sample_index=0,
        session_index=0,
    )
    kwargs = dict(
        context=context,
        run_id="run-1",
        receipt_id=receipt_id,
        policy={
            "termination_policy": "budget-terminal-v1",
            "budget_limits": {
                "max_generated_tokens": 3,
                "trajectory_capacity": 100,
            },
        },
        receipt={"termination_policy": "budget-terminal-v1", "termination_kind": "budget_exhausted", "finished": False},
    )
    return trajectory, root, directory, kwargs


def record(trajectory, directory, kwargs, *, online):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return record_budget_admission(trajectory, directory=descriptor, online=online, **kwargs)
    finally:
        os.close(descriptor)


def test_real_proof_admission_replay_is_read_only(evidence):
    trajectory, _, directory, kwargs = evidence
    admitted = record(trajectory, directory, kwargs, online=True)
    path = directory / "admission-chain-1.json"
    before = path.stat().st_mtime_ns, path.read_bytes()
    restored = record(admitted, directory, kwargs, online=False)
    assert restored.finished is False
    assert restored.response_mask == trajectory.response_mask
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before


def test_offline_admission_cannot_create_authority(evidence):
    trajectory, _, directory, kwargs = evidence
    with pytest.raises(FileNotFoundError):
        record(trajectory, directory, kwargs, online=False)
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize("change", ["context", "run", "receipt", "policy", "version", "projection", "rehash-proof"])
def test_private_admission_rejects_rehashed_or_rebound_evidence(evidence, change):
    trajectory, _, directory, kwargs = evidence
    admitted = deepcopy(record(trajectory, directory, kwargs, online=True))
    kwargs = deepcopy(kwargs)
    if change == "context":
        kwargs["context"]["global_steps"] += 1
    elif change == "run":
        kwargs["run_id"] = "other-run"
    elif change == "receipt":
        kwargs["receipt_id"] = "sha256:" + "2" * 64
        admitted.extra_fields["dsh_reward_info"]["harbor_dsh"]["receipt_sha256"] = kwargs["receipt_id"]
    elif change == "policy":
        kwargs["policy"]["operator_revision"] = "other"
    elif change == "version":
        admitted.extra_fields["max_global_steps"] = 999
    elif change == "projection":
        admitted.extra_fields["budget_admission"]["admission_sha256"] = "sha256:" + "2" * 64
    else:
        proof = admitted.extra_fields["gateway_budget_proof"]
        proof["request_count"] = 2
        proof["exhaustion_events"][0]["request_index"] = 2
        proof["proof_sha256"] = budget_json_sha256({k: v for k, v in proof.items() if k != "proof_sha256"})
    with pytest.raises(ValueError, match="Private budget admission|projection mismatch"):
        record(admitted, directory, kwargs, online=False)


@pytest.mark.parametrize("change", ["npz", "metadata", "context", "tokens", "projection"])
def test_private_dump_binds_exact_artifact_and_identity(evidence, change):
    trajectory, root, directory, kwargs = evidence
    admitted = record(trajectory, directory, kwargs, online=True)
    params = dict(
        context=kwargs["context"],
        npz_sha256="sha256:" + "a" * 64,
        metadata={"group_uid": "group-1", "finished": False},
        artifact_root=root,
    )
    bind_budget_dump([admitted], online=True, **params)
    saved = (directory / "dump-chain-1.json").read_bytes()
    bind_budget_dump([admitted], online=False, **params)
    assert (directory / "dump-chain-1.json").read_bytes() == saved
    params = deepcopy(params)
    admitted = deepcopy(admitted)
    if change == "npz":
        params["npz_sha256"] = "sha256:" + "b" * 64
    elif change == "metadata":
        params["metadata"]["finished"] = True
    elif change == "context":
        params["context"]["group_uid"] = "other"
    elif change == "tokens":
        admitted.response_ids[0] += 1
    else:
        admitted.extra_fields["budget_admission"]["admission_sha256"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="private admission|Private dump binding"):
        bind_budget_dump([admitted], online=False, **params)


def test_real_framework_npz_dump_restores_and_validates_private_binding(evidence, tmp_path):
    trajectory, root, directory, kwargs = evidence
    admitted = record(trajectory, directory, kwargs, online=True)
    framework, _, _ = build(tmp_path)
    framework._termination_policy = "budget-terminal-v1"
    framework._trajectory_postprocessor_kwargs = {"artifact_root": str(root)}
    framework._require_trajectory_dump = True
    dump = tmp_path / "dump"
    framework._dump_trajectories(
        dump, "budget", [admitted], **{k: v for k, v in kwargs["context"].items() if k != "gateway_session_id"}
    )
    metadata = json.loads((dump / "trajectory.json").read_text())
    npz = (dump / "trajectory.npz").read_bytes()
    restored = _load_dump_trajectory(npz_bytes=npz, trajectory_meta=metadata["trajectories"][0], trajectory_index=0)
    restored = record(restored, directory, kwargs, online=False)
    bind_budget_dump(
        [restored],
        context=kwargs["context"],
        metadata=metadata,
        npz_sha256="sha256:" + hashlib.sha256(npz).hexdigest(),
        artifact_root=root,
        online=False,
    )
    assert restored.finished is False
    assert restored.response_mask == admitted.response_mask


def test_budget_framework_cannot_disable_gateway_version_evidence(tmp_path):
    limits = {"max_generated_tokens": 3, "trajectory_capacity": 100}
    policy = {"termination_policy": "budget-terminal-v1", "budget_limits": limits}
    settings = dict(
        termination_policy="budget-terminal-v1",
        fail_on_rollout_error=True,
        require_finished_episode=True,
        require_verifier_reward=True,
        require_trajectory_dump=True,
        require_version_evidence=False,
        trajectory_postprocessor_pass_context=True,
        max_generated_tokens_per_episode=3,
        mask_unfinished_episode=False,
        trajectory_postprocessor=validate_registered_trajectories,
        trajectory_postprocessor_kwargs={**policy, "policy_template": policy},
        rollout_config=OmegaConf.create({"max_model_len": 100}),
    )
    with pytest.raises(ValueError, match="budget-terminal"):
        build(tmp_path, **settings)
