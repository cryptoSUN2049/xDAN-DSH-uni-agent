"""Bounded overnight pipeline. Every subprocess failure remains visible in HTML."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/workspace/verl-uni-agent-harbor-opd-rl")
HERE = Path(__file__).resolve().parent
DATA = ROOT / "data-overnight-opd-20260924-v2"
BASE = "/workspace/models/Qwen3.5-9B"
TEACHER = "/workspace/models/Qwen3.8-27B"
PYTHON = str(ROOT / "envs/ua-verl-py312-vllm023-ws1/bin/python")
STATE = {
    "objective": "多领域单教师OPD：27B → 9B",
    "stages": [],
    "models": [
        {"id": "base-9b", "role": "baseline", "path": BASE},
        {"id": "teacher-27b", "role": "teacher", "path": TEACHER},
    ],
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _report():
    from summarize import summarize

    summarize(HERE)
    STATE["updated_at"] = stamp()
    temp = HERE / "state.tmp"
    temp.write_text(json.dumps(STATE, ensure_ascii=False, indent=2))
    temp.replace(HERE / "state.json")
    subprocess.run([sys.executable, str(HERE / "report.py")], check=True, stdout=subprocess.DEVNULL)


def report():
    # Reporting must not orphan the owned training process on a transient read error.
    try:
        _report()
    except Exception as error:
        with (HERE / "report-errors.log").open("a") as log:
            log.write(f"{stamp()} {type(error).__name__}: {error}\n")
        print(f"Report refresh failed: {type(error).__name__}: {error}", flush=True)


def stage(name, command, timeout, env=None):
    record = {"name": name, "status": "running", "started_at": stamp()}
    STATE["stages"].append(record)
    report()
    with (HERE / f"{name}.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        record["pid"] = process.pid
        report()
        start = time.monotonic()
        while process.poll() is None:
            if time.monotonic() - start > timeout:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                record["reason"] = "Bounded stage timed out; own process group terminated"
                break
            time.sleep(10)
            report()
        record["exit_code"] = process.returncode
        record["status"] = "complete" if process.returncode == 0 else "failed"
        record["finished_at"] = stamp()
        if process.returncode != 0 and not record.get("reason"):
            record["reason"] = f"See {name}.log; exit={process.returncode}"
    report()
    return process.returncode == 0


def main():
    environment = os.environ.copy()
    environment.update(
        VIRTUAL_ENV=str(ROOT / "envs/ua-verl-py312-vllm023-ws1"),
        UV_PROJECT_ENVIRONMENT=str(ROOT / "envs/ua-verl-py312-vllm023-ws1"),
        PYTHONNOUSERSITE="1",
        PATH=str(ROOT / "envs/ua-verl-py312-vllm023-ws1/bin") + ":" + os.environ.get("PATH", ""),
        VLLM_USE_FLASHINFER_SAMPLER="0",
        HF_HUB_DISABLE_PROGRESS_BARS="1",
        TOKENIZERS_PARALLELISM="false",
        WANDB_MODE="offline",
        PYTHONPATH=str(ROOT / "src/uni-agent") + ":" + str(ROOT / "src/uni-agent/verl"),
    )
    compatibility = json.loads((HERE / "compatibility/report.json").read_text())
    if not compatibility.get("scoring_gate_passed"):
        raise RuntimeError("Compatibility scoring gate not passed")
    STATE["stages"].append({"name": "compatibility", "status": "complete", "reason": "See compatibility evidence"})
    used = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True
    )
    if any(int(x) > 2000 for x in used.splitlines()):
        raise RuntimeError("GPU busy: will not kill other jobs")
    smoke = ROOT / "runs/overnight-opd-20260924-attempt2-smoke"
    full = ROOT / "runs/overnight-opd-20260924-attempt2"
    smoke_env = {**environment, "RUN": str(smoke), "STEPS": "1", "RESPONSE": "1024", "WARMUP": "0"}
    smoke_ok = stage("train-smoke", ["bash", str(HERE / "train.sh")], 3600, smoke_env)
    if smoke_ok:
        smoke_ok = stage(
            "export-smoke",
            [
                PYTHON,
                str(HERE / "export_checkpoints.py"),
                "--checkpoints",
                str(smoke / "checkpoints"),
                "--out",
                str(HERE / "adapters-smoke"),
                "--base-model",
                BASE,
            ],
            900,
            environment,
        )
    if smoke_ok:
        manifest = json.loads((HERE / "adapters-smoke/manifest.json").read_text())
        adapter = manifest["checkpoints"][-1]["adapter"]
        smoke_ok = stage(
            "reload-smoke",
            [
                PYTHON,
                str(HERE / "evaluate.py"),
                "--model",
                BASE,
                "--model-id",
                "smoke-step1",
                "--data",
                str(DATA / "val.parquet"),
                "--out",
                str(HERE / "models/smoke-step1"),
                "--adapter",
                adapter,
                "--max-tokens",
                "4096",
            ],
            3600,
            {**environment, "CUDA_VISIBLE_DEVICES": "0"},
        )
    if smoke_ok:
        stage(
            "train-full",
            ["bash", str(HERE / "train.sh")],
            14400,
            {**environment, "RUN": str(full), "STEPS": "16", "RESPONSE": "1024"},
        )
        stage(
            "export-full",
            [
                PYTHON,
                str(HERE / "export_checkpoints.py"),
                "--checkpoints",
                str(full / "checkpoints"),
                "--out",
                str(HERE / "adapters"),
                "--base-model",
                BASE,
            ],
            1200,
            environment,
        )
    candidates = [("base-9b", BASE, None), ("teacher-27b", TEACHER, None)]
    manifest_path = HERE / "adapters/manifest.json"
    if manifest_path.exists():
        for row in json.loads(manifest_path.read_text())["checkpoints"]:
            if row["status"] == "exported":
                candidates.append((f"opd-step{row['step']}", BASE, row["adapter"]))
    for name, model, adapter in candidates:
        if adapter:
            STATE["models"].append({"id": name, "role": "trained checkpoint", "path": model, "adapter": adapter})
        command = [
            PYTHON,
            str(HERE / "evaluate.py"),
            "--model",
            model,
            "--model-id",
            name,
            "--data",
            str(DATA / "val.parquet"),
            "--out",
            str(HERE / "models" / name),
            "--max-tokens",
            "4096",
        ]
        if adapter:
            command += ["--adapter", adapter]
        stage("eval-" + name, command, 3600, {**environment, "CUDA_VISIBLE_DEVICES": "0"})
    STATE["finished_at"] = stamp()
    STATE["result"] = "Inspect individual stage statuses; failed stages are not completion"
    report()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        STATE["stages"].append({"name": "pipeline", "status": "failed", "reason": f"{type(error).__name__}: {error}"})
        report()
        raise
