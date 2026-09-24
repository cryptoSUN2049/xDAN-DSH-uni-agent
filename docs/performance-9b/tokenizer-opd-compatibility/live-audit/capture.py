"""Capture true microbatch loss boundary; never patch deployed VERL files."""

import functools
import hashlib
import json
import os
import time
from pathlib import Path

import torch


def pack(value):
    if isinstance(value, torch.Tensor):
        if value.is_nested:
            return {"kind": "nested", "rows": [x.detach().cpu().clone() for x in value.unbind()]}
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {str(k): pack(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [pack(v) for v in value]
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if hasattr(value, "data"):
        return pack(value.data)
    return {"unserialized_type": type(value).__name__, "repr": repr(value)}


def install(module):
    original = module.distillation_loss
    destination = Path(os.environ["OPD_LIVE_AUDIT_DIR"])
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(module.__file__)
    marker = {
        "pid": os.getpid(),
        "python": os.sys.executable,
        "virtual_env": os.environ.get("VIRTUAL_ENV"),
        "module": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "capture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (destination / f"installed-{os.getpid()}.json").write_text(json.dumps(marker, indent=2))
    counter = 0

    @functools.wraps(original)
    def wrapped(config, distillation_config, model_output, data):
        nonlocal counter
        loss, metrics = original(config, distillation_config, model_output, data)
        if counter >= int(os.environ.get("OPD_LIVE_AUDIT_MAX_CALLS", "64")):
            return loss, metrics
        counter += 1
        # retain_graph preserves normal backward; autograd.grad does not accumulate .grad.
        gradient = torch.autograd.grad(loss, model_output["log_probs"], retain_graph=True)[0]
        lc = distillation_config.distillation_loss
        fields = (
            "loss_mode",
            "use_policy_gradient",
            "policy_loss_mode",
            "loss_max_clamp",
            "clip_ratio",
            "clip_ratio_low",
            "clip_ratio_high",
            "clip_ratio_c",
            "log_prob_min_clamp",
            "use_task_rewards",
        )
        payload = {
            "schema": 1,
            "origin": "live-native-distillation-loss",
            "identity": marker,
            "time_ns": time.time_ns(),
            "data": {str(k): pack(v) for k, v in data.items()},
            "model_log_probs": pack(model_output["log_probs"]),
            "actual_gradient": pack(gradient),
            "actual_loss": pack(loss),
            "loss_config": {k: pack(getattr(lc, k, 3.0 if k == "clip_ratio_c" else None)) for k in fields},
            "aggregation": config.loss_agg_mode,
            "global_batch_info": pack(config.global_batch_info),
            "temperature_note": ("Actor temperature is in data; teacher temperature requires run config."),
        }
        output = destination / f"micro-{os.getpid()}-{counter:04d}.pt"
        temporary = output.with_suffix(".tmp")
        torch.save(payload, temporary)
        temporary.replace(output)
        return loss, metrics

    module.distillation_loss = wrapped
