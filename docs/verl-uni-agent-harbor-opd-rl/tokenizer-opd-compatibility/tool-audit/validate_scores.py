"""Independent fail-closed scoring gate for eight live rows plus nine mode rows."""

import argparse
import json
from pathlib import Path

import numpy as np

EXPECTED_MODES = {
    f"{name}_thinking_{mode}"
    for name in ("single", "history_reasoning_field", "history_inline_thinking", "tool_history_control")
    for mode in ("false", "true")
} | {"long_prompt_thinking_false"}


def compare(reference, actual):
    ref, got = np.asarray(reference, dtype=float), np.asarray(actual, dtype=float)
    assert ref.ndim == got.ndim == 1 and ref.shape == got.shape and ref.size > 0
    finite = bool(np.isfinite(ref).all() and np.isfinite(got).all())
    if not finite:
        return {"passed": False, "finite": False, "tokens": len(ref)}
    error = np.abs(ref - got)
    return {
        "tokens": len(ref),
        "finite": True,
        "mean_abs_error": float(error.mean()),
        "p95_abs_error": float(np.quantile(error, 0.95)),
        "max_abs_error": float(error.max()),
        "passed": bool(error.mean() < 0.1 and np.quantile(error, 0.95) < 0.5),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    args = p.parse_args()
    root = args.directory
    rows = json.loads((root / "samples.json").read_text())
    hf = json.loads((root / "hf-replay.json").read_text())
    vllm = json.loads((root / "vllm-replay.json").read_text())
    assert len(rows) == len(hf["teacher"]) == len(hf["student"]) == len(vllm) == 17
    live = [r for r in rows if "live_teacher_logprobs" in r]
    modes = [r for r in rows if "live_teacher_logprobs" not in r]
    assert len(live) == 8 and len(modes) == 9
    assert {r["domain"] for r in modes} == EXPECTED_MODES
    assert len({(r["source_capture"], r["microbatch_row"]) for r in live}) == 8
    results = []
    for i, row in enumerate(rows):
        n, start = len(row["ids"]) - row["prompt_length"], row["prompt_length"] - 1
        assert n > 0 and start >= 0
        assert len(hf["teacher"][i]) == len(hf["student"][i]) == len(vllm[i]) == len(row["ids"]) - 1
        teacher_ref = np.asarray(hf["teacher"][i][start:])
        item = {"index": i, "domain": row["domain"], "hf_vs_vllm_teacher": compare(teacher_ref, vllm[i][start:])}
        if "live_teacher_logprobs" in row:
            assert row["scope"].startswith("exact raw IDs captured")
            assert row["ids"] == row["prompt_ids"] + row["response_ids"]
            assert len(row["response_mask"]) == len(row["live_teacher_ids"]) == n
            assert all(x in (0, 1, False, True) for x in row["response_mask"])
            mask = np.asarray(row["response_mask"], dtype=bool)
            assert mask.any()
            assert all(a == b for a, b, m in zip(row["live_teacher_ids"], row["response_ids"], mask, strict=True) if m)
            assert (
                len(row["live_teacher_logprobs"])
                == len(row["live_student_logprobs"])
                == len(row["live_old_log_probs"])
                == n
            )
            item["live_teacher_vs_hf_at_temperature_1"] = compare(
                teacher_ref[mask], np.asarray(row["live_teacher_logprobs"])[mask]
            )
            student_ref = np.asarray(hf["student"][i][start:])[mask]
            item["student_diagnostic_only"] = compare(student_ref, np.asarray(row["live_student_logprobs"])[mask])
            item["old_policy_diagnostic_only"] = compare(student_ref, np.asarray(row["live_old_log_probs"])[mask])
            item["actor_temperature_recorded"] = row["actor_temperature"]
            item["passed"] = (
                item["hf_vs_vllm_teacher"]["passed"] and item["live_teacher_vs_hf_at_temperature_1"]["passed"]
            )
        else:
            assert row["scope"].startswith("HF student actual generation raw token IDs")
            item["passed"] = item["hf_vs_vllm_teacher"]["passed"]
        results.append(item)
    result = {
        "passed": all(r["passed"] for r in results),
        "coverage": {"expected_live": 8, "actual_live": len(live), "expected_modes": 9, "actual_modes": len(modes)},
        "gates": {"mean_abs_error_below": 0.1, "p95_abs_error_below": 0.5, "finite_required": True},
        "teacher_reference_temperature": 1.0,
        "student_reference_temperature": 0.8,
        "student_comparison_scope": (
            "Diagnostic only: requires separate proof of initial base identity, "
            "zero-B LoRA and no preceding optimizer update. Not a gate."
        ),
        "limits": [
            "Model identity, source hashes and actual launch temperatures must be audited separately",
            "Eight distinct capture rows do not alone prove all trainer microbatches were captured",
        ],
        "cases": results,
    }
    (root / "score-acceptance.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"passed": result["passed"], "cases": len(results)}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
