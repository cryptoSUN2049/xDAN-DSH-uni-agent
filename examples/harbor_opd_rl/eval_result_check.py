"""Build failure-preserving evaluation evidence and validate the exact parquet task set."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DONE = re.compile(r"Harbor trial done: instance_id=(\S+) reward=[0-9.]+ resolved=(True|False)\b")
BAD = re.compile(r"Harbor trial incomplete for (\S+) \(infra\)")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def check(root: Path, data: Path, n: int, limit: int, process_exit: int, resume_from: str) -> dict:
    import pandas as pd

    config_errors = []
    try:
        rows = pd.read_parquet(data).to_dict("records")
        if limit > 0:
            rows = rows[:limit]
        expected = [row["extra_info"]["tools_kwargs"]["task"]["metadata"]["instance_id"] for row in rows]
        if not expected or n < 1:
            raise ValueError("empty task selection or invalid sample count")
        if len(set(expected)) != len(expected):
            raise ValueError("duplicate instance_id in eval parquet")
        if len({x.rsplit("/", 1)[-1] for x in expected}) != len(expected):
            raise ValueError("task basenames collide; cannot emit unambiguous paired summary")
    except Exception as exc:
        expected = []
        config_errors.append(f"invalid eval data: {exc}")

    observed, infra = {}, {}
    for path in sorted((root / "agent-logs").rglob("task.log")):
        text = path.read_text(errors="replace")
        for match in DONE.finditer(text):
            observed.setdefault(match[1], []).append(float(match[2] == "True"))
        for match in BAD.finditer(text):
            name = match[1].rsplit("/", 1)[-1]
            infra[name] = infra.get(name, 0) + 1
    log_path = root / "eval.log"
    log = ANSI.sub("", log_path.read_text(errors="replace")) if log_path.exists() else ""
    loaded = not resume_from
    if resume_from:
        actor = re.escape(str(Path(resume_from) / "actor"))
        loaded = bool(
            re.search(
                r"Loaded (?:model|LoRA-only checkpoint \([^\n]*\)) from "
                + actor
                + r"/model_world_size_\d+_rank_\d+\.pt\b",
                log,
            )
        )
    counts = {task: len(observed.get(task, [])) for task in expected}
    mismatches = {task: count for task, count in counts.items() if count != n}
    unexpected = sorted(set(observed) - set(expected))
    errors = list(config_errors)
    if process_exit:
        errors.append(f"trainer exited {process_exit}")
    if not loaded:
        errors.append("requested checkpoint load evidence missing")
    if mismatches:
        errors.append("per-task sample counts differ from requested n")
    if unexpected:
        errors.append("unexpected task identities")
    status = "failed" if config_errors or process_exit or not loaded else ("incomplete" if errors else "complete")
    per_task = {task.rsplit("/", 1)[-1]: values for task, values in sorted(observed.items())}
    means = [sum(values) / len(values) for values in per_task.values()]
    summary = {
        "tasks": len(per_task),
        "samples": sum(map(len, per_task.values())),
        "pass_rate": sum(means) / len(means) if means else None,
        "infra_incomplete": infra,
        "per_task": per_task,
        "status": status,
        "checkpoint_loaded": loaded,
        "process_exit": process_exit,
        "errors": errors,
        "expected_tasks": len(expected),
        "expected_n": n,
        "sample_count_mismatches": mismatches,
        "unexpected_task_ids": unexpected,
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    validation = {key: value for key, value in summary.items() if key not in ("per_task", "pass_rate")}
    validation["data"] = str(data)
    validation["resume_from"] = resume_from
    (root / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--process-exit", type=int, required=True)
    parser.add_argument("--resume-from", default="")
    args = parser.parse_args()
    result = check(args.root, args.data, args.n, args.limit, args.process_exit, args.resume_from)
    print(json.dumps({key: result[key] for key in ("status", "tasks", "samples", "pass_rate", "errors")}))
    raise SystemExit(0 if result["status"] == "complete" else 4)


if __name__ == "__main__":
    main()
