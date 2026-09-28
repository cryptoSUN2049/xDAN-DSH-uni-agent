import json

import pytest

from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload
from tests.uni_agent.tasks.test_harbor_dsh_task import downloaded, evidence
from tests.uni_agent.tasks.test_mimo_binding import binding_value
from uni_agent.tasks.harbor_dsh.mimo import MimoBinding, canonical, digest
from uni_agent.tasks.harbor_dsh.protocol import JobRequest, request_sha256
from uni_agent.tasks.harbor_dsh.task import verify_downloaded_evidence

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def fixture():
    data = payload()
    data["task_ref"]["id"] = "mimo-code-code-1"
    data["dsh_release"]["image_digest"] = "sha256:" + "b" * 64
    data["request_sha256"] = request_sha256(data)
    request = JobRequest.model_validate(data)
    binding = MimoBinding.model_validate(binding_value())
    contents = evidence(request, score=0.0)
    state = {
        "schema": "dsh.mimo-workspace-state.v1",
        "cwd": "/testbed",
        "gateway_session_id": "session-1",
        "binding_sha256": digest(canonical(binding.model_dump(mode="json", by_alias=True))),
        "base_ref": "c" * 40,
        "base_tree": "d" * 40,
        "snapshot_sha256": "sha256:" + "e" * 64,
    }
    receipt = {
        "schema": "dsh.mimo-verifier-receipt.v1",
        "status": "graded",
        "reward": 0.0,
        "base_ref": state["base_ref"],
        "snapshot_sha256": state["snapshot_sha256"],
        "gateway_session_id": "session-1",
        "verifier_returncode": 1,
    }
    contents.update(binding=canonical(state), receipt=canonical(receipt))
    return request, binding, contents


def test_valid_mimo_failure_reward_is_admitted_with_frozen_workspace_receipt():
    request, binding, contents = fixture()
    assert verify_downloaded_evidence(request, downloaded(request, contents), worker_id="worker-1", mimo=binding) == 0.0


@pytest.mark.parametrize(
    "field,value", [("base_ref", "f" * 40), ("gateway_session_id", "other"), ("status", "infra_error")]
)
def test_mimo_receipt_tampering_or_infra_failure_is_not_model_reward(field, value):
    request, binding, contents = fixture()
    receipt = json.loads(contents["receipt"])
    receipt[field] = value
    contents["receipt"] = canonical(receipt)
    with pytest.raises(ValueError):
        verify_downloaded_evidence(request, downloaded(request, contents), worker_id="worker-1", mimo=binding)


def test_old_lane_does_not_accept_extra_mimo_evidence():
    request, _, contents = fixture()
    with pytest.raises(ValueError):
        verify_downloaded_evidence(request, downloaded(request, contents), worker_id="worker-1")


@pytest.mark.asyncio
async def test_mimo_typed_result_survives_independent_trajectory_readback(tmp_path, monkeypatch):
    from tests.uni_agent.tasks.test_harbor_dsh_protocol import policy
    from tests.uni_agent.tasks.test_harbor_dsh_task import config
    from uni_agent.gateway.session import Trajectory
    from uni_agent.tasks.base import build_reward_info
    from uni_agent.tasks.harbor_dsh.client import HarborDshClient
    from uni_agent.tasks.harbor_dsh.task import HarborDshTask
    from uni_agent.tasks.harbor_dsh.trajectory_audit import validate_trajectories

    request, binding, template = fixture()
    path = tmp_path / "mimo-binding.json"
    path.write_bytes(canonical(binding.model_dump(mode="json", by_alias=True)))
    reference = {"task_ref": request.task_ref.model_dump(), "path": str(path), "sha256": digest(path.read_bytes())}
    cfg = config(
        tmp_path, task_ref=request.task_ref, policy=policy(request.model_dump(by_alias=True)), mimo_binding=reference
    )

    async def run(self, actual):
        contents = evidence(actual, score=0.0)
        contents.update(binding=template["binding"], receipt=template["receipt"])
        return downloaded(actual, contents)

    monkeypatch.setattr(HarborDshClient, "run", run)
    result = await HarborDshTask(cfg).run()
    trajectory = Trajectory(
        prompt_ids=[1, 2],
        response_ids=[3, 4, 5],
        response_mask=[1, 0, 1],
        response_logprobs=[-0.1, 0.0, -0.2],
        finished=True,
        reward_score=0.0,
        extra_fields={"dsh_reward_info": build_reward_info(result)},
    )
    original = trajectory.response_ids
    accepted = validate_trajectories(
        (trajectory,),
        task_result=result,
        context=cfg.runner_context.model_dump(),
        artifact_root=cfg.artifact_root,
        run_id=cfg.run_id,
        worker_id=cfg.worker_id,
        task_ref=cfg.task_ref,
        policy=cfg.policy,
        instruction=cfg.instruction,
        mimo_binding=reference,
    )
    assert accepted[0] is trajectory
    assert accepted[0].response_ids is original
