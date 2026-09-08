"""Audit this project's trusted single-rank AdamW optimizer checkpoints on CPU.

Observed format: torch dict(state[int] -> empty dict or step/exp_avg/exp_avg_sq,
param_groups -> one group with integer params). This is not a generic optimizer
or arbitrary-pickle inspector. Only use checkpoints produced by our own runs;
weights_only=True restricts unpickling but does not make unknown artifacts safe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import torch


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inspect_state(value):
    require(isinstance(value, dict) and set(value) == {"state", "param_groups"}, "Expected state/param_groups dict")
    states, groups = value["state"], value["param_groups"]
    require(isinstance(states, dict) and states, "Optimizer state must be nonempty")
    require(isinstance(groups, list) and len(groups) == 1 and isinstance(groups[0], dict), "Expected one param group")
    params = groups[0].get("params")
    require(isinstance(params, list) and all(type(p) is int and p >= 0 for p in params), "Expected integer param IDs")
    require(len(params) == len(set(params)) and set(params) == set(states), "Param IDs must exactly match state keys")
    active, steps, nonzero, moment_count = {}, set(), 0, 0
    for key, state in states.items():
        require(type(key) is int and isinstance(state, dict), "Expected integer state keys and dict values")
        if not state:
            continue
        require(set(state) == {"step", "exp_avg", "exp_avg_sq"}, "Unsupported AdamW state fields")
        step = state["step"]
        require(isinstance(step, torch.Tensor) and step.ndim == 0, "Step must be a scalar tensor")
        scalar = step.item()
        require(
            type(scalar) in (int, float) and math.isfinite(scalar) and scalar > 0 and scalar == int(scalar),
            "Step must be a finite positive integer",
        )
        tensors = [state[name] for name in ("exp_avg", "exp_avg_sq")]
        for tensor in tensors:
            require(
                isinstance(tensor, torch.Tensor) and tensor.layout == torch.strided and tensor.numel() > 0,
                "Moments must be nonempty dense tensors",
            )
            require(tensor.is_floating_point() and torch.isfinite(tensor).all().item(), "Nonfinite/invalid moment")
            nonzero += int(torch.count_nonzero(tensor).item() > 0)
            moment_count += 1
        require(
            tensors[0].shape == tensors[1].shape and tensors[0].dtype == tensors[1].dtype, "Moment shape/dtype mismatch"
        )
        require((tensors[1] >= 0).all().item(), "Negative second moment")
        active[key] = state
        steps.add(int(scalar))
    require(active and len(steps) == 1, "Expected nonempty active states at one consistent optimizer step")
    require(nonzero > 0, "All optimizer moments are zero")
    return active, {
        "steps": sorted(steps),
        "active_state_count": len(active),
        "empty_state_count": len(states) - len(active),
        "tensor_count": moment_count + len(active),
        "all_finite": True,
        "nonzero_moment_tensors": nonzero,
    }


def compare_optimizers(before, after):
    report = {"schema": "dsh.native-optimizer-delta.v1", "passed": False, "errors": []}
    try:
        old, before_info = inspect_state(before)
        new, after_info = inspect_state(after)
        report.update(before=before_info, after=after_info)
        require(
            before["param_groups"][0]["params"] == after["param_groups"][0]["params"], "Param group ordering changed"
        )
        require(set(old) == set(new), "Active/empty state topology changed")
        changed = 0
        for key in old:
            require(new[key]["step"].item() > old[key]["step"].item(), "Optimizer step did not advance")
            for name in ("exp_avg", "exp_avg_sq"):
                a, b = old[key][name], new[key][name]
                require(a.shape == b.shape and a.dtype == b.dtype, "Cross-checkpoint moment shape/dtype changed")
                changed += int(not torch.equal(a, b))
        report.update(
            passed=True,
            active_state_count=len(old),
            empty_state_count=before_info["empty_state_count"],
            changed_moment_tensors=changed,
            optimizer_step_advanced=True,
        )
    except (ValueError, TypeError, KeyError, RuntimeError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    return report


def load_trusted(path):
    require(not path.is_symlink() and path.is_file(), "Checkpoint must be a regular non-symlink file")
    with path.open("rb") as source:
        before_hash = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        value = torch.load(source, map_location="cpu", weights_only=True)
        source.seek(0)
        require(
            hashlib.file_digest(source, "sha256").hexdigest() == before_hash, "Checkpoint bytes changed during load"
        )
    return value, {"path": str(path.resolve()), "sha256": before_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Exclusive claim before reading big files; no prior report/checkpoint overwrite.
    with args.output.open("x") as output:
        report = {"schema": "dsh.native-optimizer-delta.v1", "passed": False, "errors": []}
        try:
            require(args.before.resolve() != args.after.resolve(), "Distinct checkpoints required")
            before, before_file = load_trusted(args.before)
            after, after_file = load_trusted(args.after)
            report = compare_optimizers(before, after)
            report["files"] = {"before": before_file, "after": after_file}
        except Exception as error:
            # Loading corruption/unsupported restricted pickle is a failing audit, never a retry with unsafe loading.
            report["errors"].append(f"{type(error).__name__}: {error}")
        report["input_scope"] = "Trusted checkpoints produced by this project's own run; weights_only=True, CPU only"
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(report, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
