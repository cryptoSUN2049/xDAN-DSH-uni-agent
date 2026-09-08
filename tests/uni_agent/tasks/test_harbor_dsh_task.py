import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload, policy
from uni_agent.agents.dsh.agent import _run_key
from uni_agent.tasks.base import build_reward_info
from uni_agent.tasks.harbor_dsh import task as module
from uni_agent.tasks.harbor_dsh.client import DownloadedJob
from uni_agent.tasks.harbor_dsh.protocol import Artifact, JobManifest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def config(tmp_path, **changes):
    data = payload()
    values = {
        "instruction": "Write the answer",
        "prompt": [{"role": "user", "content": "Write the answer"}],
        "run_id": "run-1",
        "task_ref": data["task_ref"],
        "policy": policy(data),
        "worker_url": "http://127.0.0.1:47081",
        "worker_token": "test-private-token-Z" * 3,
        "worker_id": "worker-1",
        "artifact_root": str(tmp_path / "private"),
        "gateway_base_url": "http://10.0.0.2:45678/sessions/session-1/v1",
        "runner_context": {
            "partition_id": "train",
            "gateway_session_id": "session-1",
            "global_steps": 4,
            "group_uid": "group-1",
            "group_size": 4,
            "sample_index": 2,
            "session_index": 3,
        },
    }
    values.update(changes)
    return module.HarborDshTaskConfig(**values)


def evidence(request, score=1.0):
    trace = b'{"type":"turn/end","data":{"reason":"completed"}}\n'
    helper = {
        "schema": "dsh.uni-agent.dsh-run.v1",
        "dsh_session_id": "dsh-" + request.gateway_session_id,
        "trace_sha256": digest(trace),
        "event_count": 1,
        "final_response": "done",
        "profile": "sdk-minimal",
        "finish_reason": "completed",
        "trace_path": "/tmp/uni-agent-dsh/artifacts/" + _run_key(request.gateway_session_id) + "/session.jsonl",
        "trace_persisted": True,
        "patches_sha256": digest(b"[]"),
    }
    status = {
        "schema": "dsh.harbor-agent-execution.v1",
        "status": "completed",
        "finished": True,
        "finish_reason": "completed",
        "gateway_session_id": request.gateway_session_id,
        "dsh_session_id": helper["dsh_session_id"],
        "harbor_context_id": "trial-1",
        "harbor_agent_session_id": "dsh-" + request.request_sha256[7:39] + "__agent",
        "trace_sha256": digest(trace),
        "run_sha256": digest(raw(helper)),
        "event_count": 1,
        "agent_result_sha256": digest(b"not-transferred"),
    }
    harbor = {
        "id": "trial-1",
        "exception_info": None,
        "agent_result": {"metadata": {"dsh": status}},
        "verifier_result": {"rewards": {"reward": score}},
    }
    return {
        "dsh_trace": trace,
        "dsh_result": raw(helper),
        "harbor_result": raw(harbor),
        "verifier_log": b"verified\n",
        "reward": raw({"reward": score}),
    }


def downloaded(request, contents):
    artifacts = [
        Artifact(id="object-" + kind, kind=kind, size_bytes=len(content), sha256=digest(content))
        for kind, content in contents.items()
    ]
    manifest = JobManifest.model_validate(
        {
            "schema": "dsh.harbor-job-manifest.v1",
            "job_id": request.job_id,
            "request_sha256": request.request_sha256,
            "gateway_session_id": request.gateway_session_id,
            "nonce": request.nonce,
            "worker_id": "worker-1",
            "trial_id": "trial-1",
            "status": "succeeded",
            "sealed_at_unix": request.budgets.deadline_unix - 1,
            "artifacts": [entry.model_dump() for entry in artifacts],
        }
    )
    return DownloadedJob(manifest, {"object-" + kind: content for kind, content in contents.items()})


@pytest.fixture
def transport(monkeypatch):
    calls = []
    edit = {"fn": lambda request, contents: None, "score": 1.0}

    async def run(self, request):
        calls.append(request)
        contents = evidence(request, edit["score"])
        edit["fn"](request, contents)
        return downloaded(request, contents)

    monkeypatch.setattr(module.HarborDshClient, "run", run)
    return calls, edit


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [0.0, 1.0])
async def test_task_binds_verified_raw_evidence_to_new_receipt(tmp_path, transport, score):
    calls, edit = transport
    edit["score"] = score
    cfg = config(tmp_path)
    result = await module.HarborDshTask(cfg).run()
    assert result.reward == result.verifier_reward == score
    assert result.finished is True
    info = build_reward_info(result)["harbor_dsh"]
    assert info["schema"] == "dsh.harbor-verifier-receipt.v1"
    assert "dsh" not in result.reward_info
    receipt_path = Path(info["receipt_path"])
    receipt = json.loads(receipt_path.read_bytes())
    receipt_id = receipt.pop("receipt_id")
    assert receipt_id == digest(raw(receipt)) == info["receipt_sha256"]
    assert receipt["framework_context"] == cfg.runner_context.model_dump()
    assert receipt["request_sha256"] == calls[0].request_sha256
    assert receipt["run_id"] == "run-1"
    assert "eligible" not in receipt
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert receipt_path.parent.stat().st_mode & 0o777 == 0o700
    for entry in receipt["artifacts"]:
        content = (receipt_path.parent / entry["id"]).read_bytes()
        assert digest(content) == entry["sha256"]
    assert cfg.worker_token.get_secret_value().encode() not in (receipt_path.parent / "request.json").read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attack",
    [
        "trace",
        "helper-session",
        "unfinished",
        "bool-count",
        "profile",
        "trial",
        "exception",
        "status-session",
        "status-hash",
        "reward-mismatch",
        "nan",
        "duplicate-key",
    ],
)
async def test_self_consistent_manifest_cannot_admit_misaligned_evidence(tmp_path, transport, attack):
    _, edit = transport

    def mutate(request, contents):
        helper = json.loads(contents["dsh_result"])
        harbor = json.loads(contents["harbor_result"])
        status = harbor["agent_result"]["metadata"]["dsh"]
        if attack == "trace":
            contents["dsh_trace"] = b'{"type":"tool/call"}\n'
        elif attack == "helper-session":
            helper["dsh_session_id"] = "dsh-another"
        elif attack == "unfinished":
            helper["finish_reason"] = "length"
        elif attack == "bool-count":
            helper["event_count"] = True
        elif attack == "profile":
            helper["profile"] = "other"
        elif attack == "trial":
            harbor["id"] = "different-trial"
        elif attack == "exception":
            harbor["exception_info"] = {"error": "failed"}
        elif attack == "status-session":
            status["gateway_session_id"] = "another"
        elif attack == "status-hash":
            status["trace_sha256"] = digest(b"another")
        elif attack == "reward-mismatch":
            contents["reward"] = b"0\n"
        elif attack == "nan":
            contents["reward"] = b"NaN"
        elif attack == "duplicate-key":
            contents["reward"] = b'{"reward":0,"reward":1}'
        contents["dsh_result"] = raw(helper)
        status["run_sha256"] = digest(contents["dsh_result"])
        contents["harbor_result"] = raw(harbor)

    edit["fn"] = mutate
    with pytest.raises((ValueError, RuntimeError)):
        await module.HarborDshTask(config(tmp_path)).run()
    assert not list((tmp_path / "private").rglob("receipt.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.9:45678/sessions/session-1/v1",
        "http://10.0.0.2:45678/sessions/other/v1",
        "http://user:pass@10.0.0.2:45678/sessions/session-1/v1",
        "http://10.0.0.2:45678/sessions/session-1/v1?x=1",
    ],
)
async def test_runtime_route_must_match_independent_policy_and_context(tmp_path, transport, url):
    calls, _ = transport
    with pytest.raises(ValueError):
        await module.HarborDshTask(config(tmp_path, gateway_base_url=url)).run()
    assert calls == []


@pytest.mark.asyncio
async def test_second_run_is_not_implicitly_retried(tmp_path, transport):
    task = module.HarborDshTask(config(tmp_path))
    await task.run()
    with pytest.raises(RuntimeError, match="once"):
        await task.run()
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", ["symlink", "public"])
async def test_artifact_root_must_be_private_real_directory(tmp_path, transport, unsafe):
    root = tmp_path / "private"
    if unsafe == "symlink":
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        root.symlink_to(target, target_is_directory=True)
    else:
        root.mkdir(mode=0o755)
        os.chmod(root, 0o755)
    with pytest.raises((ValueError, OSError)):
        await module.HarborDshTask(config(tmp_path)).run()


def test_dynamic_identity_cannot_coerce_bool_or_unknown_fields(tmp_path):
    ctx = config(tmp_path).runner_context.model_dump()
    ctx["sample_index"] = True
    with pytest.raises(ValueError):
        config(tmp_path, runner_context=ctx)
    ctx["sample_index"] = 2
    ctx["run_id"] = "forged"
    with pytest.raises(ValueError):
        config(tmp_path, runner_context=ctx)


@pytest.mark.asyncio
async def test_prompt_must_match_operator_instruction(tmp_path, transport):
    with pytest.raises(ValueError, match="instruction"):
        await module.HarborDshTask(config(tmp_path, prompt=[{"role": "user", "content": "Different task"}])).run()
    assert transport[0] == []


def test_prompt_template_cannot_replace_untrusted_original_prompt(tmp_path):
    with pytest.raises(ValueError, match="prompt_template"):
        config(
            tmp_path,
            prompt=[{"role": "user", "content": "Different task"}],
            prompt_template=[{"role": "user", "content": "Write the answer"}],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["manifest-nonce", "manifest-worker", "raw-bytes", "extra-artifact"])
async def test_task_revalidates_client_output_before_receipt(tmp_path, monkeypatch, attack):
    async def run(self, request):
        result = downloaded(request, evidence(request))
        if attack == "manifest-nonce":
            return DownloadedJob(result.manifest.model_copy(update={"nonce": "cd" * 16}), result.artifacts)
        if attack == "manifest-worker":
            return DownloadedJob(result.manifest.model_copy(update={"worker_id": "another"}), result.artifacts)
        if attack == "raw-bytes":
            result.artifacts["object-dsh_trace"] = b"x"
        else:
            result.artifacts["unlisted"] = b"x"
        return result

    monkeypatch.setattr(module.HarborDshClient, "run", run)
    with pytest.raises(ValueError):
        await module.HarborDshTask(config(tmp_path)).run()
    assert not list((tmp_path / "private").rglob("receipt.json"))


@pytest.mark.asyncio
async def test_scalar_reward_file_zero_is_a_completed_task(tmp_path, transport):
    transport[1]["score"] = 0.0
    transport[1]["fn"] = lambda request, contents: contents.update(reward=b"0.0\n")
    result = await module.HarborDshTask(config(tmp_path)).run()
    assert result.reward == result.verifier_reward == 0.0
    assert result.finished is True


@pytest.mark.asyncio
@pytest.mark.parametrize("correct_path_digest", [True, False])
async def test_t2_patch_content_and_path_identities_are_distinct(tmp_path, transport, correct_path_digest, monkeypatch):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256, release_patch_paths_digest

    _, edits = transport
    cfg = config(tmp_path)
    value = cfg.policy.model_dump(mode="json")
    value["dsh_release"]["patch_sha256s"] = [T2_PATCH_SHA256]
    cfg = config(tmp_path, policy=value, t2_fixture=t2_binding(tmp_path, cfg.task_ref))
    from examples.dsh.capability_tasks.log_tool import verifier

    monkeypatch.setattr(verifier, "verify_trace", lambda *args, **kwargs: {"eligible": True, "passed": True})

    def edit(request, contents):
        helper = json.loads(contents["dsh_result"])
        helper["patches_sha256"] = (
            release_patch_paths_digest(request.dsh_release) if correct_path_digest else T2_PATCH_SHA256
        )
        contents["dsh_result"] = raw(helper)
        harbor = json.loads(contents["harbor_result"])
        harbor["agent_result"]["metadata"]["dsh"]["run_sha256"] = digest(contents["dsh_result"])
        contents["harbor_result"] = raw(harbor)

    edits["fn"] = edit
    if correct_path_digest:
        result = await module.HarborDshTask(cfg).run()
        assert result.finished is True
    else:
        with pytest.raises(ValueError, match="identity"):
            await module.HarborDshTask(cfg).run()


def t2_binding(tmp_path, task_ref):
    path = tmp_path / "fixture.json"
    raw_fixture = Path("examples/dsh/capability_tasks/log_tool/fixtures/dev-01.json").read_bytes()
    path.write_bytes(raw_fixture)
    return {"task_ref": task_ref.model_dump(), "fixture_path": str(path), "fixture_sha256": digest(raw_fixture)}


def test_t2_fixture_snapshot_survives_source_change(tmp_path):
    cfg = config(tmp_path)
    binding = module.T2FixtureBinding.model_validate(t2_binding(tmp_path, cfg.task_ref))
    snapshot = module.load_t2_fixture(binding, cfg.task_ref)
    Path(binding.fixture_path).write_text("tampered")
    assert digest(snapshot.raw) == binding.fixture_sha256
    with pytest.raises(ValueError, match="hash"):
        module.load_t2_fixture(binding, cfg.task_ref)


@pytest.mark.parametrize(
    "eligible,passed,reward,accept",
    [
        (True, True, 1, True),
        (True, False, 0, True),
        (False, False, 0, False),
        (True, True, 0, False),
        (True, False, 1, False),
    ],
)
def test_t2_business_rescores_instead_of_trusting_worker(tmp_path, monkeypatch, eligible, passed, reward, accept):
    from examples.dsh.capability_tasks.log_tool import verifier

    cfg = config(tmp_path)
    snapshot = module.load_t2_fixture(
        module.T2FixtureBinding.model_validate(t2_binding(tmp_path, cfg.task_ref)), cfg.task_ref
    )

    def verify(path, expected, *, fixture):
        assert path.read_bytes() == b"actual trace"
        assert expected == digest(b"actual trace")
        assert fixture["case_id"] == "log-tool-dev-01"
        return {"eligible": eligible, "passed": passed}

    monkeypatch.setattr(verifier, "verify_trace", verify)
    if accept:
        module._verify_t2_business(b"actual trace", reward, snapshot)
    else:
        with pytest.raises(ValueError):
            module._verify_t2_business(b"actual trace", reward, snapshot)


def test_t2_requires_operator_binding_and_rejects_wrong_task(tmp_path):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256

    cfg = config(tmp_path)
    policy_value = cfg.policy.model_dump(mode="json")
    policy_value["dsh_release"]["patch_sha256s"] = [T2_PATCH_SHA256]
    with pytest.raises(ValueError, match="binding"):
        module.HarborDshTask(config(tmp_path, policy=policy_value))
    binding = t2_binding(tmp_path, cfg.task_ref)
    binding["task_ref"]["version"] = "wrong"
    with pytest.raises(ValueError, match="TaskRef"):
        module.HarborDshTask(config(tmp_path, policy=policy_value, t2_fixture=binding))
    with pytest.raises(ValueError, match="binding"):
        module.HarborDshTask(config(tmp_path, t2_fixture=t2_binding(tmp_path, cfg.task_ref)))
