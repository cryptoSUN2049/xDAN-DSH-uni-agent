"""Compare independent HF scoring against historical actual teacher tensors."""

import argparse
import json
from pathlib import Path

import torch


def stats(reference, observed):
    x, y = torch.tensor(reference, dtype=torch.float64), torch.tensor(observed, dtype=torch.float64)
    assert x.shape == y.shape and x.numel() > 0
    error = (x - y).abs()
    return {
        "tokens": x.numel(),
        "finite": bool(torch.isfinite(x).all() and torch.isfinite(y).all()),
        "mean_abs": float(error.mean()),
        "p95_abs": float(error.quantile(0.95)),
        "max_abs": float(error.max()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--hf", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    samples, hf = json.loads(args.samples.read_text()), json.loads(args.hf.read_text())
    assert len(hf["teacher"]) == len(samples)
    rows = []
    for i, sample in enumerate(samples):
        if "live_teacher_logprobs" not in sample:
            continue
        start = sample["prompt_length"] - 1
        response_len = len(sample["response_ids"])
        assert len(hf["teacher"][i]) == len(sample["ids"]) - 1
        mask = sample["response_mask"]
        hf_teacher = hf["teacher"][i][start : start + response_len]
        assert len(hf_teacher) == len(mask)
        keep = lambda values, mask=mask: [v for v, valid in zip(values, mask, strict=True) if valid]  # noqa: E731
        row = {
            "sample_index": sample["sample_index"],
            "source_capture": sample["source_capture"],
            "teacher_hf_vs_actual_live": stats(keep(hf_teacher), keep(sample["live_teacher_logprobs"])),
        }
        if "student" in hf:
            row["student_hf_vs_live_diagnostic_only"] = stats(
                keep(hf["student"][i][start : start + response_len]), keep(sample["live_student_logprobs"])
            )
        teacher = row["teacher_hf_vs_actual_live"]
        row["passed"] = teacher["finite"] and teacher["mean_abs"] < 0.1 and teacher["p95_abs"] < 0.5
        rows.append(row)
    result = {
        "passed": len(rows) == 8 and all(r["passed"] for r in rows),
        "required_actual_live_samples": 8,
        "samples": rows,
        "student_diagnostic_note": "HF base bf16 vs live FSDP actor precision/microbatch numerics; not teacher gate",
    }
    args.out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
