import hashlib
import json

import pyarrow.parquet as pq
import pytest
import yaml

from tests.uni_agent.examples.test_prepare_capability_eval import inputs as base_inputs

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    return base_inputs.__wrapped__(tmp_path, monkeypatch)


def test_context_eval_strict_task_identity_and_hashes(inputs):
    from examples.dsh.capabilities.prepare_context_eval import prepare
    from uni_agent.tasks.dsh.task import DshArchitectureTaskConfig, _task_identity

    inputs["run_root"] = inputs["output_dir"].parent / "independent-run"
    manifest = prepare(**inputs)
    output = inputs["output_dir"]
    rows = pq.read_table(output / "eval.parquet").to_pylist()
    config = yaml.safe_load((output / "task.yaml").read_text())[0]
    assert len(rows) == 4
    assert config["verifier_id"] == "dsh-context-file-evidence"
    assert config["verifier_command"][-1] == "examples.dsh.capabilities.context_verifier"
    assert config["agent"]["patches"] == []
    for row in rows:
        metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
        parsed = DshArchitectureTaskConfig.model_validate({**config, "metadata": metadata})
        identity = _task_identity(parsed)
        assert identity["split"] == "test"
        assert identity["verifier_id"] == config["verifier_id"]
        assert identity["verifier_code_digest"] == manifest["verifier_bundle"]["sha256"]
    assert manifest["context_switch_verified"] is False
    assert manifest["training"] is False
    assert not inputs["run_root"].exists()
    assert "--dsh-strict-audit" in manifest["inference_arguments"]
    for relative, digest in manifest["files"].items():
        assert "sha256:" + hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest
    assert (output / "preparation-manifest.json").exists()
    assert not (output / "run-manifest.json").exists()
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.rglob("*") if p.is_file())


def test_context_eval_refuses_reuse_and_bad_runtime(inputs):
    from examples.dsh.capabilities.prepare_context_eval import prepare

    inputs["run_root"] = inputs["output_dir"].parent / "run"
    original = inputs["environment_digest"]
    inputs["environment_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="runtime"):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()
    inputs["environment_digest"] = original
    prepare(**inputs)
    with pytest.raises(ValueError, match="new private"):
        prepare(**inputs)


def test_context_eval_run_must_be_independent(inputs):
    from examples.dsh.capabilities.prepare_context_eval import prepare

    inputs["run_root"] = inputs["output_dir"] / "run"
    with pytest.raises(ValueError, match="independent"):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()


def test_context_eval_wrong_package_version(inputs, monkeypatch):
    import subprocess

    from examples.dsh.capabilities.prepare_context_eval import prepare

    inputs["run_root"] = inputs["output_dir"].parent / "run"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 0, json.dumps({"path": str(inputs["runtime_executable"]), "sdk": "0.1.2a1", "runtime": "0.1.2a1"}), ""
        ),
    )
    with pytest.raises(ValueError, match="0.1.3a2"):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()


def test_context_eval_real_strict_parser_and_resolver(inputs):
    from examples.dsh.capabilities.prepare_context_eval import prepare
    from examples.inference import parallel_infer_verl as cli

    inputs["run_root"] = inputs["output_dir"].parent / "run"
    manifest = prepare(**inputs)
    args = cli._parse_args(manifest["inference_arguments"])
    cli._validate_evidence_args(args)
    configs = yaml.safe_load((inputs["output_dir"] / "task.yaml").read_text())
    rows = pq.read_table(inputs["output_dir"] / "eval.parquet").to_pylist()
    registered = cli._registered_samples(
        rows, [row["uid"] for row in rows], cli.TaskConfigResolver.from_file(args.task_config), strict=True
    )
    assert len(registered) == 4
    assert all(row["metadata"]["verifier_id"] == "dsh-context-file-evidence" for row in registered)
    config = cli.init_config(args, task_configs=configs, served_model_name="operator-model")
    framework = config.actor_rollout_ref.rollout.custom.agent_framework
    assert framework.require_verifier_reward is True
    assert framework.require_finished_episode is True
    assert framework.fail_on_rollout_error is True
    assert args.n == 1
