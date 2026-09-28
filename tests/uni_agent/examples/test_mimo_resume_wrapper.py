"""Check the operator r5 draft's actual command without importing a GPU stack."""

import argparse
import runpy
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "docs/verl-uni-agent-harbor-opd-rl/mimo-r5-resume-wrapper.py"
CHECKPOINT = "/workspace/mimo-dsh-rl-20260928/runs/r4/rl-training/checkpoints/global_step_2"


def setup_wrapper(tmp_path, monkeypatch):
    supervisor = types.ModuleType("deployment.services.harbor_training_supervisor")
    services = types.ModuleType("deployment.services")
    services.harbor_training_supervisor = supervisor
    monkeypatch.setitem(sys.modules, "deployment.services", services)
    monkeypatch.setitem(sys.modules, "deployment.services.harbor_training_supervisor", supervisor)
    recipe = tmp_path / "examples/mimo_dsh_rl/mimo-9b-smoke.yaml"
    recipe.parent.mkdir(parents=True)
    recipe.write_text("trainer: {}\n")
    monkeypatch.chdir(tmp_path)
    return supervisor, recipe


def test_r5_main_installs_command_with_explicit_absolute_resume_target(tmp_path, monkeypatch):
    supervisor, recipe = setup_wrapper(tmp_path, monkeypatch)
    launch = "/root/mimo-private/launch-r5/launch.json"
    observed = {}

    def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--launch", type=Path, required=True)
        parser.add_argument("--manifest", type=Path, required=True)
        args = parser.parse_args()
        observed["argv"] = supervisor.training_command({}, args.launch, "/owned/python")

    supervisor.main = main
    monkeypatch.setattr(
        sys, "argv", [str(WRAPPER), "--launch", launch, "--manifest", "/root/mimo-private/supervisor-r5.json"]
    )
    runpy.run_path(str(WRAPPER), run_name="__main__")
    assert observed["argv"] == [
        "/owned/python",
        "-m",
        "examples.harbor_opd_rl.launch",
        "--mode",
        "rl",
        "--launch",
        launch,
        "--recipe-config",
        str(recipe),
        "--resume-from-path",
        CHECKPOINT,
        "--total-training-steps",
        "3",
        "--save-freq",
        "1",
    ]


def test_r5_draft_keeps_native_legacy_adapter_rejection(tmp_path, monkeypatch):
    setup_wrapper(tmp_path, monkeypatch)
    module = runpy.run_path(str(WRAPPER))
    with pytest.raises(ValueError, match="legacy adapter"):
        module["native_training_command"]({"lora_adapter": {}}, Path("launch.json"), "/owned/python")


def test_r5_draft_requires_frozen_recipe_cwd(tmp_path, monkeypatch):
    _, recipe = setup_wrapper(tmp_path, monkeypatch)
    recipe.unlink()
    module = runpy.run_path(str(WRAPPER))
    with pytest.raises(ValueError, match="frozen source root"):
        module["native_training_command"]({}, Path("launch.json"), "/owned/python")
