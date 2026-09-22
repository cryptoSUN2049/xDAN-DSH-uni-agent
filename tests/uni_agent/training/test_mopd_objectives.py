import math

import pytest
import torch

from uni_agent.training.mopd_objectives import (
    corrected_topk_reverse,
    flash_orm_token_loss,
    pg_sequence_token_loss,
    sequence_mean,
)


def test_sequence_equal_weight_and_masked_gradients():
    loss = torch.ones(2, 10000, requires_grad=True)
    mask = torch.ones_like(loss)
    mask[0, 1000:] = 0
    result = sequence_mean(loss, mask)
    result.backward()
    torch.testing.assert_close(loss.grad.sum(1), torch.tensor([0.5, 0.5]))
    assert loss.grad[0, 1000:].count_nonzero() == 0


def test_microbatch_and_dp_partition_preserve_value_and_gradient():
    x = torch.tensor([[2.0, 5.0, 7.0], [3.0, 4.0, 9.0], [8.0, 2.0, 1.0], [0.0, 0.0, 0.0]], requires_grad=True)
    mask = torch.tensor([[1, 1, 1], [1, 0, 0], [1, 1, 0], [0, 0, 0]])
    whole = sequence_mean(x, mask)
    parts = sum(sequence_mean(x[i : i + 1], mask[i : i + 1], global_num_sequences=3, dp_size=2) for i in range(4)) / 2
    torch.testing.assert_close(whole, parts)
    torch.testing.assert_close(torch.autograd.grad(whole, x)[0], torch.autograd.grad(parts, x)[0])


def test_empty_local_microbatch_requires_global_denominator():
    x = torch.ones(1, 2, requires_grad=True)
    mask = torch.zeros_like(x)
    with pytest.raises(ValueError, match="valid trajectory"):
        sequence_mean(x, mask)
    sequence_mean(x, mask, global_num_sequences=2).backward()
    assert x.grad.count_nonzero() == 0


def test_pg_matches_detached_clipped_reference():
    p = torch.tensor([[-2.0, -10.0, -0.2]], dtype=torch.float64, requires_grad=True)
    q = torch.tensor([[-1.0, -1.0, -10.0]], dtype=torch.float64, requires_grad=True)
    mask = torch.tensor([[1, 1, 0]])
    losses, metrics = pg_sequence_token_loss(p, q, mask)
    reference = -p * torch.tensor([[1.0, 5.0, 0.0]], dtype=torch.float64)
    torch.testing.assert_close(losses, reference)
    losses.sum().backward()
    torch.testing.assert_close(p.grad, torch.tensor([[-1.0, -5.0, 0.0]], dtype=torch.float64))
    assert q.grad is None
    assert not metrics["teacher_advantage"].requires_grad


@pytest.mark.parametrize("k", [1, 3, 5])
def test_topk_float64_reference_and_gradients(k):
    torch.manual_seed(1)
    z = torch.randn(2, 3, 5, dtype=torch.float64, requires_grad=True)
    qlog = torch.randn_like(z).log_softmax(-1).detach().requires_grad_()
    q, ids = qlog.topk(k, -1)
    mask = torch.tensor([[1, 0, 1], [1, 1, 0]])
    loss, metrics = corrected_topk_reverse(z, ids, q, mask, chunk_size=2)
    rows = []
    for i in range(2):
        terms = []
        for t in range(3):
            probs = z[i, t].softmax(-1)
            term = sum(
                probs[v] * (probs[v].log() - qlog[i, t, v].detach()) - probs[v] + qlog[i, t, v].detach().exp()
                for v in ids[i, t]
            )
            terms.append(term * mask[i, t])
        rows.append(torch.stack(terms))
    ref = torch.stack(rows)
    torch.testing.assert_close(loss, ref, atol=1e-12, rtol=1e-12)
    torch.testing.assert_close(
        torch.autograd.grad(loss.sum(), z, retain_graph=True)[0],
        torch.autograd.grad(ref.sum(), z)[0],
        atol=1e-12,
        rtol=1e-12,
    )
    loss.sum().backward()
    assert qlog.grad is None
    assert not metrics["student_mass"].requires_grad
    if k == 1:
        assert z.grad[0, 0].count_nonzero() == 5


def test_full_vocab_is_reverse_kl_and_equal_distribution_zero():
    z = torch.tensor([[[1.0, 0.0, -1.0]]], dtype=torch.float64, requires_grad=True)
    qlog = torch.tensor([[[0.0, 1.0, 0.0]]], dtype=torch.float64).log_softmax(-1)
    ids = torch.tensor([[[0, 1, 2]]])
    loss, _ = corrected_topk_reverse(z, ids, qlog)
    reverse = (z.softmax(-1) * (z.log_softmax(-1) - qlog)).sum(-1)
    torch.testing.assert_close(loss, reverse)
    same, _ = corrected_topk_reverse(z, ids, z.detach().log_softmax(-1))
    torch.testing.assert_close(same, torch.zeros_like(same), atol=1e-15, rtol=0)
    torch.testing.assert_close(torch.autograd.grad(same.sum(), z)[0], torch.zeros_like(z), atol=1e-15, rtol=0)


def test_topk_gradcheck_and_flatten_layout_equivalence():
    z = torch.tensor([[[1.0, 0.0, -2.0], [0.0, 1.0, -1.0]]], dtype=torch.float64, requires_grad=True)
    ids = torch.tensor([[[0, 1], [1, 2]]])
    q = torch.tensor([[[-0.7, -1.0], [-0.3, -2.0]]], dtype=torch.float64)
    assert torch.autograd.gradcheck(lambda v: corrected_topk_reverse(v, ids, q)[0], (z,))
    actual, _ = corrected_topk_reverse(z, ids, q)
    flat, _ = corrected_topk_reverse(z.reshape(-1, 3), ids.reshape(-1, 2), q.reshape(-1, 2))
    torch.testing.assert_close(actual.flatten(), flat)


def test_topk_ignores_invalid_dummy_positions_and_preserves_zero_grad():
    z = torch.tensor([[[1.0, 0.0, 2.0], [float("nan"), 1.0, 2.0]]], requires_grad=True)
    ids = torch.tensor([[[0, 1], [99, 99]]])
    q = torch.tensor([[[-1.0, -2.0], [float("nan"), float("inf")]]])
    loss, _ = corrected_topk_reverse(z, ids, q, torch.tensor([[1, 0]]))
    assert torch.isfinite(loss).all()
    loss.sum().backward()
    assert z.grad[0, 1].count_nonzero() == 0


@pytest.mark.parametrize("problem", ["duplicate", "out_of_range", "nonfinite", "shape"])
def test_topk_rejects_invalid_active_candidates(problem):
    z = torch.zeros(1, 1, 3)
    ids = torch.tensor([[[0, 1]]])
    q = torch.tensor([[[-1.0, -2.0]]])
    if problem == "duplicate":
        ids[0, 0, 1] = 0
    elif problem == "out_of_range":
        ids[0, 0, 1] = 3
    elif problem == "nonfinite":
        q[0, 0, 0] = float("nan")
    else:
        q = q[..., :1]
    with pytest.raises(ValueError):
        corrected_topk_reverse(z, ids, q)


def test_low_precision_topk_computes_fp32():
    loss, _ = corrected_topk_reverse(
        torch.zeros(1, 3, dtype=torch.bfloat16),
        torch.tensor([[0, 1]]),
        torch.tensor([[-1.0, -2.0]], dtype=torch.bfloat16),
    )
    assert loss.dtype == torch.float32


def test_flash_boundaries_rejection_denominator_and_detached_gradient():
    ratios = torch.tensor([[0.5, 2.0, 0.49, 2.01]], dtype=torch.float64)
    p = torch.full((1, 4), -3.0, dtype=torch.float64, requires_grad=True)
    q = torch.full_like(p, -2.0, requires_grad=True)
    mu = (p.detach() - ratios.log()).requires_grad_()
    orm = torch.tensor([2.0], dtype=torch.float64, requires_grad=True)
    loss, metrics = flash_orm_token_loss(p, q, mu, orm, torch.ones_like(p), alpha=0.5, is_lower=0.5, is_upper=2.0)
    reduced = sequence_mean(loss, torch.ones_like(p))
    torch.testing.assert_close(reduced, torch.tensor(3.75, dtype=torch.float64))
    reduced.backward()
    torch.testing.assert_close(p.grad, torch.tensor([[-0.25, -1.0, 0.0, 0.0]], dtype=torch.float64))
    assert q.grad is None and mu.grad is None and orm.grad is None
    torch.testing.assert_close(metrics["is_weight"], torch.tensor([[0.5, 2.0, 0.0, 0.0]], dtype=torch.float64))


@pytest.mark.parametrize("alpha", [0.0, 0.7])
def test_flash_reduces_to_teacher_or_orm(alpha):
    p = torch.tensor([[-2.0, -3.0]], requires_grad=True)
    q = p.detach() if alpha else p.detach() + 0.3
    orm = torch.tensor([2.0])
    loss, _ = flash_orm_token_loss(p, q, p.detach(), orm, torch.ones_like(p), alpha=alpha, is_lower=0.5, is_upper=2.0)
    expected_adv = torch.full_like(p, 2.0 * alpha if alpha else 0.3)
    torch.testing.assert_close(loss, -expected_adv * p)


def test_flash_all_rejected_finite_zero_gradient_even_ratio_overflow():
    p = torch.tensor([[-1.0, -1000.0]], requires_grad=True)
    loss, _ = flash_orm_token_loss(
        p,
        torch.full_like(p, -2.0),
        torch.tensor([[-1000.0, -1.0]]),
        torch.tensor([0.0]),
        torch.ones_like(p),
        alpha=1.0,
        is_lower=0.5,
        is_upper=2.0,
    )
    assert torch.equal(loss, torch.zeros_like(loss))
    loss.sum().backward()
    assert p.grad.count_nonzero() == 0


@pytest.mark.parametrize(
    "kwargs", [{"alpha": -1.0}, {"alpha": math.inf}, {"is_lower": 0.0}, {"is_lower": 1.1}, {"is_upper": 0.9}]
)
def test_flash_rejects_invalid_hyperparameters(kwargs):
    params = dict(alpha=1.0, is_lower=0.5, is_upper=2.0)
    params.update(kwargs)
    x = torch.full((1, 2), -1.0)
    with pytest.raises(ValueError):
        flash_orm_token_loss(x, x, x, torch.zeros(1), torch.ones_like(x), **params)


def test_nonfinite_active_logprob_rejected_but_padding_sanitized():
    p = torch.tensor([[-1.0, float("nan")]], requires_grad=True)
    q = torch.tensor([[-2.0, float("nan")]])
    mask = torch.tensor([[1, 0]])
    loss, _ = pg_sequence_token_loss(p, q, mask)
    loss.sum().backward()
    assert torch.isfinite(p.grad).all() and p.grad[0, 1] == 0
    with pytest.raises(ValueError, match="finite"):
        pg_sequence_token_loss(p, q, torch.ones_like(mask))


@pytest.mark.parametrize("mask", [torch.tensor([[0.5, 1.0]]), torch.tensor([[float("nan"), 1.0]]), torch.ones(2)])
def test_invalid_masks_rejected(mask):
    with pytest.raises(ValueError):
        sequence_mean(torch.ones(1, 2), mask)


def test_topk_entire_padding_microbatch_keeps_zero_backward_graph():
    logits = torch.full((2, 3, 5), float("nan"), requires_grad=True)
    ids = torch.full((2, 3, 2), -1)
    q = torch.full((2, 3, 2), float("nan"))
    mask = torch.zeros(2, 3)
    loss, metrics = corrected_topk_reverse(logits, ids, q, mask)
    sequence_mean(loss, mask, global_num_sequences=4, dp_size=2).backward()
    assert torch.equal(loss, torch.zeros_like(loss))
    assert logits.grad.count_nonzero() == 0
    assert all(not value.requires_grad for value in metrics.values())


def test_flash_padding_nan_and_per_token_orm_masking():
    p = torch.tensor([[-1.0, float("nan")]], requires_grad=True)
    q = torch.tensor([[-2.0, float("nan")]], requires_grad=True)
    mu = p.detach().clone().requires_grad_()
    orm = torch.tensor([[2.0, float("nan")]], requires_grad=True)
    loss, metrics = flash_orm_token_loss(p, q, mu, orm, torch.tensor([[1, 0]]), alpha=1.0, is_lower=0.5, is_upper=2.0)
    torch.testing.assert_close(loss, torch.tensor([[1.0, 0.0]]))
    loss.sum().backward()
    torch.testing.assert_close(p.grad, torch.tensor([[-1.0, 0.0]]))
    assert q.grad is None and mu.grad is None and orm.grad is None
    assert all(not value.requires_grad for value in metrics.values())


def test_flash_does_not_clamp_teacher_advantage_like_pg():
    p = torch.tensor([[-20.0]], requires_grad=True)
    loss, _ = flash_orm_token_loss(
        p,
        torch.tensor([[-1.0]]),
        p.detach(),
        torch.zeros(1),
        torch.ones_like(p),
        alpha=0.0,
        is_lower=0.5,
        is_upper=2.0,
    )
    loss.sum().backward()
    torch.testing.assert_close(p.grad, torch.tensor([[-19.0]]))


def test_chunk_size_does_not_change_topk_value_or_gradient():
    torch.manual_seed(3)
    z = torch.randn(2, 4, 11, dtype=torch.float64, requires_grad=True)
    q, ids = torch.randn_like(z).log_softmax(-1).topk(3, dim=-1)
    small, _ = corrected_topk_reverse(z, ids, q, chunk_size=1)
    large, _ = corrected_topk_reverse(z, ids, q, chunk_size=99)
    torch.testing.assert_close(small, large)
    torch.testing.assert_close(torch.autograd.grad(small.sum(), z)[0], torch.autograd.grad(large.sum(), z)[0])


def test_diagnostic_scalars_are_detached_and_empty_safe():
    p = torch.tensor([[-2.0, -2.0]], requires_grad=True)
    mask = torch.tensor([[1, 0]])
    _, info = flash_orm_token_loss(
        p, p.detach() + 1, p.detach(), torch.ones_like(p), mask, alpha=0.3, is_lower=0.5, is_upper=2
    )
    assert info["teacher_abs_advantage_mean"].item() == pytest.approx(1)
    assert info["orm_abs_advantage_mean"].item() == pytest.approx(0.3)
    assert info["joint_abs_advantage_mean"].item() == pytest.approx(1.3)
    assert info["is_rejected_fraction"].item() == 0
    assert info["active_token_count"].item() == 1
    _, empty = pg_sequence_token_loss(p, p.detach(), torch.zeros_like(mask))
    assert empty["teacher_abs_advantage_mean"].item() == 0
    assert all(not v.requires_grad for v in info.values())
