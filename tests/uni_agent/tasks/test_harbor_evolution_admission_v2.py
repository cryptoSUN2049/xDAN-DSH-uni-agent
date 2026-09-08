import json
from pathlib import Path

import pytest

from examples.dsh.evolution_verifier_v2 import bundle_digest, source_hashes
from tests.uni_agent.tasks.test_harbor_dsh_task import digest, downloaded, evidence, raw
from tests.uni_agent.tasks.test_harbor_evolution_admission import configured
from uni_agent.agents.dsh.harbor_release import release_patch_paths_digest
from uni_agent.gateway.session import Trajectory
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.config import TaskConfigResolver
from uni_agent.tasks.dsh.trajectory_audit import TrajectoryAuditError
from uni_agent.tasks.harbor_dsh import task as module
from uni_agent.tasks.harbor_dsh.trajectory_audit import validate_trajectories


def v2_config(tmp_path):
    cfg, data = configured(tmp_path)
    metadata = json.loads(Path(cfg.evolution_binding.metadata_path).read_bytes())
    metadata.update(task_version="2", verifier_version="2", verifier_code_digest=bundle_digest())
    Path(cfg.evolution_binding.metadata_path).write_bytes(raw(metadata))
    values = cfg.model_dump()
    values["worker_token"] = cfg.worker_token
    ref = {**values["task_ref"], "version": "v2", "sha256": digest(b"v2-task")}
    binding = {
        **values["evolution_binding"],
        "kind": "evolution-v2-lifecycle-admission-v2",
        "task_ref": ref,
        "metadata_sha256": digest(raw(metadata)),
        "verifier_bundle_sha256": bundle_digest(),
        "source_sha256s": {"examples/dsh/" + k: "sha256:" + v for k, v in source_hashes().items()},
    }
    values.update(task_ref=ref, evolution_binding=None, evolution_v2_binding=binding)
    values["policy"]["task_refs"] = [ref]
    return module.HarborDshTaskConfig.model_validate(values), data


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["policy_failure", "partial", "unsafe"])
async def test_v2_task_audit_uses_same_cli_admission(tmp_path, monkeypatch, variant):
    cfg, data = v2_config(tmp_path)
    if variant == "policy_failure":
        del data["events"][2:4]
    elif variant == "partial":
        del data["events"][8:10]
    else:
        data["events"][0]["data"]["arguments"] = json.dumps({"command": "edit"})
    reward = 0.25 if variant == "partial" else 0.0

    async def run(self, request):
        contents = evidence(request, reward)
        trace = b"".join(raw(event) for event in data["events"])
        helper = json.loads(contents["dsh_result"])
        helper.update(
            trace_sha256=digest(trace),
            event_count=len(data["events"]),
            patches_sha256=release_patch_paths_digest(request.dsh_release),
            final_response=data["envelope"]["response"],
        )
        contents.update(dsh_trace=trace, dsh_result=raw(helper))
        harbor = json.loads(contents["harbor_result"])
        harbor["agent_result"]["metadata"]["dsh"].update(
            trace_sha256=digest(trace), run_sha256=digest(contents["dsh_result"]), event_count=len(data["events"])
        )
        contents["harbor_result"] = raw(harbor)
        return downloaded(request, contents)

    monkeypatch.setattr(module.HarborDshClient, "run", run)
    if variant == "unsafe":
        with pytest.raises(ValueError):
            await module.HarborDshTask(cfg).run()
        return
    result = await module.HarborDshTask(cfg).run()
    assert result.reward == reward
    receipt = json.loads(Path(result.reward_info["harbor_dsh"]["receipt_path"]).read_bytes())
    assert receipt["evolution_v2_binding"]["verifier_bundle_sha256"] == bundle_digest()
    assert "evolution_binding" not in receipt and "fresh" not in receipt
    trajectory = Trajectory(
        prompt_ids=[1],
        response_ids=[2],
        response_mask=[1],
        response_logprobs=[-0.1],
        finished=True,
        reward_score=reward,
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
        evolution_v2_binding=cfg.evolution_v2_binding.model_dump(),
    )
    assert validate_trajectories((trajectory,), **kwargs)[0] is trajectory
    kwargs["evolution_binding"] = kwargs.pop("evolution_v2_binding")
    with pytest.raises(TrajectoryAuditError):
        validate_trajectories((trajectory,), **kwargs)


def test_v2_binding_cannot_be_supplied_by_sample(tmp_path):
    cfg, _ = v2_config(tmp_path)
    resolver = TaskConfigResolver(defaults_by_name={"harbor_dsh": cfg.model_dump()})
    with pytest.raises(ValueError, match="task-config-only"):
        resolver.resolve({"name": "harbor_dsh", "evolution_v2_binding": None})
