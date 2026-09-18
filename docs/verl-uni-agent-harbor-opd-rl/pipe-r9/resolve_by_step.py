"""Binary resolve rate per training step and source for a pipe run, next to the base 9B rates.

Steps are assigned by comparing each trial's finish time with the checkpoint directory
mtimes. Read-only; run on the pod:

    python resolve_by_step.py /workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r9
"""

import collections
import datetime as dt
import glob
import os
import re
import sys

BASE = {"swe": 0.33, "terminal-lego": 0.52}  # data line 5e: base 9B on SWE easy / TL medium
DONE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d).*Harbor trial done: instance_id=(\S+) "
    r"reward=([0-9.]+) resolved=(\w+) elapsed=([0-9.]+)s"
)


def main(run):
    rows = []
    for log in glob.glob(f"{run}/train/agent-logs/**/task.log", recursive=True):
        for line in open(log, errors="replace"):
            match = DONE.search(line)
            if match:
                finished = dt.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                resolved = match.group(4) == "True"
                rows.append((finished, match.group(2), float(match.group(3)), resolved, float(match.group(5))))
    checkpoints = sorted(
        (dt.datetime.utcfromtimestamp(os.path.getmtime(d)), int(d.rsplit("_", 1)[1]))
        for d in glob.glob(f"{run}/train/checkpoints/*/*/global_step_*")
    )

    def step_of(finished):
        for saved, step in checkpoints:
            if finished <= saved:
                return step
        return checkpoints[-1][1] + 1 if checkpoints else 1

    agg = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
    for finished, instance, reward, resolved, elapsed in rows:
        source = "terminal-lego" if "terminal-lego" in instance else "swe"
        phase = "val" if instance.startswith("tasks-validation/") else f"step{step_of(finished):02d}"
        cell = agg[(phase, source)]
        cell[0] += 1
        cell[1] += resolved
        cell[2] += reward
        cell[3] += elapsed
    print(f"{'phase':8} {'source':14} {'n':>3} {'resolved':>9} {'base':>5} {'reward':>7} {'avg_s':>6}")
    for (phase, source), (n, k, reward, elapsed) in sorted(agg.items()):
        print(f"{phase:8} {source:14} {n:>3} {k / n:>9.2f} {BASE[source]:>5.2f} {reward / n:>7.3f} {elapsed / n:>6.0f}")


if __name__ == "__main__":
    main(sys.argv[1])
