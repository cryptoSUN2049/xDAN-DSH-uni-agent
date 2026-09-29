"""Real dense FSDP output path, tested on CPU without loading a model."""

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import torch
import torch.utils.checkpoint
from tensordict import TensorDict

from examples.harbor_opd_rl import launch
from tests.uni_agent.examples.test_mimo_budget_recipe import ENV, prepared_budget_launch
from verl.utils import tensordict_utils as tu
from verl.utils.config import omega_conf_to_dataclass
from verl.workers.config.engine import FSDPEngineConfig
from verl.workers.engine.fsdp import transformer_impl as upstream

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def impl(tmp_path_factory):
    overlay = ROOT / "deployment/patches/verl"
    manifest = json.loads((overlay / "mimo-dense-entropy-manifest.json").read_bytes())
    entry = manifest["files"][0]
    patch = overlay / manifest["patch"]

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert sha(patch) == manifest["patch_sha256"]
    source = Path(upstream.__file__)
    source_sha = sha(source)
    assert source_sha in (entry["before_sha256"], entry["after_sha256"])
    if os.environ.get("MIMO_DENSE_ENTROPY_DIRECT") == "1":
        assert source_sha == entry["after_sha256"]
        return upstream
    root = tmp_path_factory.mktemp("mimo-entropy-overlay")
    target = root / entry["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    if source_sha == entry["before_sha256"]:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=root, check=True)
    assert sha(target) == entry["after_sha256"]
    spec = importlib.util.spec_from_file_location("verl.workers.engine.fsdp._mimo_entropy_test", target)
    module = importlib.util.module_from_spec(spec)
    # Import-time engine decorators register into a temporary registry only.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(upstream.EngineRegistry, "_engines", {})
        spec.loader.exec_module(module)
    assert sha(source) == source_sha
    return module


def run_dense(impl, logits, *, chunking=True, checkpoint=False, entropy=True, chunk_size=4):
    lengths = [logits.shape[1], logits.shape[1] - 2]
    offsets = torch.tensor([0, lengths[0], sum(lengths)])
    ids = torch.nested.nested_tensor_from_jagged(torch.zeros(sum(lengths), dtype=torch.long), offsets)
    batch = TensorDict({"input_ids": ids}, batch_size=[2])
    for key, value in {"use_remove_padding": False, "calculate_entropy": entropy}.items():
        tu.assign_non_tensor_data(batch, key, value)
    config = FSDPEngineConfig(
        entropy_checkpointing=checkpoint,
        entropy_from_logits_with_chunking=chunking,
        entropy_from_logits_chunk_size=chunk_size,
    )
    native = impl.verl_F.entropy_from_logits_with_chunking if chunking else impl.verl_F.entropy_from_logits
    helper = Mock(wraps=native)
    engine = SimpleNamespace(engine_config=config, compute_entropy_from_logits=helper)
    result = impl.FSDPEngineWithLMHead.prepare_model_outputs(
        engine,
        SimpleNamespace(logits=logits),
        {"temperature": torch.ones(2), "temperature_is_one": True, "input_ids_rmpad_rolled": ids.values()},
        batch,
        None,
    )
    return result, helper, lengths


def valid_values(dense, lengths):
    return torch.cat([row[:length] for row, length in zip(dense, lengths, strict=True)])


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("checkpoint", [False, True])
@pytest.mark.parametrize("chunk_size", [1, 4, 256])
def test_chunked_dense_entropy_output_and_gradient(impl, dtype, checkpoint, chunk_size):
    torch.manual_seed(37)
    logits = torch.randn(2, 7, 19, dtype=dtype, requires_grad=True)
    reference = logits.detach().clone().requires_grad_()
    result, helper, lengths = run_dense(impl, logits, checkpoint=checkpoint, chunk_size=chunk_size)
    helper.assert_called_once()
    assert helper.call_args.args[0].shape == (14, 19)
    assert helper.call_args.kwargs["chunk_size"] == chunk_size
    actual = result["entropy"].values()
    expected = valid_values(impl.verl_F.entropy_from_logits(reference.float()), lengths)
    assert actual.dtype == torch.float32
    torch.testing.assert_close(actual, expected)
    actual.sum().backward()
    expected.sum().backward()
    torch.testing.assert_close(logits.grad, reference.grad, rtol=0.02 if dtype == torch.bfloat16 else 1e-5, atol=1e-6)
    assert torch.count_nonzero(logits.grad[1, 5:]) == 0
    if checkpoint:
        assert helper.call_count == 2
    assert result["log_probs"].values().numel() == sum(lengths)


@pytest.mark.parametrize("checkpoint", [False, True])
@pytest.mark.parametrize("chunking", [False, True])
def test_old_log_prob_no_grad_and_entropy_disabled(impl, checkpoint, chunking):
    logits = torch.randn(2, 7, 19)
    with torch.no_grad():
        result, helper, lengths = run_dense(impl, logits, checkpoint=checkpoint, chunking=chunking)
    reference = impl.verl_F.entropy_from_logits(logits.float())
    torch.testing.assert_close(result["entropy"].values(), valid_values(reference, lengths))
    assert not result["entropy"].values().requires_grad
    if chunking:
        helper.assert_called_once()
    else:
        helper.assert_not_called()  # Keep the legacy direct native function unchanged.
    result, helper, _ = run_dense(impl, logits, checkpoint=checkpoint, chunking=chunking, entropy=False)
    assert "entropy" not in result
    helper.assert_not_called()


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
@pytest.mark.parametrize("checkpoint", [False, True])
def test_disabled_preserves_original_dtype_values_and_gradients(impl, dtype, checkpoint):
    logits = torch.randn(2, 7, 19, dtype=dtype, requires_grad=True)
    reference = logits.detach().clone().requires_grad_()
    result, helper, lengths = run_dense(impl, logits, chunking=False, checkpoint=checkpoint)
    expected = valid_values(impl.verl_F.entropy_from_logits(reference), lengths)
    actual = result["entropy"].values()
    assert actual.dtype == expected.dtype == dtype
    torch.testing.assert_close(actual, expected)
    actual.sum().backward()
    expected.sum().backward()
    torch.testing.assert_close(logits.grad, reference.grad)
    helper.assert_not_called()


def test_mimo_recipe_reaches_native_fsdp_engine_config():
    cfg = launch.compose_config(
        launch.build_overrides(
            "rl",
            prepared_budget_launch(),
            ENV,
            recipe_config=ROOT / "examples/mimo_dsh_rl/mimo-9b-budget-terminal.yaml",
        )
    )
    actor = omega_conf_to_dataclass(cfg.actor_rollout_ref.actor)
    native = actor.engine
    assert native is actor.fsdp_config
    assert isinstance(native, FSDPEngineConfig)
    assert native.entropy_from_logits_with_chunking is True
    assert native.entropy_from_logits_chunk_size == 256
    assert cfg.actor_rollout_ref.model.use_remove_padding is False
