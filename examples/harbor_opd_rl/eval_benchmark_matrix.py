"""Serial, resumable cross-benchmark evaluation; never rerun valid failed answers."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_name(phase, benchmark, version):
    return phase[0] + "-" + hashlib.sha256(f"{phase}/{benchmark}/{version}".encode()).hexdigest()[:16]


def jobs(dataset, versions, probe_only=False):
    return [
        {
            "phase": phase,
            "dataset": dataset["label"],
            "version": version,
            "name": run_name(phase, dataset["label"], version["label"]),
            "status": "pending",
        }
        for phase in (("probe",) if probe_only else ("probe", "full"))
        for version in versions
    ]


def check_stop(cfg):
    if cfg.get("stop_file") and Path(cfg["stop_file"]).exists():
        raise RuntimeError(f"budget/operator stop file exists: {cfg['stop_file']}")


def complete(root, ids, data, n, checkpoint, task_config, model):
    try:
        receipt = read(root / "validation.json")
        config = read(root / "eval-config.json")
        result = read(root / "summary.json")["per_task"]
        return (
            receipt["status"] == "complete"
            and receipt["process_exit"] == 0
            and receipt["checkpoint_loaded"] is True
            and receipt["resume_from"] == checkpoint
            and receipt["data"] == str(data)
            and receipt["expected_n"] == n
            and receipt["expected_tasks"] == len(ids)
            and not receipt["unexpected_task_ids"]
            and not receipt["sample_count_mismatches"]
            and config["data"] == str(data)
            and config["resume_from"] == checkpoint
            and config["task_config"] == task_config
            and config["model_path"] == model
            and config["n"] == n
            and config["tasks"] == len(ids)
            and set(result) == {x.rsplit("/", 1)[-1] for x in ids}
            and all(len(v) == n and all(x in (0, 1) for x in v) for v in result.values())
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def wait_gpu(cfg):
    deadline = time.monotonic() + cfg.get("gpu_wait_seconds", 43200)
    while True:
        check_stop(cfg)
        result = subprocess.run(
            ["nvidia-smi", "-i", str(cfg["gpu"]), "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip().isdigit() and int(result.stdout.strip()) < 2000:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("GPU wait expired; existing outputs preserved")
        time.sleep(30)


def launch(command, env, logfile):
    with logfile.open("w") as log:
        return subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT).returncode


def validate_dataset(dataset):
    import pandas as pd

    for key, hashkey in [("data", "sha256"), ("task_config", "task_config_sha256")]:
        if sha(dataset[key]) != dataset[hashkey]:
            raise ValueError(f"{key} hash mismatch: {dataset['label']}")
    frame = pd.read_parquet(dataset["data"])
    ids = frame.extra_info.map(lambda x: x["tools_kwargs"]["task"]["metadata"]["instance_id"]).tolist()
    if len(ids) != dataset["tasks"] or len(set(ids)) != len(ids):
        raise ValueError("dataset count/identity not unique")
    if len({x.rsplit("/", 1)[-1] for x in ids}) != len(ids):
        raise ValueError("basename collisions prevent paired reports")
    if len(dataset["probe_ids"]) != 3 or len(set(dataset["probe_ids"])) != 3:
        raise ValueError("exactly three distinct fixed probe_ids required")
    if not set(dataset["probe_ids"]) <= set(ids) or dataset["n"] < 1:
        raise ValueError("invalid probe selection or n")
    return frame, ids


def run_job(cfg, dataset, job, data, ids, n, root, script):
    version = job["version"]
    checkpoint = version.get("checkpoint", "")
    model = cfg["env"]["MODEL_PATH"]
    raw = root / job["name"]
    aggregate = root / ("a-" + job["name"])
    arguments = (ids, data, n, checkpoint, dataset["task_config"], model)
    launch_receipt = root / (job["name"] + "-launch.json")
    if launch_receipt.exists() and read(launch_receipt).get("returncode") not in (0, 4):
        raise RuntimeError("prior launch failed or interrupted; diagnosis required")
    for candidate in (aggregate, raw):
        if complete(candidate, *arguments):
            job.update(status="complete", output=str(candidate))
            return candidate
    env = (
        os.environ
        | cfg["env"]
        | {
            "LANE_PY": cfg["python"],
            "EVAL_ROOT": str(raw),
            "EVAL_RUN": version.get("run", ""),
            "RESUME_FROM": checkpoint,
            "EVAL_DATA": str(data),
            "EVAL_LIMIT": "0",
            "EVAL_N": str(n),
            "TASK_CONFIG": dataset["task_config"],
            "CUDA_VISIBLE_DEVICES": str(cfg["gpu"]),
            "KEEP_GPU_PROCESS": "1",
            "CKPT_LOAD_CONTENTS": "model",
        }
    )
    launch_receipt = root / (job["name"] + "-launch.json")
    if launch_receipt.exists():
        prior = read(launch_receipt)
        if prior.get("returncode") not in (0, 4):
            raise RuntimeError("prior launch failed or interrupted; refusing automatic full restart")
    if not raw.exists():
        if launch_receipt.exists():
            raise RuntimeError("attempt already launched without output; diagnosis required")
        wait_gpu(cfg)
        save(launch_receipt, {"status": "started"})
        code = launch(["bash", str(script / "eval_val_only.sh")], env, root / (job["name"] + ".log"))
        job["returncode"] = code
        save(launch_receipt, {"status": "exited", "returncode": code})
        if code not in (0, 4):
            raise RuntimeError(f"evaluation process failed with exit {code}")
    if complete(raw, *arguments):
        job.update(status="complete", output=str(raw))
        return raw
    # No second full attempt. The supplement validates that ALL missing samples are infra.
    if not (raw / "validation.json").exists() or not (raw / "summary.json").exists():
        raise RuntimeError("original attempt has no validation evidence; never rerun automatically")
    receipt = read(raw / "validation.json")
    summary = read(raw / "summary.json")
    if not summary.get("samples") or receipt.get("process_exit") != 0 or not receipt.get("checkpoint_loaded"):
        raise RuntimeError("zero samples or failed engine/checkpoint: stopped for diagnosis")
    if aggregate.exists():
        raise RuntimeError("one supplement already attempted but incomplete; bounded retry exhausted")
    from eval_supplement import plan_missing

    plan_missing(receipt, summary["per_task"])
    wait_gpu(cfg)
    code = launch(
        [
            cfg["python"],
            str(script / "eval_supplement.py"),
            "--source",
            str(raw),
            "--output",
            str(aggregate),
            "--gpu",
            str(cfg["gpu"]),
            "--run",
            version.get("run", ""),
            "--python",
            cfg["python"],
        ],
        env,
        root / ("a-" + job["name"] + ".log"),
    )
    job["supplement_returncode"] = code
    if code or not complete(aggregate, *arguments):
        raise RuntimeError("supplement did not complete; no further automatic retries")
    job.update(status="complete", output=str(aggregate))
    return aggregate


def behavior_report(python, script, baseline, output, label):
    runs = [f"base={baseline}"]
    if label != "base":
        runs.append(f"{label}={output}")
    subprocess.run(
        [python, str(script / "eval_behavior_report.py"), *runs, "--out", str(output / "behavior.json")], check=True
    )


def write_report(path, state):
    lines = [
        "# Cross-benchmark evaluation",
        "",
        "Framework resolved rates. Probe scores are not used to gate or select checkpoints.",
        "",
        "| Benchmark | Phase | Model | Status | Rate | Difference vs base | 95% CI | Output / Error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for job in state:
        stats = job.get("comparison", {})
        rate = f"{job['rate']:.2%}" if "rate" in job else "—"
        detail = str(job.get("error", job.get("output", "—"))).replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {job['dataset']} | {job['phase']} | {job['version']['label']} | {job['status']} | "
            f"{rate} | {stats.get('diff', '—')} | {stats.get('ci95', '—')} | {detail} |"
        )
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--benchmark")
    ap.add_argument("--probe-only", action="store_true", help="run only the three model probes; no full evaluations")
    args = ap.parse_args()
    cfg = read(args.manifest)
    if [v["label"] for v in cfg["versions"]] != ["base", "opd12", "rl60"]:
        raise ValueError("versions must be ordered base, opd12, rl60")
    if cfg["versions"][0].get("checkpoint") or any(not v.get("checkpoint") for v in cfg["versions"][1:]):
        raise ValueError("base must have no checkpoint; trained versions must have checkpoints")
    root = Path(cfg["output"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / "queue.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    identity = root / "manifest.sha256"
    digest = sha(args.manifest)
    if identity.exists() and identity.read_text().strip() != digest:
        raise ValueError("manifest changed; use a fresh output root")
    identity.write_text(digest + "\n")
    save(root / "manifest.json", cfg)
    selected = [d for d in cfg["datasets"] if args.benchmark is None or d["label"] == args.benchmark]
    if not selected:
        raise ValueError("selected benchmark absent")
    if len({d["label"] for d in cfg["datasets"]}) != len(cfg["datasets"]):
        raise ValueError("duplicate benchmark label")
    state = [j for dataset in selected for j in jobs(dataset, cfg["versions"], probe_only=args.probe_only)]
    state_path = root / ("status-" + (args.benchmark or "all") + ("-probe" if args.probe_only else "") + ".json")
    report_path = root / ("report-probe.md" if args.probe_only else "report.md")
    save(state_path, state)
    write_report(report_path, state)
    script = Path(__file__).resolve().parent
    for dataset in selected:
        frame, full_ids = validate_dataset(dataset)
        probe = root / (run_name("dataset", dataset["label"], "probe") + ".parquet")
        mask = frame.extra_info.map(lambda x: x["tools_kwargs"]["task"]["metadata"]["instance_id"]).isin(
            dataset["probe_ids"]
        )
        if not probe.exists():
            frame.loc[mask].to_parquet(probe, index=False)
        else:
            import pandas as pd

            if pd.read_parquet(probe).to_json() != frame.loc[mask].reset_index(drop=True).to_json():
                raise ValueError("existing probe data changed")
        baseline = None
        for job in [x for x in state if x["dataset"] == dataset["label"]]:
            try:
                check_stop(cfg)
                # Recheck original artifacts before every launch/resume.
                validate_dataset(dataset)
                is_probe = job["phase"] == "probe"
                job.update(status="running")
                save(state_path, state)
                output = run_job(
                    cfg,
                    dataset,
                    job,
                    probe if is_probe else Path(dataset["data"]),
                    dataset["probe_ids"] if is_probe else full_ids,
                    1 if is_probe else dataset["n"],
                    root,
                    script,
                )
                if not is_probe:
                    per_task = read(output / "summary.json")["per_task"]
                    job["rate"] = sum(sum(v) / len(v) for v in per_task.values()) / len(per_task)
                    if job["version"]["label"] == "base":
                        baseline = output
                    else:
                        subprocess.run(
                            [
                                cfg["python"],
                                str(script / "eval_pair_report.py"),
                                str(baseline / "summary.json"),
                                str(output / "summary.json"),
                                "--labels",
                                "base",
                                job["version"]["label"],
                                "--out",
                                str(output / "pair.json"),
                            ],
                            check=True,
                        )
                        job["comparison"] = read(output / "pair.json")["groups"]["all"]
                    behavior_report(cfg["python"], script, baseline, output, job["version"]["label"])
                save(state_path, state)
                write_report(report_path, state)
            except Exception as exc:
                job.update(status="blocked", error=str(exc))
                save(state_path, state)
                write_report(report_path, state)
                raise


if __name__ == "__main__":
    main()
