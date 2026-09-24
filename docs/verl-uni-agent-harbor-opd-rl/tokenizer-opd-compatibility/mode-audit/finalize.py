"""Assert mode-matrix coverage and replace the inherited replay scope explicitly."""

import argparse
import json
from pathlib import Path


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["preflight", "merge", "verdict"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--capture-samples", type=Path)
    args = p.parse_args()
    out = args.out
    rows = json.loads((out / "samples.json").read_text())
    if args.mode == "merge":
        assert args.capture_samples is not None
        live = json.loads(args.capture_samples.read_text())
        assert len(rows) == 9 and len(live) == 8
        assert len({r["domain"] for r in rows + live}) == 17
        assert all(0 < r["prompt_length"] < len(r["ids"]) <= 4095 for r in live)
        write(out / "mode-only-samples.json", rows)
        write(out / "live-capture-samples.json", live)
        write(out / "samples.json", rows + live)
        return
    all_rows = rows
    if (out / "mode-only-samples.json").exists():
        rows = json.loads((out / "mode-only-samples.json").read_text())
    generation = json.loads((out / "generation-complete.json").read_text())
    expected = {
        f"{name}_thinking_{mode}"
        for name in ["single", "history_reasoning_field", "history_inline_thinking", "tool_history_control"]
        for mode in ["false", "true"]
    } | {"long_prompt_thinking_false"}
    assert len(rows) == 9 and {r["domain"] for r in rows} == expected
    assert generation["passed"] and generation["samples"] == generation["expected"] == 9
    assert all(r["generation_budget"] == 1024 for r in rows)
    assert all(r["prompt_length"] < len(r["ids"]) <= 4095 for r in rows)
    assert all(r["scope"].startswith("HF student actual generation raw token IDs") for r in rows)
    assert all(r["cross_tokenizer_equal"] for r in rows)
    unclosed = [r["domain"] for r in rows if r["thinking"] and not r["thinking_close_observed"]]
    exhausted = [r["domain"] for r in rows if r["budget_exhausted"]]
    checks = {
        "expected_cases": 9,
        "actual_cases": len(rows),
        "actual_generation_complete": True,
        "all_contexts_within_4095": True,
        "unclosed_thinking_cases": unclosed,
        "budget_exhausted_cases": exhausted,
        "all_thinking_closed": not unclosed,
        "all_generation_ended": not exhausted,
        "tool_execution_verified": False,
        "tool_rollout_mask_verified": False,
        "scope": "9-mode HF student raw IDs; constructed histories, student template, context <=4096",
    }
    write(out / "mode-generation-check.json", checks)
    if args.mode == "preflight":
        # Keep scoring unfinished thinking prefixes, but never label those full acceptance.
        print(json.dumps(checks, ensure_ascii=False), flush=True)
        return
    verdict = json.loads((out / "replay-verdict.json").read_text())
    loss = json.loads((out / "replay-loss-check.json").read_text())
    parser = json.loads((out / "native-parser-checks.json").read_text())
    expected_all = {r["domain"] for r in all_rows}
    assert len(expected_all) == len(all_rows)
    assert len(verdict["cases"]) == len(parser) == len(all_rows)
    assert {r["domain"] for r in verdict["cases"]} == expected_all
    assert {r["domain"] for r in parser} == expected_all
    if len(all_rows) != 9:
        assert len(all_rows) == 17
        checks["scope"] += "; plus 8 separate live-capture scoring cases"
        checks["total_scoring_cases"] = 17
    parser_passed = all(r["all_shifted_ids_equal"] and r["dummy_tail_correct"] for r in parser)
    numeric_passed = verdict["passed"] and loss["passed"] and parser_passed
    verdict["scope"] = checks["scope"]
    verdict["tool_execution_verified"] = False
    verdict["tool_rollout_mask_verified"] = False
    write(out / "replay-verdict.json", verdict)
    result = {
        **checks,
        "score_coordinate_and_numeric_passed": numeric_passed,
        "native_parser_passed": parser_passed,
        "acceptance_passed": bool(numeric_passed and not unclosed and not exhausted),
        "mean_abs_error": verdict["mean_abs_error"],
        "p95_abs_error": verdict["p95_abs_error"],
        "scope_limits": [
            "Not real tool execution or rollout mask",
            "Not complete thinking quality evaluation",
            "Not contexts above 4096",
            "Not live trainer tensor equivalence",
        ],
    }
    write(out / "mode-verdict.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    assert result["acceptance_passed"], "Mode audit failed; inspect mode-verdict.json (preserved)"


if __name__ == "__main__":
    main()
