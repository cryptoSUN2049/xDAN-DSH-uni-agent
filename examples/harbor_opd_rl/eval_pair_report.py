"""Paired comparison of two eval runs (summary.json from eval_tb21.sh) on the same tasks.

    python examples/harbor_opd_rl/eval_pair_report.py BASE/summary.json OTHER/summary.json \
        --labels base pipe-r11 --out report.json

Each task contributes its pass rate over the k samples of each run; the statistic is the
mean over tasks of (other - base), with a 95% bootstrap interval that resamples tasks
(paired: a task's two rates move together). Groups: all tasks, and each source prefix
(swe-rebench-v2-fv, terminal-lego-15k). A gain is claimed only when the interval's lower
bound is above 0, the same rule the Tinker line uses on eval-set-v1.
"""

from __future__ import annotations

import argparse
import json
import random


def paired(base: dict[str, list[float]], other: dict[str, list[float]], tasks: list[str], seed: int = 0) -> dict:
    diffs = [sum(other[t]) / len(other[t]) - sum(base[t]) / len(base[t]) for t in tasks]
    rng = random.Random(seed)
    boots = sorted(sum(diffs[rng.randrange(len(diffs))] for _ in diffs) / len(diffs) for _ in range(4000))
    lo, hi = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]
    rate = lambda runs: sum(sum(runs[t]) / len(runs[t]) for t in tasks) / len(tasks)  # noqa: E731
    return {
        "tasks": len(tasks),
        "base_rate": round(rate(base), 4),
        "other_rate": round(rate(other), 4),
        "diff": round(sum(diffs) / len(diffs), 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "gain_claimed": lo > 0,
        "regression_flagged": hi < 0,
        "tasks_up": sum(d > 0 for d in diffs),
        "tasks_down": sum(d < 0 for d in diffs),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("other")
    ap.add_argument("--labels", nargs=2, default=["base", "other"])
    ap.add_argument("--out")
    args = ap.parse_args()
    base = json.load(open(args.base))["per_task"]
    other = json.load(open(args.other))["per_task"]
    common = sorted(set(base) & set(other))
    missing = {
        "only_" + args.labels[0]: sorted(set(base) - set(other)),
        "only_" + args.labels[1]: sorted(set(other) - set(base)),
    }
    groups = {"all": common}
    for prefix in sorted({t.split("__", 1)[0] for t in common}):
        groups[prefix] = [t for t in common if t.startswith(prefix + "__")]
    report = {
        "labels": args.labels,
        "samples_per_task": {
            args.labels[0]: sorted({len(v) for v in base.values()}),
            args.labels[1]: sorted({len(v) for v in other.values()}),
        },
        "missing": missing,
        "groups": {name: paired(base, other, tasks) for name, tasks in groups.items() if tasks},
    }
    text = json.dumps(report, indent=1)
    if args.out:
        open(args.out, "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
