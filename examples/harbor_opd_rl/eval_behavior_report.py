"""Behaviour metrics of eval runs, per source, next to the solve rate.

    python examples/harbor_opd_rl/eval_behavior_report.py label1=EVAL_ROOT1 label2=EVAL_ROOT2 [--out f.json]

The Tinker line saw every regressing arm go bad on these before the solve rate moved,
so both lines report them per source (SWE / Terminal-Lego):

  solve_rate          resolved / trials that produced a verdict
  out_tokens_median   generated tokens per rollout (Harbor agent_result.n_output_tokens)
  max_turns_share     rollouts that used all max_turns episodes
  timeout_share       agent timeout (Harbor exception) or trial wall-clock kill
  parse_error_share   rollouts with at least one "Previous response had parsing errors"
  parse_errors_mean   such feedback turns per rollout
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
from collections import Counter, defaultdict

PARSE_FEEDBACK = "Previous response had parsing errors"


def session_record(session: str, max_turns: int) -> dict | None:
    harbor = os.path.join(session, "harbor")
    try:
        config = json.load(open(os.path.join(harbor, "config.json")))
    except (OSError, ValueError):
        return None
    task = os.path.basename(config["task"]["path"])
    rec = {
        "task": task,
        "source": task.split("__", 1)[0],
        "resolved": None,
        "timeout": False,
        "out_tokens": None,
        "turns": None,
        "parse_errors": 0,
        "exception": None,
    }
    try:
        framework_log = open(os.path.join(session, "framework.log"), errors="replace").read()
    except OSError:
        framework_log = ""
    if "exceeded trial_timeout_sec" in framework_log:
        rec["timeout"] = True
        rec["exception"] = "TrialWallClockKill"
    try:
        result = json.load(open(os.path.join(harbor, "result.json")))
    except (OSError, ValueError):
        result = None
    if result:
        agent = result.get("agent_result") or {}
        rec["out_tokens"] = agent.get("n_output_tokens")
        rec["turns"] = (agent.get("metadata") or {}).get("n_episodes")
        exc = result.get("exception_info")
        if exc:
            rec["exception"] = exc.get("exception_type") or str(exc)[:60]
            rec["timeout"] = rec["timeout"] or "Timeout" in str(rec["exception"])
        reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if reward is not None:
            rec["resolved"] = float(reward) >= 1.0
    try:
        steps = json.load(open(os.path.join(harbor, "agent", "trajectory.json"))).get("steps", [])
        rec["parse_errors"] = sum(
            1 for s in steps if s.get("source") != "agent" and PARSE_FEEDBACK in str(s.get("message", ""))
        )
    except (OSError, ValueError, AttributeError):
        pass
    rec["max_turns"] = rec["turns"] is not None and rec["turns"] >= max_turns
    return rec


def summarize(records: list[dict]) -> dict:
    graded = [r for r in records if r["resolved"] is not None]
    toks = [r["out_tokens"] for r in records if r["out_tokens"] is not None]
    n = len(records)
    share = lambda k: round(sum(1 for r in records if r[k]) / n, 3) if n else None  # noqa: E731
    return {
        "rollouts": n,
        "graded": len(graded),
        "solve_rate": round(sum(r["resolved"] for r in graded) / len(graded), 3) if graded else None,
        "out_tokens_median": int(statistics.median(toks)) if toks else None,
        "max_turns_share": share("max_turns"),
        "timeout_share": share("timeout"),
        "parse_error_share": round(sum(1 for r in records if r["parse_errors"]) / n, 3) if n else None,
        "parse_errors_mean": round(sum(r["parse_errors"] for r in records) / n, 2) if n else None,
        "exceptions": dict(Counter(r["exception"] for r in records if r["exception"])),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="label=EVAL_ROOT")
    ap.add_argument("--max-turns", type=int, default=50)
    ap.add_argument("--out")
    args = ap.parse_args()
    report = {}
    for spec in args.runs:
        label, root = spec.split("=", 1)
        sessions = glob.glob(os.path.join(root, "agent-logs", "*", "*", "*", "session-*"))
        records = [r for r in (session_record(s, args.max_turns) for s in sessions) if r]
        by_source = defaultdict(list)
        for r in records:
            by_source[r["source"]].append(r)
        report[label] = {"all": summarize(records)} | {src: summarize(rs) for src, rs in sorted(by_source.items())}
    text = json.dumps(report, indent=1)
    if args.out:
        open(args.out, "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
