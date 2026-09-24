"""Fail-closed coverage gate for this explicitly bounded batch8/n1/epoch1 run."""

import argparse
import hashlib
import json
import shlex
from collections import defaultdict
from pathlib import Path

import torch
from replay import dense, replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--exit-file", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()
    command_file = args.directory.parent / "command.txt"
    command = dict(token.split("=", 1) for token in shlex.split(command_file.read_text()) if "=" in token)
    expected = {
        "data.train_batch_size": "8",
        "actor_rollout_ref.rollout.n": "1",
        "actor_rollout_ref.actor.ppo_epochs": "1",
        "trainer.total_training_steps": "1",
        "actor_rollout_ref.actor.optim.lr_warmup_steps": "0",
    }
    command_ok = all(command.get(key) == value for key, value in expected.items())
    files = sorted(args.directory.glob("micro-*.pt"))
    groups = defaultdict(list)
    rows = 0
    temperatures, counts, checks = [], [], []
    for file in files:
        payload = torch.load(file, map_location="cpu", weights_only=False)
        data = payload["data"]
        mask = dense(data["response_mask"]).bool()
        rows += len(mask)
        counts.extend(mask.sum(-1).tolist())
        temperatures.append(float(data["temperature"]))
        parts = file.stem.split("-")
        groups[parts[1]].append(int(parts[2]))
        checks.append(replay(file))
    calls_ok = bool(groups) and all(sorted(v) == list(range(1, len(v) + 1)) and len(v) < 64 for v in groups.values())
    exit_code = int(args.exit_file.read_text().strip())
    shards = list(args.checkpoint.glob("actor/model_world_size_*_rank_*.pt"))
    checkpoint_ok = (
        args.checkpoint.name == "global_step_1" and bool(shards) and all(p.stat().st_size > 0 for p in shards)
    )
    passed = (
        command_ok
        and rows == 8
        and len(counts) == 8
        and all(c > 0 for c in counts)
        and calls_ok
        and exit_code == 0
        and checkpoint_ok
        and all(abs(t - 0.8) < 1e-6 for t in temperatures)
        and bool(checks)
        and all(r["passed"] for r in checks)
    )
    result = {
        "passed": passed,
        "scope": "batch8,n1,ppo_epochs1,one update; no inference to larger runs",
        "command_verified": command_ok,
        "command_expected": expected,
        "command_sha256": hashlib.sha256(command_file.read_bytes()).hexdigest(),
        "captured_rows": rows,
        "valid_tokens_per_row": counts,
        "microbatch_calls": dict(groups),
        "calls_contiguous_below_cap": calls_ok,
        "actor_temperatures": temperatures,
        "train_exit_code": exit_code,
        "exit_file": str(args.exit_file),
        "exit_file_sha256": hashlib.sha256(args.exit_file.read_bytes()).hexdigest(),
        "checkpoint": str(args.checkpoint),
        "checkpoint_model_shards": [str(p) for p in shards],
        "checkpoint_present": checkpoint_ok,
        "all_microbatches_pass": all(r["passed"] for r in checks),
        "teacher_temperature_note": "Teacher temperature1 requires launch config plus source SHA evidence",
    }
    (args.directory / "coverage-verdict.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
