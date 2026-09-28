"""Exercise filtering and the public launch boundary without a GPU or model weights."""

import json

import pytest

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_harbor_opd_rl_recipe import configured, prepared_launch


def local_model(tmp_path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import GPT2Config, PreTrainedTokenizerFast

    tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "[EOS]": 1, "short": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    wrapped = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token="[UNK]", eos_token="[EOS]")
    wrapped.chat_template = "{{ messages[0]['content'] }}"
    model = tmp_path / "model"
    wrapped.save_pretrained(model)
    GPT2Config(architectures=["GPT2LMHeadModel"]).save_pretrained(model)
    return model


def dataset_config(tmp_path, prompts):
    cfg = configured("rl")
    cfg.actor_rollout_ref.model.path = str(local_model(tmp_path))
    cfg.actor_rollout_ref.model.override_config = {"attn_implementation": "sdpa"}
    cfg.actor_rollout_ref.model.use_remove_padding = False
    cfg.actor_rollout_ref.rollout.checkpoint_engine.backend = "naive"
    cfg.data.max_prompt_length = 3
    cfg.data.filter_overlong_prompts_workers = 1
    for name, texts in [("train", prompts), ("val", ["short"])]:
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps({"prompt": [{"role": "user", "content": text}]}) + "\n" for text in texts))
        cfg.data[f"{name}_files"] = str(path)
    return cfg


def test_preflight_uses_native_filtered_dataset_not_raw_row_count(tmp_path):
    cfg = dataset_config(tmp_path, ["short", "short short short short"])
    with pytest.raises(ValueError, match="(?i)(effective|filtered|training).*batch"):
        launch.preflight_training(cfg)


def test_preflight_accepts_real_local_tokenizer_and_complete_batch(tmp_path):
    cfg = dataset_config(tmp_path, ["short", "short", "short short short short"])
    report = launch.preflight_training(cfg)
    assert report["train_rows"] == 2
    assert report["validation_rows"] == 1
    assert cfg.trainer.total_epochs == 10
    assert report["backend_validation"] == {
        "attention": [{"backend": "sdpa", "validation": "torch_sdpa_operator"}],
        "checkpoint_backend": "naive",
        "gpu_execution_validated": False,
    }


def cli_setup(tmp_path, monkeypatch, *options):
    prepared = prepared_launch()
    prepared["environment"]["RUN_ROOT"] = str(tmp_path / "run")
    path = tmp_path / "launch.json"
    path.write_text(json.dumps(prepared))
    monkeypatch.setenv("STUDENT_MODEL_PATH", "/models/student")
    monkeypatch.setenv("TOOL_PARSER", "hermes")
    monkeypatch.setattr("sys.argv", ["launch", "--mode", "rl", "--launch", str(path), *options])


def test_preflight_failure_never_invokes_trainer(tmp_path, monkeypatch):
    cli_setup(tmp_path, monkeypatch)

    def invalid(config):
        raise ValueError("filtered training dataset is smaller than one batch")

    monkeypatch.setattr(launch, "preflight_training", invalid, raising=False)
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("must not start Ray/GPU"))
    with pytest.raises(ValueError, match="filtered training"):
        launch.main()


def test_bounded_launch_passes_final_plan_to_native_trainer(tmp_path, monkeypatch):
    cli_setup(tmp_path, monkeypatch, "--total-training-steps", "1", "--save-freq", "1")
    observed = {}

    def preflight(config):
        return launch.finalize_training_plan(config, train_rows=2, validation_rows=1)

    def execute(command, **kwargs):
        cfg = launch.compose_config(command[4:])
        observed.update(
            steps=cfg.trainer.total_training_steps, epochs=cfg.trainer.total_epochs, save=cfg.trainer.save_freq
        )

    monkeypatch.setattr(launch, "preflight_training", preflight, raising=False)
    monkeypatch.setattr(launch.subprocess, "run", execute)
    launch.main()
    assert observed == {"steps": 1, "epochs": 1, "save": 1}
    report = json.loads((tmp_path / "run/rl-training/training-preflight.json").read_text())
    assert report["total_training_steps"] == 1


def test_explicit_resume_passes_native_restore_options_without_loading_state(tmp_path, monkeypatch, capsys):
    checkpoint = tmp_path / "global_step_5"
    cli_setup(tmp_path, monkeypatch, "--resume-from-path", str(checkpoint), "--print-config")
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("print must not launch"))
    launch.main()
    result = capsys.readouterr().out
    assert "resume_mode: resume_path" in result
    assert str(checkpoint) in result


def test_resume_requires_checkpoint_and_dataloader_state_before_launch(tmp_path, monkeypatch):
    checkpoint = tmp_path / "global_step_5"
    checkpoint.mkdir()
    cli_setup(tmp_path, monkeypatch, "--resume-from-path", str(checkpoint))
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("must reject incomplete state"))
    monkeypatch.setattr(launch, "preflight_training", lambda cfg: {}, raising=False)
    with pytest.raises(ValueError, match="(?i)(checkpoint|dataloader|actor|data.pt)"):
        launch.main()


@pytest.mark.parametrize("flag", ["--total-training-steps", "--save-freq"])
def test_nonpositive_budget_is_rejected_even_for_print(tmp_path, monkeypatch, flag):
    cli_setup(tmp_path, monkeypatch, flag, "0", "--print-config")
    with pytest.raises(SystemExit):
        launch.main()


def test_preflight_only_reports_plan_without_starting_or_writing_run(tmp_path, monkeypatch, capsys):
    cli_setup(tmp_path, monkeypatch, "--preflight-only")
    monkeypatch.setattr(
        launch, "preflight_training", lambda cfg: launch.finalize_training_plan(cfg, train_rows=2, validation_rows=1)
    )
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("preflight must not launch"))
    launch.main()
    assert json.loads(capsys.readouterr().out)["total_epochs"] == 10
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("step", [10, 11])
def test_resume_target_must_advance_beyond_checkpoint(tmp_path, monkeypatch, step):
    checkpoint = tmp_path / f"global_step_{step}"
    (checkpoint / "actor").mkdir(parents=True)
    (checkpoint / "data.pt").write_bytes(b"existence-only fixture; never loaded")
    cli_setup(tmp_path, monkeypatch, "--resume-from-path", str(checkpoint))
    monkeypatch.setattr(launch.subprocess, "run", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="exceed the checkpoint step"):
        launch.main()


def test_resume_plan_preserves_native_load_contract(tmp_path, monkeypatch):
    checkpoint = tmp_path / "global_step_5"
    (checkpoint / "actor").mkdir(parents=True)
    (checkpoint / "data.pt").write_bytes(b"existence-only fixture; never loaded")
    cli_setup(tmp_path, monkeypatch, "--resume-from-path", str(checkpoint))
    monkeypatch.setattr(
        launch, "preflight_training", lambda cfg: launch.finalize_training_plan(cfg, train_rows=2, validation_rows=1)
    )
    observed = {}

    def execute(command, **kwargs):
        cfg = launch.compose_config(command[4:])
        observed.update(mode=cfg.trainer.resume_mode, path=cfg.trainer.resume_from_path)
        assert cfg.trainer.total_epochs == 10
        assert set(cfg.actor_rollout_ref.actor.checkpoint.load_contents) == {"model", "optimizer", "extra"}

    monkeypatch.setattr(launch.subprocess, "run", execute)
    launch.main()
    assert observed == {"mode": "resume_path", "path": str(checkpoint)}


def test_unseeded_random_subset_is_rejected_before_model_loading():
    cfg = configured("rl")
    cfg.data.train_max_samples = 2
    assert cfg.data.seed is None and cfg.data.shuffle
    with pytest.raises(ValueError, match="data.seed"):
        launch.preflight_training(cfg)


def test_missing_default_flash_attention_fails_before_model_or_dataset(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(launch, "version", missing, raising=False)
    # These paths do not exist: dependency admission must happen before either
    # model/tokenizer loading or dataset filtering, not merely before Ray.
    cfg = configured("rl")
    with pytest.raises(ValueError, match="flash_attention_2.*unavailable"):
        launch.preflight_training(cfg)


def flash_dependency(tmp_path, monkeypatch, *, package_version="2.8.3", broken=False):
    import sys

    metadata = tmp_path / "flash_attn-2.8.3.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: flash-attn\nVersion: {package_version}\n")
    (tmp_path / "flash_attn.py").write_text(
        "raise ImportError('undefined symbol in CUDA extension')\n" if broken else "loaded = True\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "flash_attn", raising=False)


def test_flash_dependency_admission_does_not_require_visible_cuda(tmp_path, monkeypatch):
    import torch

    flash_dependency(tmp_path, monkeypatch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    result = launch._validate_attention_backend(configured("rl"))
    assert result == [{"backend": "flash_attention_2", "validation": "distribution_and_import"}]


@pytest.mark.parametrize(
    "package_version,broken,message", [("2.2.0", False, "unavailable"), ("2.8.3", True, "import failed")]
)
def test_incompatible_flash_dependency_is_not_admitted(tmp_path, monkeypatch, package_version, broken, message):
    flash_dependency(tmp_path, monkeypatch, package_version=package_version, broken=broken)
    with pytest.raises(ValueError, match=f"flash_attention_2.*{message}"):
        launch._validate_attention_backend(configured("rl"))


def test_sdpa_checks_torch_operator_without_requiring_flash_attention(monkeypatch):
    import torch.nn.functional as functional
    from transformers.utils import import_utils

    cfg = configured("rl")
    cfg.actor_rollout_ref.model.override_config = {"attn_implementation": "sdpa"}
    monkeypatch.setattr(import_utils, "is_flash_attn_2_available", lambda: pytest.fail("irrelevant dependency"))
    launch._validate_attention_backend(cfg)
    monkeypatch.delattr(functional, "scaled_dot_product_attention")
    with pytest.raises(ValueError, match="sdpa.*unavailable"):
        launch._validate_attention_backend(cfg)


def test_composite_attention_dependencies_and_unknown_backend(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    def missing(name):
        raise PackageNotFoundError(name)

    cfg = configured("rl")
    cfg.actor_rollout_ref.model.override_config = {
        "attn_implementation": {"text_config": "sdpa", "vision_config": "flash_attention_2"}
    }
    monkeypatch.setattr(launch, "version", missing, raising=False)
    with pytest.raises(ValueError, match="flash_attention_2.*unavailable"):
        launch._validate_attention_backend(cfg)
    cfg.actor_rollout_ref.model.override_config = {"attn_implementation": "unregistered-custom-kernel"}
    with pytest.raises(ValueError, match="Cannot validate attention backend"):
        launch._validate_attention_backend(cfg)


def test_registered_custom_attention_is_preserved(monkeypatch):
    from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS

    monkeypatch.setitem(ALL_ATTENTION_FUNCTIONS, "custom_preflight", lambda *a, **k: None)
    cfg = configured("rl")
    cfg.actor_rollout_ref.model.override_config = {"attn_implementation": "custom_preflight"}
    assert launch._validate_attention_backend(cfg) == [
        {"backend": "custom_preflight", "validation": "registered_interface_only"}
    ]


def test_checkpoint_registry_is_checked_without_instantiating_engine(monkeypatch):
    from verl.checkpoint_engine import CheckpointEngineRegistry

    monkeypatch.setattr(CheckpointEngineRegistry, "new", lambda *a, **k: pytest.fail("must not instantiate engine"))
    cfg = configured("rl")
    cfg.actor_rollout_ref.rollout.checkpoint_engine.backend = "naive"
    assert launch._validate_checkpoint_backend(cfg) == "naive"


def test_missing_checkpoint_dependency_fails_before_model_load(monkeypatch):
    from verl.checkpoint_engine import CheckpointEngineRegistry

    monkeypatch.delitem(CheckpointEngineRegistry._registry, "nccl", raising=False)
    monkeypatch.setattr(
        CheckpointEngineRegistry, "_import_errors", {"nccl_checkpoint_engine": ImportError("No module named cupy")}
    )
    cfg = configured("rl")
    cfg.actor_rollout_ref.model.override_config = {"attn_implementation": "sdpa"}
    with pytest.raises(ValueError, match="(?s)nccl.*cupy"):
        launch.preflight_training(cfg)
    assert cfg.actor_rollout_ref.rollout.checkpoint_engine.backend == "nccl"


def test_checkpoint_plugin_registration_is_imported_without_instantiation(tmp_path, monkeypatch):
    from verl.checkpoint_engine import CheckpointEngineRegistry

    monkeypatch.setattr(CheckpointEngineRegistry, "_registry", dict(CheckpointEngineRegistry._registry))
    (tmp_path / "custom_checkpoint_preflight.py").write_text(
        "from verl.checkpoint_engine import CheckpointEngineRegistry\n"
        "@CheckpointEngineRegistry.register('custom_preflight')\n"
        "class Backend:\n"
        "    def __init__(self, **kwargs):\n"
        "        raise AssertionError('must not instantiate engine')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    cfg = configured("rl")
    cfg.actor_rollout_ref.rollout.checkpoint_engine.backend = "custom_preflight"
    cfg.actor_rollout_ref.rollout.checkpoint_engine.custom_backend_module = "custom_checkpoint_preflight"
    assert launch._validate_checkpoint_backend(cfg) == "custom_preflight"
