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
async def audit_case(tmp_path, monkeypatch, request):
    async def run(self, request):
        return downloaded(request, evidence(request))

    monkeypatch.setattr(HarborDshClient, "run", run)
    ctx = dict(config(tmp_path).runner_context.model_dump(), group_size=1, session_index=0)
    ctx.update(getattr(request, "param", {}))
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
    row.write_text(json.dumps(dict(step=ctx["global_steps"], uid="group-1_0_0", score=1.0)) + "\n")
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


def test_training_without_validation_directory(audit_case):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, *_ = audit_case
    kwargs.pop("validation_data_dir").rmdir()
    kwargs.pop("validation_n")
    report = audit_training(**kwargs, no_validation=True)
    assert report["passed"], report
    assert report["mode"] == "training-only"
    assert report["unconsumed_groups"] == []


@pytest.mark.parametrize("conflict", [{"val_only": True}, {"validation_n": 1}])
def test_no_validation_rejects_conflicting_options(audit_case, conflict):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, *_ = audit_case
    kwargs.pop("validation_data_dir")
    kwargs.pop("validation_n")
    assert not audit_training(**dict(kwargs, no_validation=True, **conflict))["passed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["prefetch", "missing-consumed", "tampered-prefetch"])
async def test_prefetch_is_separate_from_consumption(audit_case, tmp_path, mode):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, row, dump, _ = audit_case
    metadata = json.loads(dump.read_text())
    ctx = dict(
        config(tmp_path).runner_context.model_dump(),
        group_size=1,
        session_index=0,
        group_uid="prefetch-group",
        gateway_session_id="prefetch-session",
        global_steps=5,
    )
    cfg = config(tmp_path, runner_context=ctx, gateway_base_url="http://10.0.0.2:45678/sessions/prefetch-session/v1")
    result = await HarborDshTask(cfg).run()
    metadata.update(ctx, session_id="prefetch-session")
    metadata["trajectories"][0].update(transfer_queue_key="prefetch-group_0_0", reward_info=build_reward_info(result))
    prefetch = dump.parent / "prefetch-session"
    prefetch.mkdir()
    npz = prefetch / "trajectory.npz"
    npz.write_bytes((dump.parent / "trajectory.npz").read_bytes())
    prefetch_dump = prefetch / "trajectory.json"
    prefetch_dump.write_text(json.dumps(metadata))
    if mode == "missing-consumed":
        row.write_text(row.read_text() + json.dumps(dict(step=6, uid="missing_0_0", score=1.0)) + "\n")
    if mode == "tampered-prefetch":
        npz.write_bytes(b"tampered")
    before = prefetch_dump.read_bytes()
    report = audit_training(**kwargs)
    assert report["passed"] == (mode == "prefetch"), report
    assert prefetch_dump.read_bytes() == before
    if mode == "prefetch":
        assert [g["group_uid"] for g in report["groups"]] == ["group-1"]
        assert [g["group_uid"] for g in report["unconsumed_groups"]] == ["prefetch-group"]
        assert report["unconsumed_trajectory_count"] == 1
        assert report["unconsumed_groups"][0]["status"] == "admitted-not-consumed"


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


@pytest.mark.parametrize("audit_case", [{"global_steps": 1}], indirect=True)
def test_async_generation_one_consumed_at_two_preserves_source(audit_case):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, row, dump, _ = audit_case
    kwargs.pop("validation_data_dir")
    kwargs.pop("validation_n")
    meta = json.loads(dump.read_text())
    meta["trajectories"][0].update(
        min_global_steps=0,
        max_global_steps=1,
        generation_count=3,
        versioned_generation_count=3,
        version_evidence_complete=True,
    )
    dump.write_text(json.dumps(meta))
    row.write_text(json.dumps(dict(step=2, uid="group-1_0_0", score=1.0)) + "\n")
    before = dump.read_bytes()
    assert not audit_training(**kwargs, no_validation=True)["passed"]
    report = audit_training(**kwargs, no_validation=True, async_training=True)
    assert report["passed"], report
    group = report["groups"][0]
    assert report["schema"] == "dsh.harbor-training-batch-audit.v2"
    assert group["global_steps"] == group["generation_global_steps"] == 1
    assert group["training_global_steps"] == 2
    assert group["consumed_rows"] == [{"transfer_queue_key": "group-1_0_0", "training_global_steps": 2, "reward": 1.0}]
    assert group["version_evidence"][0]["min_global_steps"] == 0
    assert group["version_evidence"][0]["max_global_steps"] == 1
    assert dump.read_bytes() == before


@pytest.mark.parametrize("audit_case", [{"global_steps": 1}], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "cross-step",
        "unknown-key",
        "reward",
        "before-generation",
        "version-count",
        "version-missing",
        "future-policy",
        "distant-policy",
    ],
)
def test_async_rejects_false_consumption_or_version_proof(audit_case, fault):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, row, dump, _ = audit_case
    kwargs.pop("validation_data_dir")
    kwargs.pop("validation_n")
    meta = json.loads(dump.read_text())
    entry = meta["trajectories"][0]
    entry.update(
        min_global_steps=0,
        max_global_steps=1,
        generation_count=3,
        versioned_generation_count=3,
        version_evidence_complete=True,
    )
    rows = [dict(step=2, uid="group-1_0_0", score=1.0)]
    if fault == "duplicate":
        rows.append(dict(rows[0]))
    elif fault == "cross-step":
        rows.append(dict(rows[0], step=3))
    elif fault == "unknown-key":
        rows[0]["uid"] = "unknown_0_0"
    elif fault == "reward":
        rows[0]["score"] = 0.0
    elif fault == "before-generation":
        rows[0]["step"] = 0
    elif fault == "version-count":
        entry["versioned_generation_count"] = 2
    elif fault in {"future-policy", "distant-policy"}:
        entry["max_global_steps"] = 2 if fault == "future-policy" else 99
    else:
        entry.pop("version_evidence_complete")
    dump.write_text(json.dumps(meta))
    row.write_text("".join(json.dumps(value) + "\n" for value in rows))
    report = audit_training(**kwargs, no_validation=True, async_training=True)
    assert not report["passed"], report


@pytest.mark.asyncio
@pytest.mark.parametrize("audit_case", [{"global_steps": 1, "group_size": 2}], indirect=True)
@pytest.mark.parametrize("fault", ["none", "partial", "split"])
async def test_async_complete_group_has_one_consumer_step(audit_case, tmp_path, fault):
    from examples.harbor.audit_m2_training import audit_training

    kwargs, row, dump, _ = audit_case
    kwargs.pop("validation_data_dir")
    kwargs.pop("validation_n")
    kwargs["train_n"] = 2
    metadata = json.loads(dump.read_text())
    versions = dict(
        min_global_steps=0,
        max_global_steps=1,
        generation_count=3,
        versioned_generation_count=3,
        version_evidence_complete=True,
    )
    metadata["trajectories"][0].update(versions)
    dump.write_text(json.dumps(metadata))
    ctx = {key: metadata[key] for key in config(tmp_path).runner_context.model_fields}
    ctx.update(session_index=1, gateway_session_id="session-second")
    cfg = config(tmp_path, runner_context=ctx, gateway_base_url="http://10.0.0.2:45678/sessions/session-second/v1")
    result = await HarborDshTask(cfg).run()
    metadata.update(ctx, session_id="session-second")
    metadata["trajectories"][0].update(transfer_queue_key="group-1_1_0", reward_info=build_reward_info(result))
    folder = dump.parent / "second"
    folder.mkdir()
    (folder / "trajectory.npz").write_bytes((dump.parent / "trajectory.npz").read_bytes())
    (folder / "trajectory.json").write_text(json.dumps(metadata))
    rows = [dict(step=2, uid="group-1_0_0", score=1.0)]
    if fault != "partial":
        rows.append(dict(step=3 if fault == "split" else 2, uid="group-1_1_0", score=1.0))
    row.write_text("".join(json.dumps(value) + "\n" for value in rows))
    report = audit_training(**kwargs, no_validation=True, async_training=True)
    assert report["passed"] == (fault == "none"), report


@pytest.mark.parametrize("audit_case", [{"global_steps": 1}], indirect=True)
def test_async_cli_flag_emits_explicit_v2(audit_case, monkeypatch, capsys):
    from examples.harbor.audit_m2_training import main

    kwargs, row, dump, _ = audit_case
    meta = json.loads(dump.read_text())
    meta["trajectories"][0].update(
        min_global_steps=0,
        max_global_steps=1,
        generation_count=3,
        versioned_generation_count=3,
        version_evidence_complete=True,
    )
    dump.write_text(json.dumps(meta))
    row.write_text(json.dumps(dict(step=2, uid="group-1_0_0", score=1.0)) + "\n")
    argv = ["audit", "--train-n", "1", "--no-validation", "--async-training"]
    for name in ("launch_path", "agent_log_dir", "rollout_data_dir"):
        argv += ["--" + name.replace("_", "-"), str(kwargs[name])]
    monkeypatch.setattr("sys.argv", argv)
    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] and report["schema"] == "dsh.harbor-training-batch-audit.v2"
    assert report["groups"][0]["generation_global_steps"] == 1
    assert report["groups"][0]["training_global_steps"] == 2
