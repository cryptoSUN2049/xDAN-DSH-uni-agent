"""CPU-only checks for strict inference configuration and durable TQ evidence."""

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
import yaml


@pytest.fixture
def cli():
    return importlib.import_module("examples.inference.parallel_infer_verl")


def _strict_flags(tmp_path):
    return [
        "--task-config",
        str(tmp_path / "tasks.yaml"),
        "--dsh-strict-audit",
        "--dsh-trace-root",
        str(tmp_path / "traces"),
        "--dsh-result-root",
        str(tmp_path / "results"),
        "--inference-evidence-path",
        str(tmp_path / "evidence.json"),
        "--log-dir",
        str(tmp_path / "logs"),
        "--result-path",
        str(tmp_path / "scores.json"),
    ]


def test_strict_config_uses_existing_admission_and_roots(cli, tmp_path):
    args = cli._parse_args(_strict_flags(tmp_path))
    cli._validate_evidence_args(args)
    config = cli.init_config(args, task_configs=[{}], served_model_name="policy")
    framework = config.actor_rollout_ref.rollout.custom.agent_framework
    runner = framework.agent_runners.task.runner_kwargs

    assert runner.report_reward is True
    assert runner.require_reward_post is True
    assert runner.dsh_trace_root == str(tmp_path / "traces")
    assert runner.dsh_result_root == str(tmp_path / "results")
    assert framework.fail_on_rollout_error is True
    assert framework.require_finished_episode is True
    assert framework.require_verifier_reward is True
    assert framework.require_trajectory_dump is True
    assert framework.use_reward_loop_worker is False
    assert framework.trajectory_postprocessor_fqn == "uni_agent.tasks.dsh.trajectory_audit.validate_trajectories"
    assert framework.trajectory_postprocessor_pass_context is True
    assert framework.trajectory_postprocessor_kwargs.trace_root == runner.dsh_trace_root
    assert framework.trajectory_postprocessor_kwargs.result_root == runner.dsh_result_root


@pytest.mark.parametrize(
    "flag",
    [
        "--dsh-trace-root",
        "--dsh-result-root",
        "--inference-evidence-path",
        "--log-dir",
        "--result-path",
    ],
)
def test_strict_paths_must_not_be_empty(cli, tmp_path, flag):
    flags = _strict_flags(tmp_path)
    flags[flags.index(flag) + 1] = ""
    with pytest.raises(ValueError, match=flag):
        cli._validate_evidence_args(cli._parse_args(flags))


@pytest.mark.parametrize("n", [0, 2])
def test_strict_mode_requires_one_session(cli, tmp_path, n):
    with pytest.raises(ValueError, match="--n=1"):
        cli._validate_evidence_args(cli._parse_args([*_strict_flags(tmp_path), "--n", str(n)]))


def test_normal_config_does_not_enable_strict_audit(cli):
    args = cli._parse_args(["--task-config", "unused.yaml", "--log-dir", ""])
    cli._validate_evidence_args(args)
    framework = cli.init_config(
        args, task_configs=[{}], served_model_name="policy"
    ).actor_rollout_ref.rollout.custom.agent_framework
    assert framework.log_dir == ""
    assert framework.agent_runners.task.runner_kwargs.require_reward_post is False
    assert "trajectory_postprocessor_fqn" not in framework


@pytest.fixture
def inference_run(cli, monkeypatch, tmp_path):
    metadata = {"task_id": "task-1", "family_id": "runtime-grounding", "scenario_id": "scenario-1", "nested": {"n": 2}}
    sample = {
        "prompt": [{"role": "user", "content": "Inspect runtime"}],
        "extra_info": {"tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": metadata}}},
    }
    config = yaml.safe_load((Path(cli.__file__).parents[1] / "dsh/evolution_task_config_v3_live.yaml").read_text())
    config[0]["agent"]["model"]["api_key"] = "secret-not-evidence"
    (tmp_path / "tasks.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["parallel_infer_verl.py", *_strict_flags(tmp_path)])
    monkeypatch.setattr(cli, "_load_samples", lambda args: [sample])
    real_init_config = cli.init_config
    monkeypatch.setattr(cli, "init_config", lambda *args, **kwargs: None)
    queue = SimpleNamespace(kv_list=lambda: {}, kv_batch_get=lambda **kwargs: pytest.fail("unexpected TQ read"))
    monkeypatch.setattr(cli, "tq", queue)
    return SimpleNamespace(
        path=tmp_path / "evidence.json",
        metadata=metadata,
        queue=queue,
        sample=sample,
        real_init_config=real_init_config,
    )


def test_preregistration_and_actual_readback_survive_success(cli, inference_run, monkeypatch):
    run = inference_run

    def generate(config, samples, uids):
        started = json.loads(run.path.read_text())
        assert started["status"] == "running"
        assert started["finished_at"] is None
        assert started["readback"] is None
        assert started["samples"] == [{"uid": uids[0], "sample_index": 0, "metadata": run.metadata}]
        # Listing includes an intermediate chain, but only the final chain is read.
        uid = uids[0]
        run.queue.kv_list = lambda: {
            "val": {
                uid: {"status": "finished"},
                f"{uid}_0_0": {"status": "success"},
                f"{uid}_0_1": {"status": "success"},
            }
        }

        def get(**kwargs):
            assert kwargs == {"keys": [f"{uid}_0_1"], "partition_id": "val", "select_fields": ["rm_scores"]}
            return {"rm_scores": torch.tensor([[0.0, 0.75]])}

        run.queue.kv_batch_get = get
        return 0.25

    monkeypatch.setattr(cli, "_generate", generate)
    cli.main()
    payload = json.loads(run.path.read_text())
    uid = payload["samples"][0]["uid"]
    assert payload["schema"] == "dsh.inference-evidence.v1"
    assert payload["status"] == "completed"
    assert payload["partition_id"] == "val"
    assert payload["global_steps"] is None
    assert payload["readback"] == {
        "final_keys": [f"{uid}_0_1"],
        "scores": [0.75],
        "uid_status": {uid: "finished"},
        "traj_keys": [f"{uid}_0_0", f"{uid}_0_1"],
    }
    assert datetime.fromisoformat(payload["started_at"]) <= datetime.fromisoformat(payload["finished_at"])
    assert "secret-not-evidence" not in run.path.read_text()
    assert run.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure_stage", ["engine", "readback"])
def test_failure_keeps_registration_without_false_readback(cli, inference_run, monkeypatch, failure_stage):
    run = inference_run

    def fail(*args, **kwargs):
        raise RuntimeError("do not persist secret-not-evidence")

    def generate(config, samples, uids):
        if failure_stage == "engine":
            fail()
        uid = uids[0]
        run.queue.kv_list = lambda: {"val": {uid: {"status": "finished"}, f"{uid}_0_0": {"status": "success"}}}
        run.queue.kv_batch_get = fail
        return 0.1

    monkeypatch.setattr(cli, "_generate", generate)
    with pytest.raises(RuntimeError):
        cli.main()
    payload = json.loads(run.path.read_text())
    assert payload["status"] == "failed"
    assert payload["error_type"] == "RuntimeError"
    assert payload["finished_at"] is not None
    assert payload["readback"] is None
    assert len(payload["samples"]) == 1
    assert "secret-not-evidence" not in run.path.read_text()


def test_strict_no_readable_trajectories_fails_without_claiming_readback(cli, inference_run, monkeypatch):
    monkeypatch.setattr(cli, "_generate", lambda *args: 0.1)
    with pytest.raises(RuntimeError, match="readback"):
        cli.main()
    payload = json.loads(inference_run.path.read_text())
    assert payload["status"] == "failed"
    assert payload["readback"] is None


def test_existing_evidence_is_not_overwritten(cli, inference_run, monkeypatch):
    inference_run.path.write_text("original evidence")
    monkeypatch.setattr(cli, "_generate", lambda *args: pytest.fail("must fail before engine"))
    with pytest.raises(FileExistsError):
        cli.main()
    assert inference_run.path.read_text() == "original evidence"


def test_evidence_cannot_alias_score_output(cli, tmp_path):
    flags = _strict_flags(tmp_path)
    flags[flags.index("--result-path") + 1] = str(tmp_path / "evidence.json")
    with pytest.raises(ValueError, match="differ"):
        cli._validate_evidence_args(cli._parse_args(flags))


@pytest.mark.parametrize("root", ["relative/path", "/tmp/../traces"])
def test_artifact_roots_reject_nonabsolute_or_traversing_paths(cli, tmp_path, root):
    flags = _strict_flags(tmp_path)
    flags[flags.index("--dsh-trace-root") + 1] = root
    with pytest.raises(ValueError, match="absolute traversal-free"):
        cli._validate_evidence_args(cli._parse_args(flags))


def test_atomic_creation_rejects_a_racing_existing_file(cli, tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("earlier run")
    with pytest.raises(FileExistsError):
        cli._write_evidence(path, {"status": "running"}, create=True)
    assert path.read_text() == "earlier run"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["evidence.json"]


def test_invalid_json_does_not_replace_existing_evidence(cli, tmp_path):
    path = tmp_path / "evidence.json"
    cli._write_evidence(path, {"status": "running"}, create=True)
    with pytest.raises(ValueError):
        cli._write_evidence(path, {"scores": [float("nan")]})
    assert json.loads(path.read_text()) == {"status": "running"}


def test_dataset_failure_records_error_type_before_engine(cli, inference_run, monkeypatch):
    def fail(args):
        raise OSError("secret-not-evidence")

    monkeypatch.setattr(cli, "_load_samples", fail)
    with pytest.raises(OSError):
        cli.main()
    payload = json.loads(inference_run.path.read_text())
    assert payload["status"] == "failed"
    assert payload["samples"] == []
    assert payload["error_type"] == "OSError"
    assert "secret-not-evidence" not in inference_run.path.read_text()


def test_strict_empty_dataset_fails_before_engine(cli, inference_run, monkeypatch):
    monkeypatch.setattr(cli, "_load_samples", lambda args: [])
    monkeypatch.setattr(cli, "_generate", lambda *args: pytest.fail("empty batch must not start engine"))
    with pytest.raises(ValueError, match="at least one sample"):
        cli.main()
    assert json.loads(inference_run.path.read_text())["status"] == "failed"


def test_registered_metadata_includes_defaults_and_is_frozen(cli):
    defaults = {"custom": {"name": "custom", "metadata": {"default": "kept", "nested": {"left": 1}}}}
    metadata = {"nested": {"right": 2}}
    sample = {"extra_info": {"tools_kwargs": {"task": {"name": "custom", "metadata": metadata}}}}
    rows = cli._registered_samples([sample], ["uid"], cli.TaskConfigResolver(defaults), strict=False)
    metadata["nested"]["right"] = 100
    assert rows == [
        {"uid": "uid", "sample_index": 0, "metadata": {"default": "kept", "nested": {"left": 1, "right": 2}}}
    ]


@pytest.mark.parametrize("metadata", [None, [], "invalid"])
def test_invalid_metadata_is_rejected(cli, metadata):
    sample = {"extra_info": {"tools_kwargs": {"task": {"name": "custom", "metadata": metadata}}}}
    with pytest.raises(ValueError, match="metadata must be an object"):
        cli._registered_samples([sample], ["uid"], cli.TaskConfigResolver(), strict=False)


def test_strict_registration_rejects_non_dsh_task(cli):
    sample = {"extra_info": {"tools_kwargs": {"task": {"name": "custom"}}}}
    with pytest.raises(ValueError, match="dsh_architecture"):
        cli._registered_samples([sample], ["uid"], cli.TaskConfigResolver(), strict=True)


def test_partial_readback_is_retained_but_not_completed(cli, inference_run, monkeypatch):
    run = inference_run
    monkeypatch.setattr(cli, "_load_samples", lambda args: [run.sample, run.sample])

    def generate(config, samples, uids):
        uid = uids[0]
        run.queue.kv_list = lambda: {
            "val": {
                uid: {"status": "finished"},
                uids[1]: {"status": "failure"},
                f"{uid}_0_0": {"status": "success"},
            }
        }
        run.queue.kv_batch_get = lambda **kwargs: {"rm_scores": torch.tensor([[0.5]])}
        return 0.1

    monkeypatch.setattr(cli, "_generate", generate)
    with pytest.raises(RuntimeError, match="readback"):
        cli.main()
    payload = json.loads(run.path.read_text())
    assert payload["status"] == "failed"
    assert payload["readback"]["scores"] == [0.5]
    assert len(payload["readback"]["final_keys"]) == 1
    assert len(payload["samples"]) == 2


def test_normal_empty_inference_can_finish_without_evidence(cli, monkeypatch, tmp_path):
    config = tmp_path / "tasks.yaml"
    config.write_text("- name: custom\n")
    monkeypatch.setattr(sys, "argv", ["parallel_infer_verl.py", "--task-config", str(config)])
    monkeypatch.setattr(cli, "_load_samples", lambda args: [])
    monkeypatch.setattr(cli, "_generate", lambda *args: pytest.fail("empty batch must not start engine"))
    cli.main()
    assert sorted(item.name for item in tmp_path.iterdir()) == ["tasks.yaml"]


@pytest.mark.parametrize("limit,expected", [(None, [1, 2]), (1, [1])])
def test_dataset_loader_preserves_parquet_selection(cli, monkeypatch, limit, expected):
    def load_dataset(kind, *, data_files, split):
        assert (kind, data_files, split) == ("parquet", "input.parquet", "train")
        return SimpleNamespace(to_list=lambda: [1, 2])

    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(load_dataset=load_dataset))
    assert cli._load_samples(SimpleNamespace(data_path="input.parquet", limit=limit)) == expected


def test_generation_preserves_real_adapter_input_contract(cli, monkeypatch):
    captured = {}
    model_client = object()
    config = SimpleNamespace(transfer_queue={"storage": "unused"})

    def create_manager(*, config):
        captured["config"] = config
        return SimpleNamespace(get_client=lambda: model_client)

    def create_adapter(*, config, llm_client):
        assert llm_client is model_client
        return SimpleNamespace(generate_sequences_and_wait=lambda prompts: captured.update(prompts=prompts))

    monkeypatch.setitem(
        sys.modules,
        "uni_agent.framework.entry",
        SimpleNamespace(
            AgentFrameworkRolloutAdapter=SimpleNamespace(create=create_adapter),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "verl.workers.rollout.llm_server",
        SimpleNamespace(
            LLMServerManager=SimpleNamespace(create=create_manager),
        ),
    )
    monkeypatch.setattr(cli.ray, "init", lambda: None)
    monkeypatch.setattr(cli, "tq", SimpleNamespace(init=lambda value: captured.update(queue_config=value)))
    sample = {
        "prompt": [{"role": "user", "content": "source"}],
        "extra_info": {"tools_kwargs": {"task": {"name": "custom"}}},
    }
    wall = cli._generate(config, [sample], ["registered-uid"])
    assert wall >= 0
    assert captured["config"] is config
    assert captured["queue_config"] == config.transfer_queue
    assert cli.tu.get(captured["prompts"], "global_steps") is None
    assert cli.tu.get(captured["prompts"], "validate") is True
    assert list(cli.tu.get(captured["prompts"], "uid")) == ["registered-uid"]


@pytest.mark.parametrize(
    "change",
    [
        {"scores": []},
        {"scores": [float("nan")]},
        {"uid_status": {"uid": "failure"}},
    ],
)
def test_strict_readback_rejects_invalid_scores_or_status(cli, change):
    read = {"final_keys": ["uid_0_0"], "scores": [1.0], "uid_status": {"uid": "finished"}, **change}
    with pytest.raises(RuntimeError, match="readback"):
        cli._require_complete_readback(read, ["uid"], 1)


def _episode_flags(tmp_path):
    import hashlib

    source = tmp_path / "source"
    source.mkdir()
    (source / "fixture.json").write_bytes(b"{}\n")
    entries = [{"path": "fixture.json", "sha256": "sha256:" + hashlib.sha256(b"{}\n").hexdigest()}]
    (tmp_path / "episode-files.json").write_text(json.dumps(entries))
    return [
        "--dsh-episode-workdir-root",
        str(tmp_path / "workspaces"),
        "--dsh-episode-source-root",
        str(source),
        "--dsh-episode-files",
        str(tmp_path / "episode-files.json"),
    ], entries


def test_operator_episode_files_are_loaded_and_passed_to_runner(cli, tmp_path):
    flags, entries = _episode_flags(tmp_path)
    args = cli._parse_args([*_strict_flags(tmp_path), *flags])
    cli._validate_evidence_args(args)
    runner = cli.init_config(
        args, task_configs=[{}], served_model_name="policy"
    ).actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs
    assert list(runner.dsh_episode_files) == entries
    assert runner.dsh_episode_workdir_root == str(tmp_path / "workspaces")
    assert runner.dsh_episode_source_root == str(tmp_path / "source")


def test_episode_config_loads_after_evidence_preregistration(cli, inference_run, monkeypatch, tmp_path):
    flags, entries = _episode_flags(tmp_path)
    monkeypatch.setattr(sys, "argv", ["parallel_infer_verl.py", *_strict_flags(tmp_path), *flags])
    monkeypatch.setattr(cli, "init_config", inference_run.real_init_config)

    def generate(config, samples, uids):
        assert json.loads(inference_run.path.read_text())["status"] == "running"
        runner = config.actor_rollout_ref.rollout.custom.agent_framework.agent_runners.task.runner_kwargs
        assert list(runner.dsh_episode_files) == entries
        uid = uids[0]
        inference_run.queue.kv_list = lambda: {
            "val": {uid: {"status": "finished"}, f"{uid}_0_0": {"status": "success"}}
        }
        inference_run.queue.kv_batch_get = lambda **kwargs: {"rm_scores": torch.tensor([[0.0]])}
        return 0.1

    monkeypatch.setattr(cli, "_generate", generate)
    cli.main()
    assert json.loads(inference_run.path.read_text())["status"] == "completed"


def test_episode_flags_are_rejected_without_strict_mode(cli, tmp_path):
    flags, _ = _episode_flags(tmp_path)
    args = cli._parse_args(["--task-config", "unused.yaml", *flags])
    with pytest.raises(ValueError, match="strict"):
        cli._validate_evidence_args(args)


@pytest.mark.parametrize("removed", [0, 2, 4])
def test_episode_flags_require_all_three_paths(cli, tmp_path, removed):
    flags, _ = _episode_flags(tmp_path)
    del flags[removed : removed + 2]
    with pytest.raises(ValueError, match="together"):
        cli._validate_evidence_args(cli._parse_args([*_strict_flags(tmp_path), *flags]))
