"""Check our budget against the pinned trainer's real loop without GPU workers.

Only the fit method is compiled: importing the full trainer requires GPU-only
packages. Model, logging and queue operations are stubs; loop/save decisions are
the actual pinned implementation, not a reimplementation of its arithmetic.
"""

import ast
import contextlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from omegaconf import OmegaConf

from examples.harbor_opd_rl.launch import finalize_training_plan
from tests.uni_agent.examples.test_harbor_opd_rl_recipe import configured


@pytest.fixture(scope="module")
def native_fit():
    root = Path(__file__).resolve().parents[3]
    source = root / "verl/verl/trainer/ppo/v1/trainer_base.py"
    module = ast.parse(source.read_text())
    trainer = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "PPOTrainer")
    fit = next(node for node in trainer.body if isinstance(node, ast.FunctionDef) and node.name == "fit")
    fit.args.args[1].annotation = None
    namespace = {
        name: MagicMock()
        for name in [
            "SkipManager",
            "Tracking",
            "ValidationGenerationsLogger",
            "DapoFilteredRewardTableLogger",
            "tq",
            "tqdm",
        ]
    }
    namespace.update(
        OmegaConf=OmegaConf,
        marked_timer=lambda *a, **k: contextlib.nullcontext(),
        pprint=lambda *a: None,
        DAPO_FILTERED_REWARD_COUNTS_KEY="dapo_counts",
    )
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fit], type_ignores=[])), str(source), "exec"), namespace)
    return namespace["fit"]


def run_native_loop(native_fit, cfg, *, rows, start_step=0):
    trainer = MagicMock()
    trainer.config = cfg
    trainer.global_steps = start_step
    trainer.steps_per_epoch = rows // cfg.data.train_batch_size
    trainer.total_training_steps = cfg.trainer.total_training_steps
    trainer._consume_sync_metrics.return_value = {}
    saved_steps = []
    trainer._save_checkpoint.side_effect = lambda: saved_steps.append(trainer.global_steps)
    native_fit(trainer, MagicMock())
    return trainer.step.call_count, saved_steps


@pytest.mark.parametrize("rows,old_steps,old_saves", [(2, 1, []), (8, 4, []), (16, 8, [5]), (20, 10, [5, 10])])
def test_final_plan_reaches_target_and_saves_last_native_step(native_fit, rows, old_steps, old_saves):
    cfg = configured("rl")
    # Retain the original regression as evidence, then exercise the actual fix.
    assert run_native_loop(native_fit, cfg, rows=rows) == (old_steps, old_saves)
    plan = finalize_training_plan(cfg, train_rows=rows, validation_rows=1)
    steps, saved = run_native_loop(native_fit, cfg, rows=rows)
    assert steps == 10
    assert saved == [5, 10]
    assert plan["steps_per_epoch"] == rows // 2


@pytest.mark.parametrize("rows", [2, 8, 16, 20])
def test_resume_uses_absolute_target_and_saves_final_step(native_fit, rows):
    cfg = configured("rl")
    finalize_training_plan(cfg, train_rows=rows, validation_rows=1)
    steps, saved = run_native_loop(native_fit, cfg, rows=rows, start_step=5)
    assert steps == 5
    assert saved == [10]


def test_single_step_is_saved_even_outside_periodic_interval(native_fit):
    cfg = configured("rl")
    cfg.trainer.total_training_steps = 1
    finalize_training_plan(cfg, train_rows=2, validation_rows=1)
    assert run_native_loop(native_fit, cfg, rows=2) == (1, [1])


@pytest.mark.parametrize("rows", [0, 1])
def test_insufficient_effective_data_fails_before_native_loop(rows):
    with pytest.raises(ValueError, match="fewer than one batch"):
        finalize_training_plan(configured("rl"), train_rows=rows, validation_rows=1)


def test_empty_validation_is_rejected():
    with pytest.raises(ValueError, match="validation"):
        finalize_training_plan(configured("rl"), train_rows=2, validation_rows=0)


@pytest.mark.parametrize("field", ["total_training_steps", "save_freq"])
@pytest.mark.parametrize("value", [0, -1, True])
def test_invalid_budget_cannot_disable_final_checkpoint(field, value):
    cfg = configured("rl")
    cfg.trainer[field] = value
    with pytest.raises(ValueError, match=field):
        finalize_training_plan(cfg, train_rows=2, validation_rows=1)
