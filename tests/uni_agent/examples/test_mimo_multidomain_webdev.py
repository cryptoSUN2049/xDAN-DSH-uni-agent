"""CPU contracts for the native Webdev resource profile, without cloud allocation."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "prepare_webdev_contract", ROOT / "examples/mimo_multidomain_rl/prepare_webdev.py"
)
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


def harness():
    return {
        "agent": {"tools": [{"tool": name, "description": name + " original"} for name in PREPARE.TOOLS]},
        "traj_grader": {"correctness_mode": "design_group_v1", "timeout": 720},
        "environment": {"environment_class": "k8s", "env": {"LANG": "C.UTF-8"}},
    }


def row():
    instance = {
        "dataset_type": "webdev",
        "cwd": "/workspace",
        "problem_statement": "An ordinary static frontend",
        "docker_image": "webdev-rl-opensource:v2",
        "instance_id": "original-task",
        "task_id": "original-task",
    }
    return {
        "agent_name": "mimo_swe_agent",
        "prompt": [{"role": "user", "content": "unchanged source prompt"}],
        "extra_info": {"instance_json": json.dumps(instance), "index": 41},
    }


def test_environment_only_changes_preserve_native_tools_and_grader():
    original = harness()
    before = copy.deepcopy(original)
    configured = PREPARE.modal_harness(original, run_id="r22-webdev")
    assert original == before
    assert configured["agent"] == original["agent"]
    assert configured["traj_grader"] == original["traj_grader"]
    assert configured["environment"]["environment_class"] == "mimo_reference_modal.ModalEnvironment"
    assert configured["environment"]["run_id"] == "r22-webdev"
    configured["agent"]["tools"][0]["description"] = "changed"
    assert original == before


@pytest.mark.parametrize("run_id", ["", "a/b", "a b", "a" * 101])
def test_owned_run_id_rejected(run_id):
    with pytest.raises(ValueError, match="run_id"):
        PREPARE.modal_harness(harness(), run_id=run_id)


def test_changed_tool_catalogue_rejected():
    original = harness()
    original["agent"]["tools"].reverse()
    with pytest.raises(ValueError, match="catalogue"):
        PREPARE.modal_harness(original, run_id="r22")


def test_pointwise_grade_rejected():
    original = harness()
    original["traj_grader"]["correctness_mode"] = "pointwise"
    with pytest.raises(ValueError, match="group grading"):
        PREPARE.modal_harness(original, run_id="r22")


VALID_HOOK = """
class Trainer:
    def _compute_advantage(self, batch):
        if os.environ.get("WEBDEV_GRADE_MODE"):
            self._rewrite_webdev_group_rewards(batch)
        return compute_advantage_for_multi_trajectories(batch)
"""


def test_group_rewrite_precedes_advantage():
    PREPARE.assert_group_hook_before_advantage(VALID_HOOK)


@pytest.mark.parametrize(
    "source",
    [
        "class Trainer: pass",
        VALID_HOOK.replace("self._rewrite_webdev_group_rewards(batch)", "pass"),
        VALID_HOOK.replace("WEBDEV_GRADE_MODE", "UNRELATED_MODE"),
        VALID_HOOK.replace("return compute_advantage_for_multi_trajectories(batch)", "return batch"),
        """
class Trainer:
    def _compute_advantage(self, batch):
        result = compute_advantage_for_multi_trajectories(batch)
        if os.environ.get("WEBDEV_GRADE_MODE"):
            self._rewrite_webdev_group_rewards(batch)
        return result
""",
    ],
)
def test_missing_or_late_group_hook_rejected(source):
    with pytest.raises(ValueError):
        PREPARE.assert_group_hook_before_advantage(source)


def test_image_override_preserves_every_other_source_field():
    original = row()
    before = copy.deepcopy(original)
    digest = "docker.io/public/image@sha256:" + "1" * 64
    runtime, receipts = PREPARE.materialize_rows(
        [original], {"webdev-rl-opensource:v2": "public/image:v2"}, resolver=lambda _: digest
    )
    assert original == before
    assert runtime[0]["prompt"] == original["prompt"]
    assert runtime[0]["extra_info"]["index"] == 41
    source_instance = json.loads(original["extra_info"]["instance_json"])
    runtime_instance = json.loads(runtime[0]["extra_info"]["instance_json"])
    runtime_instance["docker_image"] = source_instance["docker_image"]
    assert runtime_instance == source_instance
    assert receipts[0]["changed_instance_fields"] == ["docker_image"]
    assert receipts[0]["runtime_image"] == digest


@pytest.mark.parametrize("key,value", [("dataset_type", "music"), ("cwd", "/tmp"), ("problem_statement", "")])
def test_non_native_instance_rejected(key, value):
    original = row()
    instance = json.loads(original["extra_info"]["instance_json"])
    instance[key] = value
    original["extra_info"]["instance_json"] = json.dumps(instance)
    with pytest.raises(ValueError, match="instance contract"):
        PREPARE.materialize_rows([original], {}, resolver=lambda _: "unused")


def test_agent_name_rejected():
    original = row()
    original["agent_name"] = "dsh"
    with pytest.raises(ValueError, match="agent_name"):
        PREPARE.materialize_rows([original], {}, resolver=lambda _: "unused")


def test_missing_image_mapping_rejected():
    with pytest.raises(ValueError, match="public mapping"):
        PREPARE.materialize_rows([row()], {}, resolver=lambda _: "unused")


def test_native_dispatch_alias_does_not_change_source_registry():
    original = [{"name": "webdev", "_target_": "recipes.design.agent_loop.WebdevAgentLoop"}]
    before = copy.deepcopy(original)
    result = PREPARE.loop_registry(original, Path("/owned/harness.yaml"))
    assert original == before
    assert [item["name"] for item in result] == ["webdev", "mimo_swe_agent"]
    assert all(item["_target_"] == original[0]["_target_"] for item in result)
    assert all(item["config_path"] == "/owned/harness.yaml" for item in result)


def test_unknown_registry_rejected():
    with pytest.raises(ValueError, match="loop registry"):
        PREPARE.loop_registry([], Path("/owned/harness.yaml"))


def test_digest_input_is_preserved_without_network(monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("Immutable digest must not request an image")

    monkeypatch.setattr(PREPARE.urllib.request, "urlopen", no_network)
    image = "public/image@sha256:" + "a" * 64
    assert PREPARE.dockerhub_digest(image) == "docker.io/" + image


@pytest.mark.parametrize("image", ["public/image", "public/image@sha256:abc", "x:bad tag", "https://x:y"])
def test_invalid_image_reference_rejected(image):
    with pytest.raises(ValueError):
        PREPARE.dockerhub_digest(image)


def test_public_tag_only_downloads_auth_and_heads_manifest(monkeypatch):
    requests = []

    class Response:
        headers = {"Docker-Content-Digest": "sha256:" + "b" * 64}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"token":"unit-test-token"}'

    def request(value, *, timeout):
        requests.append(value)
        assert timeout == 30
        return Response()

    monkeypatch.setattr(PREPARE.urllib.request, "urlopen", request)
    assert PREPARE.dockerhub_digest("public/image:v2").endswith("@sha256:" + "b" * 64)
    assert len(requests) == 2
    assert requests[1].method == "HEAD"
    assert requests[1].full_url.endswith("/manifests/v2")


def test_missing_judge_is_pending_without_reward():
    result = PREPARE.grader_capabilities("")
    assert result["state"] == "pending"
    assert "reward" not in result


@pytest.mark.parametrize(
    "url", ["https://u:secret@host", "file:///tmp", "https://host?token=x", "http://host#x", "https://host/api"]
)
def test_judge_url_has_no_embedded_credentials(url):
    with pytest.raises(ValueError, match="origin"):
        PREPARE.grader_capabilities(url)


def test_capability_handshake_does_not_claim_task_acceptance(monkeypatch):
    def check(url, *, need_group, timeout_s):
        assert url == "http://localhost:18088"
        assert need_group is True
        assert timeout_s == 30
        return {"runtime_gate": True, "endpoints": ["/grade_group"], "model": "test-contract-only"}

    monkeypatch.setattr(PREPARE.importlib, "import_module", lambda _: SimpleNamespace(check_capabilities=check))
    result = PREPARE.grader_capabilities("http://localhost:18088")
    assert result["state"] == "capabilities-passed-not-grade-acceptance"
    assert "reward" not in result
    assert "task_pass" not in result


def test_two_gpu_profile_preserves_group_reward_semantics():
    profile = yaml.safe_load((ROOT / "examples/mimo_multidomain_rl/recipes/webdev.yaml").read_text())
    actor = profile["actor_rollout_ref"]["actor"]
    rollout = profile["actor_rollout_ref"]["rollout"]
    assert actor["fsdp_config"]["fsdp_size"] == profile["trainer"]["n_gpus_per_node"] == 2
    assert actor["fsdp_config"]["model_dtype"] == "fp32"
    assert actor["loss_agg_mode"] == "prompt-mean"
    assert rollout["n"] == 8
    assert rollout["disable_log_stats"] is False
    assert profile["algorithm"]["norm_adv_by_std_in_grpo"] is True
    assert profile["algorithm"]["filter_groups"]["enable"] is False
    variables = profile["ray_kwargs"]["ray_init"]["runtime_env"]["env_vars"]
    assert variables["WEBDEV_GRADE_MODE"] == "train"
    assert variables["INVALID_REWARD_FOR_INFRA"] == "false"
    assert not any("KEY" in name or "TOKEN" in name for name in variables)
