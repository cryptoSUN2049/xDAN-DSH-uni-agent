"""Pull a wandb run's config and per-step metrics into JSON for training analysis.

Usage:
  python wandb_pull.py <run_url | entity/project/run_id> [--out metrics.json] [--train-log train.log]

With --train-log, the console `step:N - ...` lines are parsed and compared with
the wandb history (actor/grad_norm must agree within 1e-6), so the analysis is
anchored to the same data the dashboard shows.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys

KEYS = (
    "training/global_step",
    "critic/score/mean",
    "critic/score/max",
    "critic/score/min",
    "critic/rewards/mean",
    "actor/grad_norm",
    "actor/pg_loss",
    "actor/pg_clipfrac",
    "actor/entropy",
    "actor/ppo_kl",
    "actor/kl_loss",
    "response_length/mean",
    "response_length/clip_ratio",
    "timing_s/gen",
    "timing_s/update_actor",
    "timing_s/step",
    "val/test_score",
)
CONFIG_KEYS = (
    "trainer/total_training_steps",
    "trainer/total_epochs",
    "trainer/v1/trainer_mode",
    "data/train_batch_size",
    "actor_rollout_ref/rollout/n",
    "actor_rollout_ref/model/lora_rank",
    "actor_rollout_ref/actor/optim/lr",
    "actor_rollout_ref/actor/clip_ratio_high",
    "algorithm/filter_groups/enable",
)


def run_path(arg: str) -> str:
    if "wandb.ai/" in arg:
        entity, project, _, run_id = arg.split("wandb.ai/")[1].split("/")[:4]
        return f"{entity}/{project}/{run_id}"
    return arg


def parse_console(path: str) -> dict[int, dict[str, float]]:
    steps: dict[int, dict[str, float]] = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        if " - " not in line or "step:" not in line:
            continue
        pairs = dict(re.findall(r"([\w/\-]+):(-?[0-9.]+(?:e-?\d+)?)", line))
        if "training/global_step" not in pairs:
            continue
        step = int(float(pairs["training/global_step"]))
        steps[step] = {k: float(v) for k, v in pairs.items() if k in KEYS}
    return steps


def finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run")
    parser.add_argument("--out")
    parser.add_argument("--train-log")
    args = parser.parse_args()

    import wandb

    run = wandb.Api().run(run_path(args.run))
    flat_cfg = {}

    def flatten(prefix, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                flatten(f"{prefix}/{k}" if prefix else k, v)
        else:
            flat_cfg[prefix] = obj

    flatten("", run.config)
    history = [{k: h.get(k) for k in KEYS if h.get(k) is not None} for h in run.history(keys=list(KEYS), pandas=False)]
    history = [h for h in history if "training/global_step" in h]

    verdict = {
        "steps": len(history),
        "steps_with_reward_variance": [
            int(h["training/global_step"])
            for h in history
            if h.get("critic/score/max", 0) > h.get("critic/score/min", 0)
        ],
        "steps_with_nonzero_grad": [
            int(h["training/global_step"])
            for h in history
            if finite(h.get("actor/grad_norm")) and h["actor/grad_norm"] > 0
        ],
        "non_finite_steps": [
            int(h["training/global_step"])
            for h in history
            if not finite(h.get("actor/grad_norm", 0.0)) or not finite(h.get("actor/pg_loss", 0.0))
        ],
    }
    if args.train_log:
        console = parse_console(args.train_log)
        agree, disagree = [], []
        for h in history:
            s = int(h["training/global_step"])
            c = console.get(s)
            if (
                c
                and "actor/grad_norm" in c
                and abs(c["actor/grad_norm"] - h.get("actor/grad_norm", float("nan"))) < 1e-6
            ):
                agree.append(s)
            elif c:
                disagree.append(s)
        verdict["console_steps"] = sorted(console)
        verdict["wandb_console_agree"] = agree
        verdict["wandb_console_disagree"] = disagree

    out = {
        "run": {
            "path": run_path(args.run),
            "name": run.name,
            "state": run.state,
            "url": run.url,
            "created": str(run.created_at),
        },
        "config": {k: flat_cfg.get(k) for k in CONFIG_KEYS},
        "history": history,
        "verdict": verdict,
    }
    text = json.dumps(out, indent=1)
    if args.out:
        open(args.out, "w").write(text + "\n")
    print(text if not args.out else json.dumps(out["verdict"]))


if __name__ == "__main__":
    sys.exit(main())
