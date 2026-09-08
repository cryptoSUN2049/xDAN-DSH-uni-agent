"""Compare trusted single-rank FSDP LoRA state dicts on CPU.

Success proves only a finite adapter update with unchanged base tensors between
these two checkpoints, not initial-to-final learning or task improvement.
"""

import argparse
import hashlib
import json
from pathlib import Path

import torch


def compare_states(before: dict, after: dict) -> dict:
    if before.keys() != after.keys():
        raise ValueError("checkpoint keys differ")
    rows = []
    for name in sorted(before):
        a, b = before[name], after[name]
        if not isinstance(a, torch.Tensor) or not isinstance(b, torch.Tensor):
            raise ValueError(f"non-tensor state: {name}")
        if a.shape != b.shape or a.dtype != b.dtype:
            raise ValueError(f"checkpoint shape or dtype differs: {name}")
        finite = bool(torch.isfinite(a).all() and torch.isfinite(b).all())
        changed = not torch.equal(a, b)
        rows.append(
            {
                "name": name,
                "adapter": "lora_" in name,
                "finite": finite,
                "changed": changed,
                "max_abs_delta": float((a.double() - b.double()).abs().max()) if finite and a.numel() else None,
            }
        )
    adapter_count = sum(r["adapter"] for r in rows)
    adapter_changed = sum(r["adapter"] and r["changed"] for r in rows)
    base_count = len(rows) - adapter_count
    base_changed = sum(not r["adapter"] and r["changed"] for r in rows)
    return {
        "schema": "dsh.single-rank-lora-delta.v1",
        "passed": bool(adapter_changed and base_count and not base_changed and all(r["finite"] for r in rows)),
        "adapter_count": adapter_count,
        "adapter_changed": adapter_changed,
        "base_count": base_count,
        "base_changed": base_changed,
        "tensors": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Refuse pickle code execution; this checker accepts ordinary tensor state dicts.
    before = torch.load(args.before, map_location="cpu", weights_only=True)
    after = torch.load(args.after, map_location="cpu", weights_only=True)
    report = compare_states(before, after)
    for key in ("before", "after"):
        path = getattr(args, key)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        report[key] = {"path": str(path.resolve()), "sha256": digest}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "tensors"}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
