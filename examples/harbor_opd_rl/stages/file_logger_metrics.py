"""Step-metrics lines from VERL file-logger files, for runs whose console step lines are missing.

    python examples/harbor_opd_rl/stages/file_logger_metrics.py <stage_dir>

VERL prints one "step:N - key:value - ..." console line per step from a Ray actor; the
lines are buffered, and S1 (2026-09-19) stopped showing them after step 9. The file logger
writes every step as {"step": N, "data": {...}}. 40_train.sh points it at one file per
attempt (<stage_dir>/metrics-<start UTC>.jsonl) because VERL opens the file with "wb",
so a resume would otherwise overwrite the earlier attempt. Files are read in name order
(start time); a step present in two attempts keeps the later one. Rows without
training/global_step (the validation before training) are skipped, as in the console.
Prints the console format so metrics_json (common.sh) parses both the same way.
"""

from __future__ import annotations

import glob
import json
import os
import sys


def step_rows(stage_dir: str) -> dict[int, dict]:
    steps: dict[int, dict] = {}
    for path in sorted(glob.glob(os.path.join(stage_dir, "metrics-*.jsonl"))):
        with open(path) as f:
            for line in f:
                try:
                    data = json.loads(line).get("data") or {}
                except (ValueError, AttributeError):
                    continue  # a line cut short by a killed process
                step = data.get("training/global_step")
                if isinstance(step, (int, float)) and not isinstance(step, bool):
                    steps[int(step)] = data
    return steps


def console_lines(steps: dict[int, dict]) -> list[str]:
    lines = []
    for step in sorted(steps):
        items = [f"{k}:{v}" for k, v in steps[step].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        lines.append(f"step:{step} - " + " - ".join(items))
    return lines


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    for line in console_lines(step_rows(sys.argv[1])):
        print(line)


if __name__ == "__main__":
    main()
