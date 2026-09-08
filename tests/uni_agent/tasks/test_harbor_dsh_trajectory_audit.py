import copy
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio

from tests.uni_agent.tasks.test_harbor_dsh_task import config, downloaded, evidence
from uni_agent.gateway.session import Trajectory
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.dsh.trajectory_audit import TrajectoryAuditError
from uni_agent.tasks.harbor_dsh.client import HarborDshClient
from uni_agent.tasks.harbor_dsh.task import HarborDshTask
from uni_agent.tasks.harbor_dsh.trajectory_audit import validate_trajectories

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest_asyncio.fixture
async def case(tmp_path, monkeypatch):
    async def run(self, request):
        return downloaded(request, evidence(request))

    monkeypatch.setattr(HarborDshClient, "run", run)
    cfg = config(tmp_path)
    result = await HarborDshTask(cfg).run()
    trajectory = Trajectory(
        prompt_ids=[1, 2],
        response_ids=[3, 4, 5],
        response_mask=[1, 0, 1],
        response_logprobs=[-0.1, 0.0, -0.2],
        finished=True,
        reward_score=1.0,
        extra_fields={"dsh_reward_info": build_reward_info(result)},
    )
    kwargs = {
        "context": cfg.runner_context.model_dump(),
        "artifact_root": cfg.artifact_root,
        "run_id": cfg.run_id,
        "worker_id": cfg.worker_id,
        "task_ref": cfg.task_ref.model_dump(),
        "policy": cfg.policy.model_dump(mode="json"),
        "instruction": cfg.instruction,
    }
    directory = Path(result.reward_info["harbor_dsh"]["receipt_path"]).parent
    return trajectory, kwargs, directory


def test_valid_receipt_returns_exact_original_gateway_objects(case):
    trajectory, kwargs, _ = case
    before = copy.deepcopy(trajectory)
    result = validate_trajectories((trajectory,), **kwargs)
    assert result == [before]
    assert result[0] is trajectory
    assert result[0].response_ids is trajectory.response_ids
    assert result[0].response_logprobs is trajectory.response_logprobs


@pytest.mark.parametrize(
    "field",
    ["gateway_session_id", "partition_id", "group_uid", "sample_index", "session_index", "global_steps", "group_size"],
)
def test_all_framework_context_fields_are_bound(case, field):
    trajectory, kwargs, _ = case
    kwargs["context"][field] = {
        "gateway_session_id": "another",
        "partition_id": "val",
        "group_uid": "another",
        "sample_index": 4,
        "session_index": 4,
        "global_steps": 5,
        "group_size": 5,
    }[field]
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


@pytest.mark.parametrize("field", ["run_id", "worker_id", "instruction", "task_ref", "policy"])
def test_operator_configuration_is_not_inferred_from_receipt(case, field):
    trajectory, kwargs, _ = case
    if field == "task_ref":
        kwargs[field]["id"] = "other"
    elif field == "policy":
        kwargs[field]["dsh_release"]["source_sha"] = "c" * 40
    else:
        kwargs[field] = "other"
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


@pytest.mark.parametrize(
    "filename",
    [
        "request.json",
        "manifest.json",
        "receipt.json",
        "object-dsh_trace",
        "object-dsh_result",
        "object-harbor_result",
        "object-reward",
        "object-verifier_log",
    ],
)
def test_every_saved_evidence_file_is_rechecked(case, filename):
    trajectory, kwargs, directory = case
    path = directory / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


@pytest.mark.parametrize(
    "attack", ["symlink-file", "hardlink", "directory", "fifo", "public-file", "public-job", "symlink-job"]
)
def test_unsafe_evidence_files_are_not_followed_or_read(case, attack, tmp_path):
    trajectory, kwargs, directory = case
    path = directory / "object-dsh_trace"
    if attack == "public-job":
        directory.chmod(0o755)
    elif attack == "symlink-job":
        destination = tmp_path / "moved"
        directory.rename(destination)
        directory.symlink_to(destination, target_is_directory=True)
    elif attack == "public-file":
        path.chmod(0o644)
    elif attack == "hardlink":
        os.link(path, tmp_path / "extra-link")
    else:
        content = path.read_bytes()
        path.unlink()
        if attack == "directory":
            path.mkdir()
        elif attack == "fifo":
            os.mkfifo(path, 0o600)
        else:
            target = tmp_path / "outside"
            target.write_bytes(content)
            path.symlink_to(target)
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("response_ids", []),
        ("response_mask", [0, 0, 0]),
        ("response_mask", [1]),
        ("response_logprobs", None),
        ("response_logprobs", [float("nan"), 0, -0.1]),
        ("reward_score", 0.0),
        ("finished", False),
    ],
)
def test_gateway_token_and_typed_reward_contract_is_required(case, field, value):
    trajectory, kwargs, _ = case
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((replace(trajectory, **{field: value}),), **kwargs)


@pytest.mark.parametrize("field", ["receipt_path", "receipt_sha256", "job_id", "request_sha256", "gateway_session_id"])
def test_reward_metadata_cannot_redirect_or_rebind_saved_evidence(case, field):
    trajectory, kwargs, _ = case
    trajectory.extra_fields["dsh_reward_info"]["harbor_dsh"][field] = "forged"
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


def test_empty_trajectory_set_is_not_admitted(case):
    _, kwargs, _ = case
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((), **kwargs)


def test_oversized_control_json_is_rejected(case):
    trajectory, kwargs, directory = case
    (directory / "receipt.json").write_bytes(b" " * 65537)
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


def test_receipt_unknown_fields_are_rejected_even_with_rehashed_body(case):
    from tests.uni_agent.tasks.test_harbor_dsh_task import digest, raw

    trajectory, kwargs, directory = case
    receipt = json.loads((directory / "receipt.json").read_bytes())
    receipt.pop("receipt_id")
    receipt["eligible"] = True
    checksum = digest(raw(receipt))
    (directory / "receipt.json").write_bytes(raw({**receipt, "receipt_id": checksum}))
    trajectory.extra_fields["dsh_reward_info"]["harbor_dsh"]["receipt_sha256"] = checksum
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


@pytest.mark.parametrize("attack", ["public", "symlink"])
def test_operator_root_is_private_and_not_a_symlink(case, tmp_path, attack):
    trajectory, kwargs, _ = case
    root = Path(kwargs["artifact_root"])
    if attack == "public":
        root.chmod(0o755)
    else:
        destination = tmp_path / "root-moved"
        root.rename(destination)
        root.symlink_to(destination, target_is_directory=True)
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


@pytest.mark.asyncio
async def test_real_framework_fqn_kwargs_and_context_contract(case):
    from tests.uni_agent.framework.test_generate_sequences_on_cpu import (
        _async_noop_runner,
        _build_framework_with_agent_runners,
        _FakeGatewayManager,
        _inline_runner_config,
    )

    trajectory, kwargs, _ = case
    context = kwargs.pop("context")
    framework = await _build_framework_with_agent_runners(
        agent_runners={"runner": _inline_runner_config(_async_noop_runner)},
        gateway_manager=_FakeGatewayManager({}),
        trajectory_postprocessor_fqn="uni_agent.tasks.harbor_dsh.trajectory_audit.validate_trajectories",
        trajectory_postprocessor_kwargs=kwargs,
        trajectory_postprocessor_pass_context=True,
    )
    result = await framework._apply_trajectory_postprocessor([trajectory], context=context)
    assert result[0] is trajectory


@pytest.mark.asyncio
async def test_zero_verifier_reward_is_admitted_without_token_changes(tmp_path, monkeypatch):
    async def run(self, request):
        return downloaded(request, evidence(request, score=0.0))

    monkeypatch.setattr(HarborDshClient, "run", run)
    cfg = config(tmp_path)
    result = await HarborDshTask(cfg).run()
    trajectory = Trajectory(
        prompt_ids=[1],
        response_ids=[2],
        response_mask=[1],
        response_logprobs=[-0.1],
        finished=True,
        reward_score=0.0,
        extra_fields={"dsh_reward_info": build_reward_info(result)},
    )
    admitted = validate_trajectories(
        (trajectory,),
        context=cfg.runner_context.model_dump(),
        artifact_root=cfg.artifact_root,
        run_id=cfg.run_id,
        worker_id=cfg.worker_id,
        task_ref=cfg.task_ref,
        policy=cfg.policy,
        instruction=cfg.instruction,
    )
    assert admitted[0] is trajectory
    assert admitted[0].reward_score == 0.0
