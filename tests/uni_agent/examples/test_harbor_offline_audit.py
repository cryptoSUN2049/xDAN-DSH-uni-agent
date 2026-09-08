import hashlib
import json

import numpy as np
import pytest
import pytest_asyncio

from tests.uni_agent.tasks.test_harbor_dsh_registration import checksum
from tests.uni_agent.tasks.test_harbor_dsh_task import config, downloaded, evidence
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.harbor_dsh.client import HarborDshClient
from uni_agent.tasks.harbor_dsh.task import HarborDshTask

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest_asyncio.fixture
async def audit_case(tmp_path, monkeypatch):
    async def run(self, request):
        return downloaded(request, evidence(request))

    monkeypatch.setattr(HarborDshClient, "run", run)
    ctx = dict(config(tmp_path).runner_context.model_dump(), group_size=1, session_index=0)
    cfg = config(tmp_path, runner_context=ctx)
    result = await HarborDshTask(cfg).run()
    policy = cfg.policy.model_dump(mode="json")
    template = {k: v for k, v in policy.items() if k != "gateway_port"}
    root = tmp_path / "registrations"
    root.mkdir(mode=0o700)
    directory = root / cfg.run_id
    directory.mkdir(mode=0o700)
    registration = directory / "registration.json"
    registration.write_text(
        json.dumps(
            dict(
                schema="dsh.harbor-route-registration.v1",
                run_id=cfg.run_id,
                controller_id="controller-1",
                run_spec_sha256="sha256:" + "d" * 64,
                policy=policy,
                policy_sha256=checksum(policy),
                registered_at_unix=1000.0,
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    registration.chmod(0o600)
    launch = tmp_path / "launch.json"
    launch.write_text(
        json.dumps(
            dict(
                schema="dsh.harbor-m2-launch.v1",
                postprocessor=dict(
                    artifact_root=cfg.artifact_root,
                    run_id=cfg.run_id,
                    worker_id=cfg.worker_id,
                    task_ref=cfg.task_ref.model_dump(mode="json"),
                    policy_template=template,
                    instruction=cfg.instruction,
                    registration_root=str(root),
                    controller_id="controller-1",
                    run_spec_sha256="sha256:" + "d" * 64,
                ),
            )
        )
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    npz = logs / "trajectory.npz"
    np.savez(npz, traj0_prompt_ids=[1], traj0_response_ids=[2], traj0_response_mask=[1], traj0_response_logprobs=[-0.1])
    info = build_reward_info(result)
    metadata = dict(
        schema="uni-agent.trajectory-dump.v2",
        **ctx,
        session_id=ctx["gateway_session_id"],
        trajectory_npz_sha256="sha256:" + hashlib.sha256(npz.read_bytes()).hexdigest(),
        num_trajectories=1,
        trajectories=[
            dict(
                trajectory_index=0,
                transfer_queue_key="group-1_0_0",
                prompt_len=1,
                response_len=1,
                model_token_count=1,
                has_logprobs=True,
                reward_score=1.0,
                reward_extra_info={"verifier_reward": 1.0},
                reward_info=info,
            )
        ],
    )
    dump = logs / "trajectory.json"
    dump.write_text(json.dumps(metadata))
    train = tmp_path / "train"
    train.mkdir()
    row = train / "4.jsonl"
    row.write_text(json.dumps(dict(step=4, uid="group-1_0_0", score=1.0)) + "\n")
    val = tmp_path / "val"
    val.mkdir()
    return (
        dict(
            launch_path=launch,
            agent_log_dir=logs,
            rollout_data_dir=train,
            validation_data_dir=val,
            train_n=1,
            validation_n=1,
        ),
        row,
        dump,
        registration,
    )


def test_real_saved_evidence_binds_train_batch(audit_case):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, *_ = audit_case
    report = audit_training(**kwargs)
    assert report["passed"], report
    assert report["groups"][0]["status"] == "admitted-and-training-batch-matched"
    assert report["optimizer_update_verified"] is False


@pytest.mark.parametrize("change", ["score", "missing", "duplicate", "unexpected", "npz", "registration", "identity"])
def test_rejects_bad_binding(audit_case, change):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, row, dump, registration = audit_case
    if change == "score":
        row.write_text(json.dumps(dict(step=4, uid="group-1_0_0", score=0)) + "\n")
    elif change == "missing":
        row.unlink()
    elif change == "duplicate":
        row.write_text(row.read_text() * 2)
    elif change == "unexpected":
        row.write_text(row.read_text() + json.dumps(dict(step=4, uid="other", score=1)) + "\n")
    elif change == "npz":
        (dump.parent / "trajectory.npz").write_bytes(b"broken")
    elif change == "registration":
        registration.unlink()
    else:
        data = json.loads(dump.read_text())
        data["sample_index"] = 99
        dump.write_text(json.dumps(data))
    assert not audit_training(**kwargs)["passed"]


def test_missing_group_session_is_rejected(audit_case):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, *_ = audit_case
    assert not audit_training(**dict(kwargs, train_n=2))["passed"]


def test_raw_artifact_tamper_is_rejected(audit_case):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, *_ = audit_case
    launch = json.loads(kwargs["launch_path"].read_text())
    from pathlib import Path

    artifact = next(Path(launch["postprocessor"]["artifact_root"]).rglob("object-dsh_trace"))
    artifact.write_bytes(b"changed")
    assert not audit_training(**kwargs)["passed"]


def test_validation_cannot_supply_training_consumption(audit_case):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, row, *_ = audit_case
    (kwargs["validation_data_dir"] / row.name).write_bytes(row.read_bytes())
    row.unlink()
    assert not audit_training(**kwargs)["passed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mixed", "val-only", "bad-score", "missing-val", "default-val-only"])
async def test_validation_is_reported_as_evaluated(audit_case, tmp_path, mode):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, _, dump, _ = audit_case
    metadata = json.loads(dump.read_text())
    cfg = config(tmp_path)
    ctx = dict(
        cfg.runner_context.model_dump(),
        group_size=1,
        session_index=0,
        partition_id="val",
        group_uid="val-group",
        gateway_session_id="val-session",
    )
    cfg = config(tmp_path, runner_context=ctx, gateway_base_url="http://10.0.0.2:45678/sessions/val-session/v1")
    result = await HarborDshTask(cfg).run()
    metadata.update(ctx, session_id="val-session")
    metadata["trajectories"][0].update(transfer_queue_key="val-group_0_0", reward_info=build_reward_info(result))
    val_dump = dump.parent / "val-session"
    val_dump.mkdir()
    (val_dump / "trajectory.npz").write_bytes((dump.parent / "trajectory.npz").read_bytes())
    (val_dump / "trajectory.json").write_text(json.dumps(metadata))
    (kwargs["validation_data_dir"] / "4.jsonl").write_text(
        json.dumps(dict(step=4, uid="val-group_0_0", score=1.0)) + "\n"
    )
    if mode != "mixed":
        dump.unlink()
        if mode != "default-val-only":
            kwargs.update(val_only=True, rollout_data_dir=None, train_n=None)
        if mode == "bad-score":
            (kwargs["validation_data_dir"] / "4.jsonl").write_text(
                json.dumps(dict(step=4, uid="val-group_0_0", score=0.0)) + "\n"
            )
        if mode == "missing-val":
            (val_dump / "trajectory.json").unlink()
            (kwargs["validation_data_dir"] / "4.jsonl").unlink()
    report = audit_training(**kwargs)
    assert report["passed"] == (mode in {"mixed", "val-only"}), report
    if mode == "val-only":
        assert report["optimizer_update_verified"] is False
        assert [group["status"] for group in report["groups"]] == ["admitted-and-evaluated"]
    if mode == "mixed":
        assert {group["status"] for group in report["groups"]} == {
            "admitted-and-training-batch-matched",
            "admitted-and-evaluated",
        }
