"""Exercise pinned VERL math, without importing its GPU/TQ package initializer.

Only the two unmodified function ASTs are compiled from the locked Git tree.
DataProto, torch and core_algos are actual installed/local VERL implementations.
This is a math contract test, not an end-to-end trainer import/execution test.
"""

import ast
import hashlib
import inspect
import json
import subprocess
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pytest
import torch

from verl.protocol import DataProto
from verl.trainer.ppo import core_algos


@pytest.fixture
def pinned_math(record_property):
    repo = Path(__file__).resolve().parents[3]
    lock = json.loads((repo / "deployment/versions/g1-source-lock.json").read_text())
    pin = lock["verl_paired_gitlink"]
    record_property("verl_pin", pin)
    core_source = subprocess.check_output(
        ["git", "-C", str(repo / "verl"), "show", f"{pin}:verl/trainer/ppo/core_algos.py"], text=True
    )
    pinned_core = next(
        node
        for node in ast.parse(core_source).body
        if isinstance(node, ast.FunctionDef) and node.name == "compute_grpo_outcome_advantage"
    )
    live_core = ast.parse(inspect.getsource(core_algos.compute_grpo_outcome_advantage)).body[0]
    assert ast.dump(pinned_core) == ast.dump(live_core), f"GRPO core differs from locked VERL {pin}"
    namespace = {
        "torch": torch,
        "DataProto": DataProto,
        "core_algos": core_algos,
        "AdvantageEstimator": core_algos.AdvantageEstimator,
        "Any": Any,
        "Optional": Optional,
        "AlgoConfig": Any,
    }
    for path, name in (
        ("verl/trainer/ppo/ray_trainer.py", "compute_advantage"),
        ("verl/trainer/ppo/v1/utils.py", "compute_advantage_for_multi_trajectories"),
    ):
        source = subprocess.check_output(["git", "-C", str(repo / "verl"), "show", f"{pin}:{path}"], text=True)
        function = next(
            node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name
        )
        record_property(name + "_ast_sha256", hashlib.sha256(ast.dump(function).encode()).hexdigest())
        exec(compile(ast.Module(body=[function], type_ignores=[]), f"{pin}:{path}", "exec"), namespace)
    return namespace["compute_advantage_for_multi_trajectories"]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("normalize", [False, True])
def test_four_terminal_reader_scores_broadcast_without_segment_weighting(pinned_math, reverse, normalize):
    keys, rewards, masks, expected = [], [], [], []
    for sibling, (segments, reward) in enumerate(zip([2, 3, 5, 2], [0, 1, 0, 1], strict=True)):
        for i in range(segments):
            keys.append(f"memory_group_{sibling}_{i}")
            # Nonterminal deliberately differs: only actual last B must enter group statistics.
            rewards.append([0.0, 0.0, float(reward if i == segments - 1 else 99)])
            masks.append([1, 0, 1])
            value = reward - 0.5
            if normalize:
                value /= torch.tensor([0.0, 1.0, 0.0, 1.0]).std().item() + 1e-6
            expected.append([value, 0, value])
    if reverse:
        keys, rewards, masks, expected = (list(reversed(x)) for x in (keys, rewards, masks, expected))
    data = DataProto.from_dict(
        tensors={"token_level_rewards": torch.tensor(rewards), "response_mask": torch.tensor(masks)},
        non_tensors={"uid": np.array(["memory_group"] * len(keys))},
    )
    result = pinned_math(
        data, keys, core_algos.AdvantageEstimator.GRPO, num_repeat=4, norm_adv_by_std_in_grpo=normalize
    )
    torch.testing.assert_close(result.batch["advantages"], torch.tensor(expected))
    torch.testing.assert_close(result.batch["returns"], result.batch["advantages"])
