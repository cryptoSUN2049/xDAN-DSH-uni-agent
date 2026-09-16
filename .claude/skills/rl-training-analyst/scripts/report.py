"""Build the standard training-signal table for one VERL + Harbor run.

Usage:
  python report.py --run <wandb url|entity/project/id> --run-root <RUN_ROOT> [--label "run 01"] [--json out.json]

Rows mirror the Tinker-line report so the two lines can be compared:
  reward/mean · groups-with-variance fraction · nonzero-advantage groups · grad_norm
  · trajectory termination breakdown (completed / max_turns / parse_error / error)
  · OPD rows (N/A until the Teacher route is wired) · held-out (N/A until enabled)
Sources: wandb scan_history (same data as the dashboard) and
<RUN_ROOT>/agent-logs/*/*/step_N/session-*/{task.log,harbor/agent/trajectory.json}.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict


def run_path(arg: str) -> str:
    if "wandb.ai/" in arg:
        entity, project, _, run_id = arg.split("wandb.ai/")[1].split("/")[:4]
        return f"{entity}/{project}/{run_id}"
    return arg


def wandb_rows(run_arg: str) -> tuple[dict, list[dict]]:
    import wandb

    run = wandb.Api().run(run_path(run_arg))
    rows = [h for h in run.scan_history() if h.get("training/global_step") is not None]
    return {"url": run.url, "state": run.state, "name": run.name}, rows


def trials(run_root: str) -> list[dict]:
    """One record per Harbor trial: step, task, sample, reward, termination."""
    out = []
    for task_log in glob.glob(os.path.join(run_root, "agent-logs", "*", "*", "step_*", "session-*", "task.log")):
        sess = os.path.dirname(task_log)
        step = int(re.search(r"step_(\d+)", sess).group(1))
        m = re.search(r"session-sample-(\d+)-rollout-(\d+)", os.path.basename(sess))
        sample, rollout = (int(m.group(1)), int(m.group(2))) if m else (-1, -1)
        text = open(task_log, encoding="utf-8", errors="replace").read()
        done = re.search(r"Harbor trial done: instance_id=(\S+) reward=([0-9.]+)", text)
        incomplete = re.search(r"Harbor trial incomplete for \S+: (\w+)", text)
        rec = {
            "step": step,
            "sample": sample,
            "rollout": rollout,
            "task": done.group(1).split("/")[-1] if done else None,
            "reward": float(done.group(2)) if done else None,
            "termination": "error:" + incomplete.group(1) if incomplete else None,
        }
        traj = os.path.join(sess, "harbor", "agent", "trajectory.json")
        if os.path.exists(traj) and rec["termination"] is None:
            t = json.load(open(traj))
            steps = t.get("steps") or []
            last = steps[-1] if steps else {}
            calls = last.get("tool_calls") or []
            fn = calls[0].get("function_name") if calls else None
            metrics = t.get("final_metrics") or {}
            rec["turns"] = len(steps)
            rec["completion_tokens"] = metrics.get("total_completion_tokens")
            if fn == "mark_task_complete":
                rec["termination"] = "completed"
            elif calls:
                rec["termination"] = "max_turns"
            else:
                rec["termination"] = "parse_error"
        out.append(rec)
    return sorted(out, key=lambda r: (r["step"], r["sample"], r["rollout"]))


def summarize(rows: list[dict], trs: list[dict]) -> dict:
    by_group: dict[tuple[int, int], list[float]] = defaultdict(list)
    for r in trs:
        if r["reward"] is not None:
            by_group[(r["step"], r["sample"])].append(r["reward"])
    groups = len(by_group)
    var_groups = sum(1 for v in by_group.values() if len(v) > 1 and max(v) > min(v))
    rewards = [r["reward"] for r in trs if r["reward"] is not None]
    term = defaultdict(int)
    for r in trs:
        term[r["termination"] or "unknown"] += 1
    grad = [h.get("actor/grad_norm") for h in rows]
    return {
        "steps_logged": len(rows),
        "reward/mean": round(sum(rewards) / len(rewards), 3) if rewards else None,
        "groups": groups,
        "groups_with_variance": var_groups,
        "groups_with_variance_frac": round(var_groups / groups, 3) if groups else None,
        "trials": len(trs),
        "grad_norm_per_step": [round(g, 5) if isinstance(g, (int, float)) else g for g in grad],
        "steps_with_nonzero_grad": [
            int(h["training/global_step"]) for h in rows if (h.get("actor/grad_norm") or 0) > 0
        ],
        "score_mean_per_step": [round(h.get("critic/score/mean", 0), 3) for h in rows],
        "response_length_mean_per_step": [round(h.get("response_length/mean", 0)) for h in rows],
        "gen_seconds_per_step": [round(h.get("timing_s/gen", 0)) for h in rows],
        "termination": dict(term),
        "opd": {
            "teacher_kl": "N/A (route 2)",
            "opd_nonzero_tokens": "N/A (route 2)",
            "rl_opd_sign_disagreement": "N/A (route 2)",
        },
        "held_out": "N/A (val disabled in smoke)",
    }


def table(label: str, s: dict) -> str:
    rows = [
        ("reward/mean", s["reward/mean"]),
        ("有组内方差的组占比", f"{s['groups_with_variance_frac']} ({s['groups_with_variance']}/{s['groups']} 组)"),
        ("非零梯度的 step", f"{s['steps_with_nonzero_grad']} / {s['steps_logged']} 步"),
        ("actor/grad_norm 每步", s["grad_norm_per_step"]),
        ("critic/score/mean 每步", s["score_mean_per_step"]),
        ("response_length/mean 每步", s["response_length_mean_per_step"]),
        ("timing_s/gen 每步", s["gen_seconds_per_step"]),
        ("轨迹终止", " / ".join(f"{k} {v}" for k, v in sorted(s["termination"].items()))),
        ("OPD 非零 token", s["opd"]["opd_nonzero_tokens"]),
        ("teacher_kl", s["opd"]["teacher_kl"]),
        ("RL 与 OPD 反号占比", s["opd"]["rl_opd_sign_disagreement"]),
        ("held-out", s["held_out"]),
    ]
    width = max(len(k) for k, _ in rows)
    lines = [f"| {'指标'.ljust(width)} | {label} |", f"|{'-' * (width + 2)}|{'-' * (len(label) + 2)}|"]
    lines += [f"| {k.ljust(width)} | {v} |" for k, v in rows]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--label", default="run")
    parser.add_argument("--json")
    args = parser.parse_args()
    meta, rows = wandb_rows(args.run)
    trs = trials(args.run_root)
    s = summarize(rows, trs)
    print(f"{args.label}: wandb {meta['url']} (state={meta['state']})")
    print(table(args.label, s))
    if args.json:
        json.dump({"run": meta, "summary": s, "trials": trs, "wandb_rows": rows}, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
