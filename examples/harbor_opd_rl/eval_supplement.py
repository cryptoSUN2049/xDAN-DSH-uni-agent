"""One bounded supplement of infrastructure-missing evaluation samples, preserving source evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def plan_missing(receipt, per_task):
    if receipt.get("process_exit") != 0 or receipt.get("checkpoint_loaded") is not True:
        raise ValueError("source process/checkpoint not verified")
    if receipt.get("unexpected_task_ids"):
        raise ValueError("unexpected source task identities")
    n = receipt["expected_n"]
    plan = {}
    mismatches = receipt["sample_count_mismatches"]
    for task, count in mismatches.items():
        key = task.rsplit("/", 1)[-1]
        missing = n - count
        if missing <= 0 or receipt.get("infra_incomplete", {}).get(key, 0) != missing:
            raise ValueError(f"{task}: missing samples not exactly explained by infrastructure failures")
        if len(per_task.get(key, [])) != count:
            raise ValueError("receipt and source results disagree")
        plan.setdefault(missing, []).append(task)
    if not plan:
        raise ValueError("no infrastructure samples to supplement")
    for key, values in per_task.items():
        if any(value not in (0, 1) for value in values):
            raise ValueError("nonbinary source reward")
        if len(values) != n and key not in {x.rsplit("/", 1)[-1] for x in mismatches}:
            raise ValueError("unreported incomplete task")
    return plan


def merge_results(source, extra, n):
    merged = {key: list(values) for key, values in source.items()}
    for key, values in extra.items():
        merged.setdefault(key, []).extend(values)
    if any(len(values) != n or any(x not in (0, 1) for x in values) for values in merged.values()):
        raise ValueError("supplement did not produce exactly n binary outcomes per task")
    return merged


def coverage_adjusted_rate(per_task, expected_tasks, n):
    """Framework resolved outcomes; missing trials contribute zero in the fixed denominator."""
    return sum(sum(values) for values in per_task.values()) / (expected_tasks * n)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def link_logs(source, destination):
    # Link individual files: Path.rglob does not descend into symlinked directories.
    for path in (source / "agent-logs").rglob("*"):
        if path.is_file():
            target = destination / path.relative_to(source / "agent-logs")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, target)
            except OSError:
                target.symlink_to(path.resolve())


def model_identity(receipt, config, run):
    checkpoint = receipt["resume_from"]
    if config["resume_from"] != checkpoint:
        raise ValueError("checkpoint identity mismatch")
    model = Path(config["model_path"]).resolve()
    identity = {"model_path": str(model), "model_config_sha256": digest(model / "config.json")}
    if checkpoint:
        if not run or not Path(checkpoint).resolve().is_relative_to(Path(run).resolve()):
            raise ValueError("checkpoint is outside requested training run")
        identity.update(
            kind="checkpoint",
            checkpoint=checkpoint,
            checkpoint_model_sha256=digest(Path(checkpoint) / "actor/model_world_size_1_rank_0.pt"),
        )
    else:
        identity.update(kind="base", checkpoint="")
    return identity


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--gpu", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--python", required=True)
    args = ap.parse_args()
    source = args.source.resolve()
    out = args.output.resolve()
    receipt = load(source / "validation.json")
    summary = load(source / "summary.json")
    config = load(source / "eval-config.json")
    plan = plan_missing(receipt, summary["per_task"])
    identity = model_identity(receipt, config, args.run)
    data = Path(receipt["data"])
    checkpoint = receipt["resume_from"]
    if Path(config["data"]).resolve() != data.resolve() or config["n"] != receipt["expected_n"]:
        raise ValueError("data or sampling identity mismatch")
    import pandas as pd

    frame = pd.read_parquet(data)
    ids = frame.extra_info.map(lambda x: x["tools_kwargs"]["task"]["metadata"]["instance_id"])
    if len(ids) != receipt["expected_tasks"] or ids.nunique() != len(ids):
        raise ValueError("source data task identity/count changed")
    expected = {task.rsplit("/", 1)[-1] for task in ids}
    missing_names = {task.rsplit("/", 1)[-1] for tasks in plan.values() for task in tasks}
    if set(summary["per_task"]) | missing_names != expected:
        raise ValueError("source results do not match parquet identity")
    out.mkdir(parents=True, exist_ok=False)
    provenance = {
        "source": str(source),
        "source_summary_sha256": digest(source / "summary.json"),
        "source_validation_sha256": digest(source / "validation.json"),
        "data": str(data),
        "data_sha256": digest(data),
        "checkpoint": checkpoint,
        "model_identity": identity,
        "source_coverage_adjusted_framework_rate": coverage_adjusted_rate(
            summary["per_task"], receipt["expected_tasks"], receipt["expected_n"]
        ),
        "rate_definition": "framework resolved; fixed expected_tasks * expected_n denominator; missing=0",
        "replaced_infra": receipt["infra_incomplete"],
        "plan": plan,
        "supplements": [],
    }
    provenance_file = out / "provenance.json"
    provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    extra = {}
    roots = [source]
    script = Path(__file__).resolve().parent
    for n, tasks in sorted(plan.items()):
        subset = out / f"tasks-n{n}.parquet"
        selected = frame.loc[ids.isin(tasks)]
        if len(selected) != len(tasks):
            raise ValueError("missing task identity in original parquet")
        selected.to_parquet(subset, index=False)
        dest = out / f"supplement-n{n}"
        env = os.environ | {
            "LANE_PY": args.python,
            "EVAL_ROOT": str(dest),
            "EVAL_RUN": args.run,
            "EVAL_DATA": str(subset),
            "EVAL_N": str(n),
            "EVAL_LIMIT": "0",
            "RESUME_FROM": checkpoint,
            "MODEL_PATH": config["model_path"],
            "TASK_CONFIG": config["task_config"],
            "CUDA_VISIBLE_DEVICES": args.gpu,
            "KEEP_GPU_PROCESS": os.environ.get("KEEP_GPU_PROCESS", "1"),
        }
        with (out / f"supplement-n{n}.log").open("w") as log:
            result = subprocess.run(
                ["bash", str(script / "eval_val_only.sh")], env=env, stdout=log, stderr=subprocess.STDOUT
            )
        provenance["supplements"].append(
            {"output": str(dest), "data_sha256": digest(subset), "returncode": result.returncode}
        )
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
        if result.returncode or load(dest / "validation.json")["status"] != "complete":
            raise SystemExit("Supplement incomplete; no further retry authorized by this invocation")
        added = load(dest / "summary.json")["per_task"]
        if set(added) != {task.rsplit("/", 1)[-1] for task in tasks}:
            raise ValueError("supplement task identity mismatch")
        extra.update(added)
        provenance["supplements"][-1]["summary_sha256"] = digest(dest / "summary.json")
        roots.append(dest)
    merged = merge_results(summary["per_task"], extra, receipt["expected_n"])
    for index, root in enumerate(roots):
        link_logs(root, out / "agent-logs" / str(index))
    (out / "eval.log").write_text("\n".join((root / "eval.log").read_text(errors="replace") for root in roots))
    shutil.copy2(source / "eval-config.json", out / "eval-config.json")
    result = subprocess.run(
        [
            args.python,
            str(script / "eval_result_check.py"),
            "--root",
            str(out),
            "--data",
            str(data),
            "--n",
            str(receipt["expected_n"]),
            "--process-exit",
            "0",
            "--resume-from",
            checkpoint,
        ]
    )
    if result.returncode or load(out / "summary.json")["per_task"] != merged:
        raise SystemExit("Aggregate failed independent validation")
    provenance["aggregate_framework_rate"] = coverage_adjusted_rate(
        merged, receipt["expected_tasks"], receipt["expected_n"]
    )
    provenance["status"] = "complete"
    provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
