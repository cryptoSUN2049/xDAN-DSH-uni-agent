"""Independent CPU replay of captured live k1 / vanilla PPO microbatches.

Only load locally trusted .pt artifacts. No VERL imports or implementation calls.
"""

import argparse
import json
from pathlib import Path

import torch
import torch.nn.functional as F


def nested(x):
    return isinstance(x, dict) and x.get("kind") == "nested"


def dense(x, padding=0):
    return torch.nn.utils.rnn.pad_sequence(x["rows"], batch_first=True, padding_value=padding) if nested(x) else x


def flat(x):
    return torch.cat(x["rows"]) if nested(x) else x


def response_slice(x, data):
    prompts, responses = data["prompts"], data["responses"]
    if nested(prompts):
        plens = [len(r) for r in prompts["rows"]]
        rlens = [len(r) for r in responses["rows"]]
        maximum = int(data.get("max_response_len", max(rlens)))
    else:
        attention = data["attention_mask"]
        plens = attention[:, : prompts.shape[1]].sum(1).tolist()
        rlens = attention[:, prompts.shape[1] :].sum(1).tolist()
        maximum = responses.shape[1]
    rows, offset = [], 0
    for p, r in zip(plens, rlens, strict=True):
        p, r = int(p), int(r)
        assert p > 0
        # Causal next-token score at prompt-last through response-penultimate.
        rows.append(F.pad(x[offset + p - 1 : offset + p + r - 1], (0, 0) * (x.ndim - 1) + (0, maximum - r)))
        offset += p + r
    assert offset == len(x)
    return torch.stack(rows)


def aggregate(values, mask, mode, info):
    dp = info.get("dp_size", 1)
    if mode == "token-mean":
        denom = info.get("batch_num_tokens")
        return (values * mask).sum() / (mask.sum() if denom is None else denom) * dp
    if mode == "token-sum":
        return (values * mask).sum() * dp
    count = mask.sum(-1)
    seq = (values * mask).sum(-1)
    if mode == "seq-mean-token-mean":
        seq = seq / (count + 1e-8)
    elif mode not in ("seq-mean-token-sum", "seq-mean-token-sum-norm"):
        raise ValueError(mode)
    denom = info.get("global_batch_size")
    result = (seq * (count > 0)).sum() / ((count > 0).sum() if denom is None else denom) * dp
    if mode == "seq-mean-token-sum-norm":
        scale = info.get("loss_scale_factor")
        result = result / (mask.shape[-1] if scale is None else scale)
    return result


def replay(path):
    payload = torch.load(path, map_location="cpu", weights_only=False)
    assert payload["origin"] == "live-native-distillation-loss"
    config, data = payload["loss_config"], payload["data"]
    assert config["loss_mode"] in ("k1", "kl") and config["use_policy_gradient"]
    assert config["policy_loss_mode"] == "vanilla", config
    raw = flat(payload["model_log_probs"]).clone().requires_grad_(True)
    student = response_slice(raw, data)
    teacher = response_slice(flat(data["teacher_logprobs"]), data).squeeze(-1)
    teacher_ids = response_slice(flat(data["teacher_ids"]), data).squeeze(-1)
    response = dense(data["responses"])
    mask = dense(data["response_mask"]).bool()
    assert teacher_ids.shape == response.shape == mask.shape
    id_errors = int((teacher_ids[mask] != response[mask]).sum())
    advantages = student - teacher
    if config["loss_max_clamp"] is not None:
        bound = config["loss_max_clamp"]
        advantages = advantages.clamp(-bound, bound)
    advantages = -advantages.detach()
    old = dense(data["old_log_probs"])
    ratio = (student - old).clamp(-20, 20).exp()
    low = config["clip_ratio_low"] if config["clip_ratio_low"] is not None else config["clip_ratio"]
    high = config["clip_ratio_high"] if config["clip_ratio_high"] is not None else config["clip_ratio"]
    unclipped = -advantages * ratio
    clipped = -advantages * ratio.clamp(1 - low, 1 + high)
    upper = torch.maximum(unclipped, clipped)
    dual = torch.minimum(-advantages * config["clip_ratio_c"], upper)
    values = torch.where(advantages < 0, dual, upper)
    if data.get("rollout_is_weights") is not None:
        values = values * dense(data["rollout_is_weights"])
    loss = aggregate(values, mask, payload["aggregation"], payload["global_batch_info"])
    grad = torch.autograd.grad(loss, raw)[0]
    actual_grad = flat(payload["actual_gradient"])
    loss_error = float((loss.detach() - payload["actual_loss"]).abs())
    grad_error = float((grad - actual_grad).abs().max())
    loss_ok = bool(torch.allclose(loss.detach(), payload["actual_loss"], atol=2e-6, rtol=2e-5))
    grad_ok = bool(torch.allclose(grad, actual_grad, atol=2e-6, rtol=2e-5))
    finite = bool(torch.isfinite(loss) and torch.isfinite(grad).all() and torch.isfinite(teacher[mask]).all())
    # All raw gradient positions outside the response-scoring mask must be zero.
    selector = torch.arange(raw.numel()).reshape(raw.shape)
    selected = response_slice(selector, data)[mask]
    outside = torch.ones(raw.numel(), dtype=torch.bool)
    outside[selected.flatten()] = False
    masked_gradient_max = float(actual_grad.flatten()[outside].abs().max()) if outside.any() else 0.0
    return {
        "file": str(path),
        "valid_tokens": int(mask.sum()),
        "teacher_id_mismatches": id_errors,
        "actual_loss": float(payload["actual_loss"]),
        "recomputed_loss": float(loss.detach()),
        "loss_absolute_error": loss_error,
        "gradient_max_absolute_error": grad_error,
        "outside_response_gradient_max": masked_gradient_max,
        "finite": finite,
        "temperature": str(data.get("temperature", "absent")),
        "passed": loss_ok and grad_ok and finite and id_errors == 0 and masked_gradient_max == 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    files = sorted(args.directory.glob("micro-*.pt"))
    assert files, "No live captures: installation marker alone is not proof"
    results = [replay(path) for path in files]
    result = {"passed": all(r["passed"] for r in results), "microbatches": results}
    (args.directory / "replay-verdict.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
