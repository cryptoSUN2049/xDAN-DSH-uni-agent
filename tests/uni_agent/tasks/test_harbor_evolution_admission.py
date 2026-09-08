import json
from pathlib import Path

import pytest

from tests.uni_agent.tasks.test_harbor_dsh_task import config, digest, downloaded, evidence, raw, t2_binding
from tests.uni_agent.tasks.test_harbor_evolution_scoring import case as scoring_case
from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256, release_patch_paths_digest
from uni_agent.gateway.session import Trajectory
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.dsh.trajectory_audit import TrajectoryAuditError
from uni_agent.tasks.harbor_dsh import task as module
from uni_agent.tasks.harbor_dsh.trajectory_audit import validate_trajectories


def configured(tmp_path):
    data = scoring_case.__wrapped__(tmp_path)
    cfg = config(tmp_path)
    policy = cfg.policy.model_dump(mode="json")
    policy["dsh_release"]["patch_sha256s"] = [T2_PATCH_SHA256]
    metadata = json.loads(Path(data["binding"].metadata_path).read_bytes())
    from uni_agent.tasks.harbor_dsh.protocol import DshRelease

    metadata["patches_sha256"] = release_patch_paths_digest(DshRelease.model_validate(policy["dsh_release"]))
    metadata["environment_digest"] = policy["dsh_release"]["runtime_sha256"]
    Path(data["binding"].metadata_path).write_bytes(raw(metadata))
    binding = data["binding"].model_dump()
    binding.update(task_ref=cfg.task_ref.model_dump(), metadata_sha256=digest(raw(metadata)))
    cfg = config(tmp_path, policy=policy, evolution_binding=binding)
    return cfg, data


def test_evolution_is_operator_only_and_mutually_exclusive(tmp_path):
    cfg, _ = configured(tmp_path)
    assert "evolution_binding" in cfg.task_config_optional_only_fields
    module.HarborDshTask(cfg)
    with pytest.raises(ValueError, match="mutually exclusive"):
        module.HarborDshTask(
            cfg.model_copy(
                update={"t2_fixture": module.T2FixtureBinding.model_validate(t2_binding(tmp_path, cfg.task_ref))}
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["valid", "wrong_reward", "veto", "receipt", "changed_binding"])
async def test_actual_fractional_rescore_receipt_and_audit(tmp_path, monkeypatch, variant):
    cfg, data = configured(tmp_path)
    del data["events"][8:10]
    if variant == "veto":
        del data["events"][2:4]

    async def run(self, request):
        contents = evidence(request, 1.0 if variant == "wrong_reward" else 0.25)
        trace = b"".join(raw(event) for event in data["events"])
        helper = json.loads(contents["dsh_result"])
        helper.update(
            trace_sha256=digest(trace),
            event_count=len(data["events"]),
            patches_sha256=release_patch_paths_digest(request.dsh_release),
            final_response=data["envelope"]["response"],
        )
        contents["dsh_trace"] = trace
        contents["dsh_result"] = raw(helper)
        harbor = json.loads(contents["harbor_result"])
        harbor["agent_result"]["metadata"]["dsh"].update(
            trace_sha256=digest(trace), run_sha256=digest(contents["dsh_result"]), event_count=len(data["events"])
        )
        contents["harbor_result"] = raw(harbor)
        return downloaded(request, contents)

    monkeypatch.setattr(module.HarborDshClient, "run", run)
    if variant in ("wrong_reward", "veto"):
        with pytest.raises(ValueError):
            await module.HarborDshTask(cfg).run()
        return
    result = await module.HarborDshTask(cfg).run()
    assert result.reward == 0.25
    trajectory = Trajectory(
        prompt_ids=[1],
        response_ids=[2],
        response_mask=[1],
        response_logprobs=[-0.1],
        finished=True,
        reward_score=0.25,
        extra_fields={"dsh_reward_info": build_reward_info(result)},
    )
    kwargs = dict(
        context=cfg.runner_context.model_dump(),
        artifact_root=cfg.artifact_root,
        run_id=cfg.run_id,
        worker_id=cfg.worker_id,
        task_ref=cfg.task_ref.model_dump(),
        policy=cfg.policy.model_dump(mode="json"),
        instruction=cfg.instruction,
        evolution_binding=cfg.evolution_binding.model_dump(),
    )
    assert validate_trajectories((trajectory,), **kwargs)[0] is trajectory
    if variant == "receipt":
        path = Path(result.reward_info["harbor_dsh"]["receipt_path"])
        value = json.loads(path.read_bytes())
        value["evolution_binding"]["metadata_sha256"] = digest(b"wrong")
        value["receipt_id"] = digest(raw({k: v for k, v in value.items() if k != "receipt_id"}))
        path.write_bytes(raw(value))
        with pytest.raises(TrajectoryAuditError):
            validate_trajectories((trajectory,), **kwargs)
    if variant == "changed_binding":
        Path(cfg.evolution_binding.metadata_path).write_bytes(b"changed")
        with pytest.raises(TrajectoryAuditError):
            validate_trajectories((trajectory,), **kwargs)
    kwargs.pop("evolution_binding")
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


def test_sample_cannot_override_evolution_binding(tmp_path):
    from uni_agent.tasks.config import TaskConfigResolver

    cfg, _ = configured(tmp_path)
    resolver = TaskConfigResolver(defaults_by_name={"harbor_dsh": cfg.model_dump()})
    with pytest.raises(ValueError, match="task-config-only"):
        resolver.resolve({"name": "harbor_dsh", "evolution_binding": None})


@pytest.mark.parametrize("field", ["runtime_sha256", "patch_sha256s"])
def test_deployment_binding_mismatch_rejected(tmp_path, field):
    cfg, _ = configured(tmp_path)
    data = cfg.model_dump()
    data["policy"]["dsh_release"][field] = [] if field == "patch_sha256s" else digest(b"other")
    with pytest.raises(ValueError):
        module.HarborDshTask(module.HarborDshTaskConfig.model_validate(data))
