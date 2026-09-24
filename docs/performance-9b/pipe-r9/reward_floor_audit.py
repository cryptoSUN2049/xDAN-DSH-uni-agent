"""SWE do-nothing reward floor per task, and where a run's SWE trials sit relative to it.

Under HARBOR_REWARD_MODE=pass_ratio an unresolved trial scores passed/total CTRF tests.
SWE-rebench tasks count pass_to_pass tests, so changing nothing scores
|P2P| / (|F2P| + |P2P|). Read-only; run on the pod:

    python reward_floor_audit.py [DATA_ROOT] [RUN_ROOT]
"""

import collections
import glob
import json
import os
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "/workspace/verl-uni-agent-harbor-opd-rl/data-pipe-r9/stage1"
RUN = sys.argv[2] if len(sys.argv) > 2 else "/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r9"


def floors(data_root):
    out = {}
    for split in ("tasks-train", "tasks-validation"):
        for task_dir in glob.glob(f"{data_root}/{split}/*swe-rebench*"):
            expected = json.load(open(task_dir + "/tests/expected.json"))
            f2p, p2p = len(expected["fail_to_pass"]), len(expected["pass_to_pass"])
            out[os.path.basename(task_dir)] = (p2p / (f2p + p2p), f2p + p2p, split)
    return out


def classify(ratio, floor):
    if ratio == 1.0:
        return "resolved"
    if abs(ratio - floor) < 1e-6:
        return "at_floor"
    return "above_floor" if ratio > floor else "below_floor"


def main():
    floor = floors(DATA)
    train = sorted(v[0] for v in floor.values() if v[2] == "tasks-train")
    n = len(train)
    print(f"SWE train tasks {n}; floor p10/p50/p90: {train[n // 10]:.3f} {train[n // 2]:.3f} {train[int(n * 0.9)]:.3f}")
    print(f"  floor>=0.9: {sum(x >= 0.9 for x in train)}  floor>=0.5: {sum(x >= 0.5 for x in train)}")
    print(f"  floor==0: {sum(x == 0 for x in train)}")
    print("SWE validation floors:", {k[-40:]: round(v[0], 3) for k, v in floor.items() if v[2] == "tasks-validation"})

    logs = f"{RUN}/train/agent-logs/*/*"
    reports = glob.glob(f"{logs}/step_*/session-*/harbor/verifier/ctrf.json")
    reports += glob.glob(f"{logs}/validation*/session-*/harbor/verifier/ctrf.json")
    print("ctrf reports", len(reports))
    stats = collections.Counter()
    for report in reports:
        trial = report.split("/verifier/")[0]
        task = os.path.basename(json.load(open(trial + "/config.json"))["task"]["path"])
        summary = json.load(open(report))["results"]["summary"]
        ratio = summary["passed"] / summary["tests"] if summary["tests"] else 0.0
        if task in floor:
            task_floor, n_tests, _ = floor[task]
            stats["SWE ctrf_count_mismatch"] += summary["tests"] != n_tests
            stats["SWE " + classify(ratio, task_floor)] += 1
        else:
            stats["TL " + ("resolved" if ratio == 1.0 else "partial")] += 1
    for key in sorted(stats):
        print(key, stats[key])


if __name__ == "__main__":
    main()
