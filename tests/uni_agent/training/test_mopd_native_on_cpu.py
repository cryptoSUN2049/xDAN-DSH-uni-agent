"""Real pinned VERL loss dispatch and packed-logits backwards on CPU."""

from dataclasses import replace
from functools import partial
from types import SimpleNamespace

import pytest
import torch
from tensordict import TensorDict

from verl.trainer.distillation.losses import distillation_ppo_loss
from verl.utils import tensordict_utils as tu
from verl.workers.config import ActorConfig, DistillationConfig, DistillationLossConfig

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def configs(mode):
    kwargs = dict(
        loss_mode=mode,
        use_policy_gradient=False,
        use_task_rewards=mode == "mopd_flash_orm",
        loss_max_clamp=None,
        log_prob_min_clamp=None,
        topk=64,
    )
    if mode == "mopd_flash_orm":
        kwargs.update(mopd_orm_alpha=0.3, mopd_is_lower=0.5, mopd_is_upper=2.0)
    return (
        ActorConfig(strategy="fsdp", rollout_n=4, use_dynamic_bsz=True, loss_agg_mode="seq-mean-token-mean"),
        DistillationConfig(distillation_loss=DistillationLossConfig(**kwargs)),
    )


def data_batch():
    # Full lengths 5,7; generated masks 2 and3 tokens. Full rows include
    # a dummy final position, which is never a prediction of a response.
    rows = {
        "prompts": [torch.tensor([2, 3]), torch.tensor([4, 5, 6])],
        "responses": [torch.tensor([7, 8, 9]), torch.tensor([7, 8, 9, 10])],
        "response_mask": [torch.tensor([1, 0, 1]), torch.tensor([1, 1, 0, 1])],
        "advantages": [torch.tensor([1.0, 1.0, 1.0]), torch.tensor([-1.0, -1.0, -1.0, -1.0])],
        "rollout_log_probs": [torch.tensor([-3.0, -3.0, -3.0]), torch.tensor([-3.0, -3.0, -3.0, -3.0])],
    }
    data = TensorDict({k: tu.nested_tensor_from_tensor_list(v) for k, v in rows.items()}, batch_size=[2])
    data["input_ids"] = tu.nested_tensor_from_tensor_list([torch.arange(5), torch.arange(7)])
    for k, v in dict(dp_size=1, global_batch_size=999, global_valid_sequences=2, batch_num_tokens=5).items():
        tu.assign_non_tensor_data(data, k, v)
    return data


@pytest.mark.parametrize("mode", ["mopd_pg_sequence", "mopd_flash_orm"])
def test_native_sampled_losses_do_not_apply_ppo_ratio(mode):
    actor, distill = configs(mode)
    data = data_batch()
    current = torch.full((12,), -3.0, requires_grad=True)
    teacher = torch.full((12, 1), -2.0)
    data["teacher_logprobs"] = tu.nested_tensor_from_tensor_list([teacher[:5], teacher[5:]], ragged_idx=1)
    # Deliberately absent old_log_probs: neither new objective needs PPO anchor.
    loss, _ = distillation_ppo_loss(actor, distill, {"log_probs": current}, data)
    loss.backward()
    expected_a = 1.3 if mode == "mopd_flash_orm" else 1.0
    expected_b = 0.7 if mode == "mopd_flash_orm" else 1.0
    assert loss.item() == pytest.approx(3 * (expected_a + expected_b) / 2)
    torch.testing.assert_close(current.grad[[1, 3]], torch.full((2,), -expected_a / 4))
    torch.testing.assert_close(current.grad[[7, 8, 10]], torch.full((3,), -expected_b / 6))
    assert current.grad[[0, 2, 4, 5, 6, 9, 11]].eq(0).all()


def topk_data():
    data = data_batch()
    logits = torch.linspace(-1.0, 1.0, 12 * 80).reshape(12, 80).requires_grad_()
    q = torch.log_softmax(torch.linspace(1.0, -1.0, 80), 0)
    ids = torch.arange(64).expand(12, 64).clone()
    q = q[:64].expand(12, 64).clone()
    ids[[4, 11]] = 0  # native teacher dummy tails, not valid candidates
    data["teacher_ids"] = tu.nested_tensor_from_tensor_list([ids[:5], ids[5:]], ragged_idx=1)
    data["teacher_logprobs"] = tu.nested_tensor_from_tensor_list([q[:5], q[5:]], ragged_idx=1)
    return data, logits


def test_native_top64_dispatch_full_vocab_gradient_and_dummy_tail():
    actor, distill = configs("mopd_top64_reverse")
    data, logits = topk_data()
    outputs = distillation_ppo_loss(actor, distill, data=data, student_logits=logits[None])
    outputs = {k: v.squeeze(0) for k, v in outputs.items()}
    loss, metrics = distillation_ppo_loss(actor, distill, outputs, data)
    assert "distillation/microbatch/student_mass" in metrics
    assert "distillation/microbatch/teacher_mass" in metrics
    assert "distillation/student_mass" not in metrics
    loss.backward()
    p = logits.detach().softmax(-1)
    q = data["teacher_logprobs"].values().exp()
    ref = (p[:, :64] * (p[:, :64].log() - q.log()) - p[:, :64] + q).sum(-1)
    assert loss.item() == pytest.approx(((ref[1] + ref[3]) / 2 + (ref[7] + ref[8] + ref[10]) / 3).item() / 2)
    assert logits.grad[1, 64:].abs().sum() > 0
    assert logits.grad[[0, 2, 4, 5, 6, 9, 11]].eq(0).all()


@pytest.mark.parametrize("use_remove_padding", [True, False])
def test_fsdp_model_output_hook_thd_and_bshd(use_remove_padding):
    from verl.utils.dataset.dataset_utils import DatasetPadMode
    from verl.workers.engine.fsdp.transformer_impl import FSDPEngineWithLMHead

    actor, distill = configs("mopd_top64_reverse")
    data, flat_logits = topk_data()
    data["loss_mask"] = data["response_mask"]
    for k, v in dict(
        use_remove_padding=use_remove_padding,
        pad_mode=DatasetPadMode.NO_PADDING,
        use_fused_kernels=False,
        distillation_use_topk=True,
        distillation_only=True,
    ).items():
        tu.assign_non_tensor_data(data, k, v)
    engine = object.__new__(FSDPEngineWithLMHead)
    engine.use_ulysses_sp = False
    engine.engine_config = SimpleNamespace(entropy_checkpointing=False)
    if use_remove_padding:
        logits = flat_logits[None]
    else:
        logits = torch.stack([torch.nn.functional.pad(flat_logits[:5], (0, 0, 0, 2)), flat_logits[5:]])
    output = SimpleNamespace(logits=logits)
    args = dict(
        input_ids_rmpad_rolled=torch.arange(12),
        temperature_rmpad=torch.ones(12),
        temperature=torch.ones(2),
        temperature_is_one=True,
        pad_size=0,
    )
    result = engine.prepare_model_outputs(output, args, data, partial(distillation_ppo_loss, actor, distill))
    loss, _ = distillation_ppo_loss(actor, distill, result, data)
    loss.backward()
    assert flat_logits.grad[1].abs().sum() > 0
    assert flat_logits.grad[[0, 2, 4, 5, 6, 9, 11]].eq(0).all()


def test_native_rejects_ambiguous_config():
    with pytest.raises(ValueError, match="use_policy_gradient"):
        DistillationLossConfig(loss_mode="mopd_pg_sequence")
    with pytest.raises(ValueError, match="explicit"):
        DistillationLossConfig(
            loss_mode="mopd_flash_orm", use_policy_gradient=False, loss_max_clamp=None, log_prob_min_clamp=None
        )


@pytest.mark.asyncio
async def test_native_teacher_routing_top64_payload_enters_real_backward():
    from unittest.mock import AsyncMock

    from verl.experimental.teacher_loop.teacher_manager import AsyncTeacherLLMServerManager

    actor, distill = configs("mopd_top64_reverse")
    data, logits = topk_data()
    manager = object.__new__(AsyncTeacherLLMServerManager)
    manager.teacher_key = "teacher_domain"
    manager.distillation_loss_config = distill.distillation_loss
    manager.teacher_model_configs = {
        d: SimpleNamespace(inference=SimpleNamespace(temperature=1.0)) for d in ("swe", "terminal")
    }
    manager.teacher_client = {}
    for domain, ids, q in zip(
        ("swe", "terminal"), data["teacher_ids"].unbind(), data["teacher_logprobs"].unbind(), strict=True
    ):
        manager.teacher_client[domain] = SimpleNamespace(
            generate=AsyncMock(
                return_value=SimpleNamespace(extra_fields={"prompt_ids": ids.tolist(), "prompt_logprobs": q.tolist()})
            )
        )
    payloads = [
        await manager.compute_teacher_logprobs_single(list(range(length)), routing_key=domain)
        for domain, length in (("swe", 5), ("terminal", 7))
    ]
    data["teacher_ids"] = tu.nested_tensor_from_tensor_list([p[0] for p in payloads], ragged_idx=1)
    data["teacher_logprobs"] = tu.nested_tensor_from_tensor_list([p[1] for p in payloads], ragged_idx=1)
    outputs = distillation_ppo_loss(actor, distill, data=data, student_logits=logits[None])
    loss, _ = distillation_ppo_loss(actor, distill, {k: v.squeeze(0) for k, v in outputs.items()}, data)
    loss.backward()
    assert logits.grad[1].abs().sum() > 0
    for client in manager.teacher_client.values():
        assert client.generate.await_args.kwargs["sampling_params"]["prompt_logprobs"] == 64
    assert data["teacher_ids"].dtype == torch.int32


@pytest.mark.parametrize(
    "bad",
    ["fused", "sp", "upstream_is", "aggregation", "entropy", "reference_kl", "temperature", "missing_denominator"],
)
def test_runtime_contract_rejects_unsupported_combination(bad):
    actor, distill = configs("mopd_pg_sequence")
    data = data_batch()
    if bad == "fused":
        tu.assign_non_tensor_data(data, "use_fused_kernels", True)
    elif bad == "sp":
        tu.assign_non_tensor_data(data, "sp_size", 2)
    elif bad == "upstream_is":
        data["rollout_is_weights"] = data["advantages"]
    elif bad == "aggregation":
        actor = replace(actor, loss_agg_mode="token-mean")
    elif bad == "entropy":
        actor = replace(actor, entropy_coeff=0.01)
    elif bad == "reference_kl":
        actor = replace(actor, use_kl_loss=True)
    elif bad == "temperature":
        tu.assign_non_tensor_data(data, "temperature", 0.7)
    else:
        del data["global_valid_sequences"]
    with pytest.raises(ValueError):
        distillation_ppo_loss(actor, distill, {}, data)


def test_global_valid_sequence_count_excludes_empty_padding_and_survives_microbatch():
    from verl.trainer.distillation.mopd import valid_sequence_count
    from verl.workers.engine.utils import prepare_micro_batches

    data = data_batch()
    data["response_mask"] = tu.nested_tensor_from_tensor_list([torch.tensor([0, 0, 0]), torch.tensor([1, 1, 0, 1])])
    count = valid_sequence_count(data["response_mask"])
    assert count.item() == 1
    tu.assign_non_tensor_data(data, "global_valid_sequences", count.item())
    tu.assign_non_tensor_data(data, "use_dynamic_bsz", False)
    tu.assign_non_tensor_data(data, "micro_batch_size_per_gpu", 1)
    micros, _ = prepare_micro_batches(data)
    assert len(micros) == 2
    assert all(tu.get_non_tensor_data(m, "global_valid_sequences", None) == 1 for m in micros)


def test_actual_engine_counts_before_microbatches_and_backpropagates(monkeypatch):
    from contextlib import nullcontext

    from verl.workers.engine.fsdp import transformer_impl as native

    actor, distill = configs("mopd_pg_sequence")
    data = data_batch()
    data["response_mask"] = tu.nested_tensor_from_tensor_list([torch.tensor([0, 0, 0]), torch.tensor([1, 1, 0, 1])])
    data["loss_mask"] = data["response_mask"]
    teachers = [torch.full((5, 1), -2.0), torch.full((7, 1), -2.0)]
    data["teacher_logprobs"] = tu.nested_tensor_from_tensor_list(teachers, ragged_idx=1)
    for name, value in dict(use_dynamic_bsz=False, micro_batch_size_per_gpu=1, mopd_exact_objective=True).items():
        tu.assign_non_tensor_data(data, name, value)
    del data["global_valid_sequences"]
    # The single-rank collective/device boundary is replaced; partitioning,
    # forward_backward_batch, exact loss and backward all execute native code.
    collective_values = []
    monkeypatch.setattr(native, "get_device_id", lambda: torch.device("cpu"))
    monkeypatch.setattr(torch.distributed, "all_reduce", lambda value, **kwargs: collective_values.append(value.item()))
    engine = object.__new__(native.FSDPEngine)
    engine.ulysses_sequence_parallel_size = 1
    engine.get_data_parallel_group = lambda: None
    engine.get_data_parallel_size = lambda: 1
    engine._gradient_sync_context = lambda **kwargs: nullcontext()
    parameter = torch.tensor(-3.0, requires_grad=True)
    denominators = []

    def forward_step(micro_batch, loss_function, forward_only):
        denominators.append(tu.get_non_tensor_data(micro_batch, "global_valid_sequences", None))
        count = micro_batch["input_ids"].values().shape[0]
        loss, metrics = loss_function(model_output={"log_probs": parameter.expand(count)}, data=micro_batch)
        return loss, {"loss": loss.detach(), "metrics": metrics}

    engine.forward_step = forward_step
    native.FSDPEngine.forward_backward_batch(engine, data, partial(distillation_ppo_loss, actor, distill))
    assert collective_values == [3, 1]  # tokens and valid trajectories
    assert denominators == [1, 1]
    assert parameter.grad.item() == pytest.approx(-1.0)


def test_registered_modes_import_in_fresh_worker_process():
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from verl.workers.config import DistillationLossConfig; "
            "from verl.trainer.distillation.losses import get_distillation_loss_settings; "
            'assert get_distillation_loss_settings("mopd_top64_reverse").use_topk; '
            'assert get_distillation_loss_settings("mopd_pg_sequence").use_estimator; '
            'assert get_distillation_loss_settings("mopd_flash_orm").use_estimator',
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr


def test_tracked_patch_applies_to_pinned_source_and_matches_tested_files(tmp_path):
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    upstream = root / "verl"
    patch = root / "patches/verl/0002-mopd-objectives.patch"
    pinned = "a9f2985159536a607211dcac730d3f5d55028950"
    paths = [
        "verl/trainer/distillation/losses.py",
        "verl/trainer/ppo/ray_trainer.py",
        "verl/trainer/ppo/v1/trainer_base.py",
        "verl/workers/config/distillation.py",
        "verl/workers/engine/fsdp/transformer_impl.py",
    ]
    for name in paths:
        result = subprocess.run(["git", "show", f"{pinned}:{name}"], cwd=upstream, capture_output=True, check=True)
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.stdout)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patch)], cwd=tmp_path, check=True, capture_output=True)
    for name in [*paths, "verl/trainer/distillation/mopd.py"]:
        assert (tmp_path / name).read_bytes() == (upstream / name).read_bytes()


def test_direct_bshd_logits_match_packed_objective_and_gradients():
    actor, distill = configs("mopd_top64_reverse")
    data, packed = topk_data()
    dense = torch.stack([torch.nn.functional.pad(packed[:5], (0, 0, 0, 2)), packed[5:]])
    packed_outputs = distillation_ppo_loss(actor, distill, data=data, student_logits=packed[None])
    dense_outputs = distillation_ppo_loss(actor, distill, data=data, student_logits=dense, data_format="bshd")
    for name in packed_outputs:
        actual = torch.cat([dense_outputs[name][0, :5], dense_outputs[name][1]])
        torch.testing.assert_close(actual, packed_outputs[name].squeeze(0))
    dense_loss = dense_outputs["distillation_losses"].sum()
    packed_loss = packed_outputs["distillation_losses"].sum()
    torch.testing.assert_close(torch.autograd.grad(dense_loss, packed)[0], torch.autograd.grad(packed_loss, packed)[0])


@pytest.mark.parametrize("invalid", [0.5, -1.0, float("nan")])
def test_native_rejects_invalid_mask_before_bool_cast(invalid):
    actor, distill = configs("mopd_pg_sequence")
    data = data_batch()
    data["response_mask"] = tu.nested_tensor_from_tensor_list(
        [torch.tensor([1.0, invalid, 1.0]), torch.tensor([1.0, 1.0, 0.0, 1.0])]
    )
    with pytest.raises(ValueError, match="binary"):
        distillation_ppo_loss(actor, distill, {}, data)


def test_native_microbatch_accumulation_and_dp_average_match_global_batch():
    # Simulate DDP's gradient average explicitly while exercising the native
    # dispatcher on each independent rank/microbatch. Unequal trajectory lengths
    # must preserve the same global sequence denominator and final gradient.
    actor, distill = configs("mopd_pg_sequence")
    data = data_batch()
    data["teacher_logprobs"] = tu.nested_tensor_from_tensor_list(
        [torch.full((5, 1), -2.0), torch.full((7, 1), -1.0)], ragged_idx=1
    )
    whole_parameter = torch.tensor(-3.0, requires_grad=True)
    whole_loss, _ = distillation_ppo_loss(actor, distill, {"log_probs": whole_parameter.expand(12)}, data)
    whole_loss.backward()
    gradients = []
    for row_index in range(2):
        shard = tu.index_select_tensor_dict(data, [row_index])
        tu.assign_non_tensor_data(shard, "dp_size", 2)
        tu.assign_non_tensor_data(shard, "global_valid_sequences", 2)
        parameter = torch.tensor(-3.0, requires_grad=True)
        count = shard["input_ids"].values().shape[0]
        loss, _ = distillation_ppo_loss(actor, distill, {"log_probs": parameter.expand(count)}, shard)
        loss.backward()
        gradients.append(parameter.grad)
    torch.testing.assert_close(torch.stack(gradients).mean(), whole_parameter.grad)


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"loss_max_clamp": 5.0}, "clamps"),
        ({"log_prob_min_clamp": -20.0}, "clamps"),
        ({"distillation_loss_coef": 0.5}, "coef"),
        ({"topk": 32}, "topk=64"),
        ({"use_task_rewards": True}, "use_task_rewards=false"),
    ],
)
def test_top64_configuration_rejects_silent_objective_changes(overrides, match):
    kwargs = dict(
        loss_mode="mopd_top64_reverse",
        use_policy_gradient=False,
        use_task_rewards=False,
        loss_max_clamp=None,
        log_prob_min_clamp=None,
        topk=64,
    )
    kwargs.update(overrides)
    with pytest.raises(ValueError, match=match):
        DistillationLossConfig(**kwargs)


def test_real_synthetic_padding_template_is_inert_for_top64():
    from verl.trainer.distillation.mopd import valid_sequence_count
    from verl.trainer.ppo.padding_utils import construct_minimal_padding_template

    actor, distill = configs("mopd_top64_reverse")
    real, original_logits = topk_data()
    fields = ["prompts", "responses", "input_ids", "response_mask", "teacher_ids", "teacher_logprobs"]
    source = {name: real[name].unbind()[0] for name in fields}
    padding, _ = construct_minimal_padding_template(source, {}, eos_token_id=1)
    data = TensorDict(
        {name: tu.nested_tensor_from_tensor_list([source[name], padding[name]], ragged_idx=1) for name in fields},
        batch_size=[2],
    )
    assert data["teacher_ids"].offsets().tolist() == data["input_ids"].offsets().tolist()
    assert valid_sequence_count(data["response_mask"]).item() == 1
    tu.assign_non_tensor_data(data, "global_valid_sequences", 1)
    tu.assign_non_tensor_data(data, "dp_size", 1)
    logits = torch.cat([original_logits[:5].detach(), torch.zeros(padding["input_ids"].numel(), 80)]).requires_grad_()
    outputs = distillation_ppo_loss(actor, distill, data=data, student_logits=logits[None])
    loss, _ = distillation_ppo_loss(actor, distill, {k: v.squeeze(0) for k, v in outputs.items()}, data)
    loss.backward()
    assert logits.grad[1].abs().sum() > 0
    assert logits.grad[5:].eq(0).all()
