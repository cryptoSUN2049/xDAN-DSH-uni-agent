"""Real Gateway + registered Harbor admission through Framework and offline audit.

Only the generation backend, Worker transport, and TransferQueue are CPU fakes.
Gateway accounting, Harbor receipt verification, registration reads, admission,
Framework group handling, dump serialization, and offline audits are real.
"""

import asyncio
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from examples.harbor.audit_m2_training import audit_training
from tests.uni_agent.framework.test_generate_sequences_on_cpu import (
    _build_prompts,
    _FakeTransferQueue,
    _inline_runner_config,
)
from tests.uni_agent.gateway.test_session_multiple_chains_on_cpu import _run
from tests.uni_agent.support import FakeTokenizer
from tests.uni_agent.tasks import test_harbor_dsh_task as fixtures
from tests.uni_agent.tasks.test_harbor_budget_terminal import terminal_contents
from tests.uni_agent.tasks.test_harbor_dsh_registration import checksum
from uni_agent.framework import framework as framework_module
from uni_agent.framework.framework import GatewayAgentFramework
from uni_agent.gateway.session import GatewaySession, MessageCodec, SessionHandle
from uni_agent.tasks.harbor_dsh.client import HarborDshClient
from uni_agent.tasks.harbor_dsh.protocol import RequestPolicy
from uni_agent.tasks.harbor_dsh.task import HarborDshTask
from verl.workers.rollout.replica import TokenOutput

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
MODE = "budget-terminal-v1"
LIMITS = {"max_generated_tokens": 6, "trajectory_capacity": 1000}


def test_cpu_integration_uses_its_own_source_tree():
    from uni_agent.tasks.harbor_dsh.budget_admission import record_budget_admission
    from uni_agent.tasks.harbor_dsh.registration import validate_registered_trajectories

    root = Path(__file__).resolve().parents[3]
    for value in (
        GatewayAgentFramework,
        GatewaySession,
        HarborDshTask,
        RequestPolicy,
        record_budget_admission,
        validate_registered_trajectories,
        audit_training,
        _build_prompts,
        _FakeTransferQueue,
        _run,
        fixtures.config,
        FakeTokenizer,
        terminal_contents,
    ):
        assert Path(inspect.getfile(value)).resolve().is_relative_to(root), inspect.getfile(value)


class LiveGateway:
    def __init__(self, attack=None, member=3):
        self.sessions = {}
        self.contexts = {}
        self.finalized = {}
        self.attack, self.member = attack, member

    async def create_session(self, session_id, **kwargs):
        handle = SessionHandle(session_id, f"http://10.0.0.2:45678/sessions/{session_id}/v1")
        self.sessions[session_id] = GatewaySession(
            handle, MessageCodec(FakeTokenizer()), prompt_length=900, response_length=100, **kwargs
        )
        return handle

    async def finalize_session(self, session_id):
        trajectories = await self.sessions[session_id].finalize()
        index = self.contexts[session_id]["session_index"]
        if index == self.member:
            if self.attack == "proof":
                trajectories[0].extra_fields.pop("gateway_budget_proof")
            elif self.attack == "token":
                trajectories[0].response_ids[0] += 1
            elif self.attack == "version":
                trajectories[0].extra_fields["version_evidence_complete"] = False
        self.finalized[index] = trajectories
        return trajectories

    async def abort_session(self, session_id):
        await self.sessions[session_id].abort()


def setup_group(tmp_path, monkeypatch, *, attack=None, member=3):
    original = fixtures.config(tmp_path)
    policy = RequestPolicy.model_validate(
        {
            **original.policy.model_dump(mode="json"),
            "termination_policy": MODE,
            "budget_limits": LIMITS,
        }
    )
    cfg = fixtures.config(tmp_path, policy=policy)
    policy_json = policy.model_dump(mode="json")
    template = {k: v for k, v in policy_json.items() if k != "gateway_port"}
    registration_root = tmp_path / "registrations"
    registration_root.mkdir(mode=0o700)
    run_root = registration_root / cfg.run_id
    run_root.mkdir(mode=0o700)
    registration = run_root / "registration.json"
    registration.write_text(
        json.dumps(
            dict(
                schema="dsh.harbor-route-registration.v1",
                run_id=cfg.run_id,
                controller_id="controller-1",
                run_spec_sha256="sha256:" + "d" * 64,
                policy=policy_json,
                policy_sha256=checksum(policy_json),
                registered_at_unix=1000.0,
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    registration.chmod(0o600)
    postprocessor = dict(
        artifact_root=cfg.artifact_root,
        run_id=cfg.run_id,
        worker_id=cfg.worker_id,
        task_ref=cfg.task_ref.model_dump(mode="json"),
        policy_template=template,
        instruction=cfg.instruction,
        registration_root=str(registration_root),
        controller_id="controller-1",
        run_spec_sha256="sha256:" + "d" * 64,
        termination_policy=MODE,
        budget_limits=LIMITS,
    )
    launch = tmp_path / "launch.json"
    launch.write_text(json.dumps(dict(schema="dsh.harbor-m2-launch.v1", postprocessor=postprocessor)))
    manager = LiveGateway(attack, member)
    results = {}

    async def worker_transport(self, request):
        index = manager.contexts[request.gateway_session_id]["session_index"]
        contents = fixtures.evidence(request, score=float(index % 2))
        if index >= 2:
            terminal_contents(contents)
        return fixtures.downloaded(request, contents)

    monkeypatch.setattr(HarborDshClient, "run", worker_transport)

    async def runner(*, session, tools_kwargs, **kwargs):
        context = tools_kwargs["_runner_context"]
        manager.contexts[session.session_id] = context
        index = context["session_index"]
        if index == member and attack == "crash":
            raise RuntimeError("synthetic transport crash")
        if index == member and attack == "cancel":
            raise asyncio.CancelledError()

        class Backend:
            def __init__(self):
                self.turn = 0

            async def generate(self, *, sampling_params, **kwargs):
                self.turn += 1
                count = 2 if self.turn == 2 and index == member and attack == "call-cap" else 3
                assert count <= sampling_params["max_tokens"]
                return TokenOutput(
                    token_ids=[65 + self.turn] * count,
                    log_probs=[-0.1] * count,
                    stop_reason="length" if index >= 2 and self.turn == 2 else "completed",
                    extra_fields={"min_global_steps": 7, "max_global_steps": 7},
                )

        backend = Backend()
        live = manager.sessions[session.session_id]
        messages = [{"role": "user", "content": cfg.instruction}]
        first = await _run(live, backend, messages, max_tokens=3)
        messages += [first.assistant_msg, {"role": "tool", "tool_call_id": "call-1", "content": "tool observation"}]
        await _run(live, backend, messages, max_tokens=2 if index == member and attack == "call-cap" else 3)
        task_cfg = fixtures.config(
            tmp_path,
            policy=policy,
            runner_context=context,
            gateway_base_url=session.base_url,
        )
        result = await HarborDshTask(task_cfg).run()
        results[index] = result
        if index == member and attack == "receipt":
            path = Path(result.reward_info["harbor_dsh"]["receipt_path"])
            path.write_bytes(path.read_bytes() + b" ")
        return result

    runner_config = _inline_runner_config(runner)
    runner_config["max_concurrent_sessions"] = 1
    config = OmegaConf.create(
        {
            "actor_rollout_ref": {
                "rollout": {
                    "n": 4,
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "top_k": -1,
                    "calculate_log_probs": True,
                    "max_model_len": 1000,
                    "val_kwargs": {"n": 4, "temperature": 0.0, "top_p": 1.0, "top_k": -1},
                    "custom": {
                        "agent_framework": {
                            "log_dir": str(tmp_path / "logs"),
                            "agent_runners": {"runner": runner_config},
                            "termination_policy": MODE,
                            "max_generated_tokens_per_episode": 6,
                            "fail_on_rollout_error": True,
                            "require_finished_episode": True,
                            "require_verifier_reward": True,
                            "require_trajectory_dump": True,
                            "require_version_evidence": True,
                            "mask_unfinished_episode": False,
                            "trajectory_postprocessor_pass_context": True,
                            "trajectory_postprocessor_fqn": (
                                "uni_agent.tasks.harbor_dsh.registration.validate_registered_trajectories"
                            ),
                            "trajectory_postprocessor_kwargs": postprocessor,
                        }
                    },
                }
            }
        }
    )
    queue = _FakeTransferQueue()
    monkeypatch.setattr(framework_module, "tq", queue)
    framework = GatewayAgentFramework.from_config(config=config, gateway_manager=manager)
    train = tmp_path / "train"
    train.mkdir()
    audit_kwargs = dict(
        launch_path=launch, agent_log_dir=tmp_path / "logs", rollout_data_dir=train, train_n=4, no_validation=True
    )
    return framework, queue, manager, results, audit_kwargs


def trainer_rows(queue, audit_kwargs):
    rows = []
    for batch in queue.batch_puts:
        for index, key in enumerate(batch["keys"]):
            rows.append(dict(step=7, uid=key, score=float(batch["fields"]["rm_scores"][index].sum())))
    (audit_kwargs["rollout_data_dir"] / "7.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.asyncio
async def test_mixed_group_preserves_masks_and_passes_complete_offline_audit(tmp_path, monkeypatch):
    framework, queue, manager, results, audit_kwargs = setup_group(tmp_path, monkeypatch)
    await framework.generate_sequences(_build_prompts(count=1, global_steps=7))
    assert queue.puts[-1]["tag"]["status"] == "finished"
    keys = []
    for batch in queue.batch_puts:
        for row, key in enumerate(batch["keys"]):
            keys.append(key)
            index = int(key.split("_")[1])
            source = manager.finalized[index][0]
            mask = batch["fields"]["response_mask"][row].tolist()
            assert mask == source.response_mask
            assert 0 in mask and sum(mask) == 6
            assert batch["fields"]["loss_mask"][row].tolist() == mask
            assert float(batch["fields"]["rm_scores"][row].sum()) == float(index % 2)
            assert results[index].finished is (index < 2)
    assert sorted(keys) == [f"uid-0_{index}_0" for index in range(4)]
    dumps = sorted(audit_kwargs["agent_log_dir"].rglob("trajectory.json"))
    assert len(dumps) == 4
    for path in dumps:
        data = json.loads(path.read_text())
        index = data["session_index"]
        assert data["trajectories"][0]["finished"] is (index < 2)
    trainer_rows(queue, audit_kwargs)
    report = audit_training(**audit_kwargs)
    assert report["passed"], report
    assert len(report["groups"]) == 1
    assert sorted(report["groups"][0]["termination_kinds"]) == ["budget_exhausted"] * 2 + ["completed"] * 2
    assert report["groups"][0]["has_reward_variance"] is True
    assert report["optimizer_update_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attack,member",
    [("proof", 0), ("token", 3), ("receipt", 3), ("version", 3), ("call-cap", 3), ("crash", 3), ("cancel", 3)],
)
async def test_one_invalid_member_rejects_whole_group_without_tq(tmp_path, monkeypatch, attack, member):
    framework, queue, manager, results, _ = setup_group(tmp_path, monkeypatch, attack=attack, member=member)
    with pytest.raises(asyncio.CancelledError if attack == "cancel" else RuntimeError) as error:
        await framework.generate_sequences(_build_prompts(count=1, global_steps=7))
    if attack != "cancel":
        expected = {
            "proof": "Invalid Gateway budget proof",
            "token": "token evidence differs",
            "receipt": "not canonical JSON",
            "version": "generation version evidence",
            "call-cap": "Harbor saved evidence or runtime binding was rejected",
            "crash": "synthetic transport crash",
        }
        assert expected[attack] in str(error.value)
    if attack == "call-cap":
        # The audit intentionally redacts nested proof errors. Independently
        # establish the precise rejected input instead of relying on that text.
        proof = manager.finalized[member][0].extra_fields["gateway_budget_proof"]
        assert proof["generated_tokens"] == 5 < proof["limits"]["max_generated_tokens"]
        assert proof["exhaustion_reason"] is None
        assert proof["exhaustion_events"] == []
        assert results[member].finished is False
        assert "1 session(s) failed" in str(error.value)
    assert queue.batch_puts == []
    assert not any(item["tag"]["status"] == "finished" for item in queue.puts)


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["metadata", "npz-rehash", "missing-consumed"])
async def test_offline_matched_group_rejects_changed_dump(tmp_path, monkeypatch, attack):
    framework, queue, _, _, audit_kwargs = setup_group(tmp_path, monkeypatch)
    await framework.generate_sequences(_build_prompts(count=1, global_steps=7))
    trainer_rows(queue, audit_kwargs)
    assert audit_training(**audit_kwargs)["passed"]
    path = next(audit_kwargs["agent_log_dir"].rglob("trajectory.json"))
    data = json.loads(path.read_text())
    if attack == "metadata":
        data["trajectories"][0]["num_turns"] += 1
        path.write_text(json.dumps(data))
    elif attack == "npz-rehash":
        npz = path.parent / "trajectory.npz"
        # Appended ZIP bytes preserve all decoded arrays; only private byte binding catches this.
        raw = npz.read_bytes() + b"tampered trailing bytes"
        npz.write_bytes(raw)
        data["trajectory_npz_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        path.write_text(json.dumps(data))
    else:
        path.unlink()
    report = audit_training(**audit_kwargs)
    assert not report["passed"], report
    assert report["errors"]
    if attack != "missing-consumed":
        assert "Private dump binding mismatch" in report["errors"][0], report
