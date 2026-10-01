"""General preparation/bootstrap contracts; never launch a GPU or sandbox."""

import importlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("mimoagent") is None:
    pytest.importorskip("mimoagent", reason="Fixed MiMo reference source is required for General contracts")

bootstrap = importlib.import_module("uni_agent.tasks.mimo_reference.general_bootstrap")
prepare = importlib.import_module("examples.mimo_multidomain_rl.prepare_general")
general = importlib.import_module("uni_agent.tasks.mimo_reference.general_environment")


@pytest.fixture
def judge_env(monkeypatch):
    for name in ("GA_JUDGE_KEY", "GA_JUDGE_URL", "GA_JUDGE_KEY_FILE", "MIMO_GENERAL_JUDGE_AUTH_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GA_JUDGE_MODEL", "public-test-model")
    monkeypatch.setenv("GA_JUDGE_API", "chat")
    monkeypatch.setenv("VERIFY_AGENT_JUDGE", "1")
    monkeypatch.setenv("VERIFY_DETERMINISTIC", "1")
    return monkeypatch


def private_auth(tmp_path, monkeypatch, mode=0o600):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"api_key": "contract-secret-not-real", "base_url": "https://judge.example/v1"}))
    path.chmod(mode)
    monkeypatch.setenv("MIMO_GENERAL_JUDGE_AUTH_FILE", str(path))
    return path


def test_private_judge_metadata_excludes_credentials(tmp_path, judge_env):
    private_auth(tmp_path, judge_env)
    report = bootstrap.configure_trusted_judge()
    assert report == {
        "authenticated": True,
        "base_url": "https://judge.example/v1",
        "model": "public-test-model",
        "api": "chat",
    }
    assert os.environ["GA_JUDGE_KEY"] == "contract-secret-not-real"
    assert "contract-secret" not in json.dumps(report)


@pytest.mark.parametrize("mode", [0o644, 0o400, 0o666])
def test_private_auth_requires_exact_permissions(tmp_path, judge_env, mode):
    private_auth(tmp_path, judge_env, mode)
    with pytest.raises(PermissionError):
        bootstrap.configure_trusted_judge()


def test_private_auth_rejects_symlink(tmp_path, judge_env):
    path = private_auth(tmp_path, judge_env)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    judge_env.setenv("MIMO_GENERAL_JUDGE_AUTH_FILE", str(link))
    with pytest.raises(ValueError):
        bootstrap.configure_trusted_judge()


@pytest.mark.parametrize(
    "field,value",
    [
        ("GA_JUDGE_URL", "https://user:password@judge.example/v1"),
        ("GA_JUDGE_URL", "https://judge.example/v1?key=bad"),
        ("GA_JUDGE_URL", "file:///secret"),
        ("GA_JUDGE_MODEL", ""),
        ("GA_JUDGE_API", "unknown"),
        ("VERIFY_AGENT_JUDGE", "0"),
        ("VERIFY_DETERMINISTIC", "0"),
    ],
)
def test_invalid_judge_contract_is_rejected(judge_env, field, value):
    judge_env.setenv("GA_JUDGE_KEY", "contract-not-real")
    judge_env.setenv("GA_JUDGE_URL", "https://judge.example/v1")
    judge_env.setenv(field, value)
    with pytest.raises(ValueError):
        bootstrap.configure_trusted_judge()


def test_no_missing_credential_is_silently_replaced(judge_env):
    with pytest.raises(RuntimeError):
        bootstrap.configure_trusted_judge()


def test_fresh_worker_installs_original_factory_routing(tmp_path, judge_env):
    private_auth(tmp_path, judge_env)
    judge_env.setenv("MIMO_GENERAL_RUN_ID", "owned-reference-contract")
    calls = []
    judge_env.setattr(general, "install_general_environment_routing", lambda **kwargs: calls.append(kwargs))
    bootstrap.install()
    assert calls == [{"run_id": "owned-reference-contract"}]
    judge_env.setenv("MIMO_GENERAL_RUN_ID", "bad/run")
    with pytest.raises(ValueError):
        bootstrap.install()


def test_modal_harness_preserves_tools_and_keeps_auth_controller_only():
    original = {
        "agent": {"tools": [{"tool": name} for name in prepare.TOOLS]},
        "environment": {"env": {"HTTP_PROXY": ""}, "sidecars": [{"name": "sidecar"}]},
    }
    result = prepare.modal_harness(original, run_id="owned-contract")
    assert result["agent"] == original["agent"]
    assert result["environment"]["sidecars"] == original["environment"]["sidecars"]
    assert result["environment"]["environment_class"].endswith("GeneralEnvironment")
    assert "run_id" not in original["environment"]
    original["environment"]["env"]["GA_JUDGE_KEY"] = "not-real"
    with pytest.raises(ValueError):
        prepare.modal_harness(original, run_id="owned-contract")


def test_general_profile_retains_original_semantics_and_no_key_in_config():
    import yaml

    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / "examples/mimo_multidomain_rl/recipes/general.yaml").read_text())
    assert config["algorithm"]["norm_adv_by_std_in_grpo"] is False
    assert config["algorithm"]["filter_groups"]["enable"] is True
    assert config["algorithm"]["length_penalty"]["enable"] is True
    assert config["algorithm"]["invalid_reward_value"] == -999
    assert config["trainer"]["v1"]["trainer_mode"] == "sync"
    assert config["actor_rollout_ref"]["actor"]["loss_agg_mode"] == "prompt-mean"
    assert config["actor_rollout_ref"]["actor"]["fsdp_config"]["model_dtype"] == "fp32"
    assert config["actor_rollout_ref"]["rollout"]["disable_log_stats"] is False
    runtime = config["ray_kwargs"]["ray_init"]["runtime_env"]
    assert runtime["worker_process_setup_hook"] == "uni_agent.tasks.mimo_reference.general_bootstrap.install"
    assert not any("KEY" in name for name in runtime["env_vars"])
