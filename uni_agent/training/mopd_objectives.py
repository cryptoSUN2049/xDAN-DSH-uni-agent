"""MiMo objectives with explicit sampling, masking, and trajectory reduction.

These functions deliberately do not perform PPO clipping, candidate-set
renormalization, or a second rollout correction. Teacher quantities and sampled
advantages are constants for differentiation; student logits remain connected.
"""

import math

import torch


def _mask_like(values, mask):
    if mask is None:
        return torch.ones_like(values, dtype=torch.bool)
    if mask.shape != values.shape:
        raise ValueError("Mask shape must equal token shape")
    if not torch.all((mask == 0) | (mask == 1)):
        raise ValueError("Mask must contain only finite binary values")
    return mask.to(device=values.device, dtype=torch.bool)


def _finite_active(value, mask, name):
    if not value.is_floating_point() or value.device != mask.device:
        raise ValueError(f"{name} must be floating and on the mask device")
    if value.shape != mask.shape:
        raise ValueError(f"{name} shape must equal token shape")
    if not torch.isfinite(value[mask]).all():
        raise ValueError(f"Active {name} values must be finite")
    return torch.where(mask, value, 0.0)


def _active_mean(value, mask):
    return (value.detach() * mask).sum() / mask.sum().clamp_min(1)


def _compute_dtype(value):
    return torch.float64 if value.dtype == torch.float64 else torch.float32


def sequence_mean(token_losses, mask, *, global_num_sequences=None, dp_size=1):
    """Mean tokens within each trajectory, then mean valid trajectories.

    For partitioned updates, callers must supply the *whole update* valid sequence
    count. DP averages gradients, hence each local contribution is scaled by DP
    size; microbatch contributions must be summed without another averaging step.
    Empty synthetic padding trajectories do not count toward this denominator.
    """
    if token_losses.ndim != 2:
        raise ValueError("Trajectory reduction requires [batch, tokens]")
    valid = _mask_like(token_losses, mask)
    values = _finite_active(token_losses, valid, "loss").to(_compute_dtype(token_losses))
    lengths = valid.sum(-1)
    if global_num_sequences is None:
        global_num_sequences = int((lengths > 0).sum())
    if (
        not math.isfinite(float(global_num_sequences))
        or float(global_num_sequences) <= 0
        or float(global_num_sequences) != int(global_num_sequences)
    ):
        raise ValueError("Reduction requires a positive valid trajectory count")
    if not math.isfinite(float(dp_size)) or dp_size < 1 or int(dp_size) != dp_size:
        raise ValueError("dp_size must be a positive integer")
    if int((lengths > 0).sum()) > global_num_sequences:
        raise ValueError("Global valid trajectory count is smaller than local count")
    return (values.sum(-1) / lengths.clamp_min(1)).sum() * (dp_size / global_num_sequences)


def pg_sequence_token_loss(logp, logq, mask, *, advantage_clip=5.0):
    """Sampled reverse-KL PG surrogate, with detached clipped teacher advantage."""
    if not math.isfinite(advantage_clip) or advantage_clip <= 0:
        raise ValueError("advantage_clip must be finite and positive")
    valid = _mask_like(logp, mask)
    p = _finite_active(logp, valid, "student logprob").to(_compute_dtype(logp))
    q = _finite_active(logq.detach(), valid, "teacher logprob").to(p.dtype)
    advantage = (q - p.detach()).clamp(-advantage_clip, advantage_clip)
    return -p * advantage, {
        "teacher_advantage": advantage,
        "teacher_abs_advantage_mean": _active_mean(advantage.abs(), valid),
        "active_token_count": valid.sum().detach(),
    }


def corrected_topk_reverse(logits, candidates, logq, valid=None, *, chunk_size=1024):
    """Sum p log(p/q) - p + q on teacher-selected vocabulary entries.

    Student probabilities use the FULL vocabulary partition function. Neither
    distribution is renormalized onto the teacher top-k set. FP16/BF16 inputs use
    FP32 arithmetic; FP64 is preserved for reference and gradient checks. Chunks
    bound temporary full-vocabulary activation sizes over valid token positions.
    """
    if logits.ndim < 2 or logits.shape[-1] < 1 or not logits.is_floating_point():
        raise ValueError("Expected floating logits with a vocabulary dimension")
    if candidates.shape != logq.shape or candidates.shape[:-1] != logits.shape[:-1]:
        raise ValueError("Candidate and teacher shapes must match student token positions")
    if candidates.dtype not in (torch.int32, torch.int64):
        raise ValueError("Candidate token IDs must be integer tensors")
    if candidates.shape[-1] < 1 or candidates.shape[-1] > logits.shape[-1]:
        raise ValueError("Invalid number of candidate tokens")
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    mask = _mask_like(logits[..., 0], valid)
    shape = mask.shape
    flat = logits.reshape(-1, logits.shape[-1])
    indices = mask.flatten().nonzero().flatten()
    ids = candidates.reshape(-1, candidates.shape[-1])[indices].long()
    q = logq.detach().reshape(-1, logq.shape[-1])[indices].to(_compute_dtype(logits))
    if torch.any((ids < 0) | (ids >= logits.shape[-1])):
        raise ValueError("Active candidate IDs outside vocabulary")
    if ids.shape[-1] > 1 and torch.any(ids.sort(-1).values.diff(dim=-1) == 0):
        raise ValueError("Active candidate IDs must be unique")
    if not torch.isfinite(q).all():
        raise ValueError("Active teacher logprobs must be finite")
    # Empty-slice sum retains a zero-gradient connection without reading NaN
    # dummy logits. Multiplying an invalid logit by zero would still yield NaN.
    zero = flat[:, :0].sum(-1).to(_compute_dtype(logits))
    loss_parts, p_parts, q_parts = [], [], []
    for start in range(0, indices.numel(), chunk_size):
        z = flat[indices[start : start + chunk_size]].to(_compute_dtype(logits))
        if not torch.isfinite(z).all():
            raise ValueError("Active student logits must be finite")
        logp = z.gather(-1, ids[start : start + chunk_size]) - z.logsumexp(-1, keepdim=True)
        teacher = q[start : start + chunk_size]
        p, teacher_p = logp.exp(), teacher.exp()
        loss_parts.append((p * (logp - teacher) - p + teacher_p).sum(-1))
        p_parts.append(p.sum(-1).detach())
        q_parts.append(teacher_p.sum(-1))
    if not loss_parts:
        return zero.reshape(shape), {
            "student_mass": zero.detach().reshape(shape),
            "teacher_mass": zero.detach().reshape(shape),
        }
    losses = zero.index_copy(0, indices, torch.cat(loss_parts)).reshape(shape)
    return losses, {
        "student_mass": zero.detach().index_copy(0, indices, torch.cat(p_parts)).reshape(shape),
        "teacher_mass": zero.detach().index_copy(0, indices, torch.cat(q_parts)).reshape(shape),
    }


def flash_orm_token_loss(logp, logq, logmu, orm, mask, *, alpha, is_lower, is_upper):
    """Flash joint advantage and detached current-policy / sampling-policy IS.

    Ratios outside the closed acceptance interval become zero, not clipped.
    Call sequence_mean with the ORIGINAL response mask so rejected positions
    retain their share of the trajectory denominator. No teacher clamp applies.
    """
    if not math.isfinite(alpha) or alpha < 0:
        raise ValueError("alpha must be finite and nonnegative")
    if not (math.isfinite(is_lower) and math.isfinite(is_upper) and 0 < is_lower <= 1 <= is_upper):
        raise ValueError("Importance thresholds must be finite and satisfy 0 < lower <= 1 <= upper")
    valid = _mask_like(logp, mask)
    p = _finite_active(logp, valid, "student logprob").to(_compute_dtype(logp))
    q = _finite_active(logq.detach(), valid, "teacher logprob").to(p.dtype)
    mu = _finite_active(logmu.detach(), valid, "sampling logprob").to(p.dtype)
    reward = orm.detach()
    if reward.shape == p.shape[:-1]:
        reward = reward.unsqueeze(-1).expand_as(p)
    reward = _finite_active(reward, valid, "ORM advantage").to(p.dtype)
    advantage = q - p.detach() + alpha * reward
    log_ratio = p.detach() - mu
    lower, upper = math.log(is_lower), math.log(is_upper)
    # Closed endpoints tolerate only arithmetic roundoff from log subtraction.
    tolerance = 4 * torch.finfo(p.dtype).eps * max(1.0, abs(lower), abs(upper))
    accepted = valid & (log_ratio >= lower - tolerance) & (log_ratio <= upper + tolerance)
    # Reject BEFORE exp: an overflowed ratio must never form 0 * inf.
    weight = torch.where(accepted, torch.where(accepted, log_ratio, 0.0).exp(), 0.0)
    loss = -p * weight * advantage
    return loss, {
        "teacher_advantage": q - p.detach(),
        "joint_advantage": advantage,
        "is_weight": weight,
        "teacher_abs_advantage_mean": _active_mean((q - p.detach()).abs(), valid),
        "orm_abs_advantage_mean": _active_mean((alpha * reward).abs(), valid),
        "joint_abs_advantage_mean": _active_mean(advantage.abs(), valid),
        "is_rejected_fraction": _active_mean((~accepted).to(p.dtype), valid),
        "active_token_count": valid.sum().detach(),
    }
