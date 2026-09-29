"""Run fixed VERL native colocated CUDA IPC tests independently on two GPUs."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

DEADLINE = 1790709401
SOURCES = (
    "tests/utils/test_bucketed_weight_transfer.py",
    "verl/workers/rollout/vllm_rollout/bucketed_weight_transfer.py",
    "verl/workers/engine_workers.py",
    "verl/checkpoint_engine/base.py",
    "verl/trainer/ppo/v1/trainer_base.py",
    "verl/trainer/ppo/v1/trainer_colocate_async.py",
)
CASES = ("test_large_weight", "test_mixed_dtypes")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lane(source, output, gpu):
    # Set visibility before importing either torch or the upstream test module.
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    sys.path.insert(0, str(source / "tests/utils"))
    import test_bucketed_weight_transfer as native
    import torch

    assert torch.cuda.is_available() and torch.cuda.device_count() == 1
    assert native.is_support_ipc()
    # Upstream functions, tensor checks and transport remain unchanged.
    native.PROCESS_TIMEOUT = 300
    gpu_uuid = str(torch.cuda.get_device_properties(0).uuid)
    expected_uuid = subprocess.check_output(
        ["nvidia-smi", "-i", str(gpu), "--query-gpu=uuid", "--format=csv,noheader"], text=True
    ).strip()
    assert uuid.UUID(gpu_uuid) == uuid.UUID(expected_uuid.removeprefix("GPU-")), (
        "CUDA visibility does not match intended physical GPU"
    )
    report = {
        "gpu_index": gpu,
        "gpu_uuid": expected_uuid,
        "torch_device_uuid": gpu_uuid,
        "pid": os.getpid(),
        "cases": [],
        "status": "running",
        "tests": 0,
        "skipped": 0,
        "errors": 0,
        "failures": 0,
    }
    try:
        test = native.TestBucketedWeightTransferIPC()
        for case in CASES:
            started = time.time()
            getattr(test, case)()
            report["cases"].append({"name": case, "status": "passed", "seconds": time.time() - started})
        report.update(status="passed", tests=2)
    except Exception as error:
        report.update(status="failed", errors=1, error_type=type(error).__name__, error=str(error)[:1000])
        raise
    finally:
        output.write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lane", type=int, choices=(0, 1))
    args = parser.parse_args()
    if args.lane is not None:
        lane(args.source, args.output, args.lane)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    budget = min(480, DEADLINE - 180 - started)
    assert budget >= 120, "insufficient authorized probe window"
    before = subprocess.check_output(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], text=True
    ).strip()
    assert not before, "GPU processes already present"
    devices = subprocess.check_output(["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"], text=True)
    assert devices.split() == ["0", "1"], "requires exactly two visible physical GPUs"
    report = {
        "schema": "mimo.dual-colocate-ipc.v1",
        "status": "running",
        "mode": "colocate_async",
        "backend": "naive",
        "gpu_indexes": [0, 1],
        "started_at": started,
        "deadline_unix": DEADLINE,
        "budget_seconds": budget,
        "operator_sha256": digest(Path(__file__)),
        "source_sha256": {"verl/" + name: digest(args.source / name) for name in SOURCES},
        "tests": 0,
        "skipped": 0,
        "failures": 0,
        "errors": 0,
        "scope": (
            "Two per-device native sender/receiver IPC lanes; names, shapes, dtypes and checksums checked. "
            "Not elementwise, FSDP world2, LoRA merge or model-training proof."
        ),
    }
    status = args.output / "status.json"
    status.write_text(json.dumps(report, indent=2) + "\n")
    processes = []
    logs = []
    try:
        for gpu in (0, 1):
            env = os.environ.copy()
            env.update(
                CUDA_VISIBLE_DEVICES=str(gpu),
                PYTHONDONTWRITEBYTECODE="1",
                OMP_NUM_THREADS="1",
                OPENBLAS_NUM_THREADS="1",
            )
            log = (args.output / f"lane{gpu}.log").open("x")
            logs.append(log)
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--source",
                str(args.source),
                "--output",
                str(args.output / f"lane{gpu}.json"),
                "--lane",
                str(gpu),
            ]
            processes.append(
                subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            )
        report["lane_pids"] = [p.pid for p in processes]
        for process in processes:
            code = process.wait(timeout=max(1, started + budget - time.time()))
            assert code == 0, f"native lane exited {code}"
        lanes = [json.loads((args.output / f"lane{gpu}.json").read_text()) for gpu in (0, 1)]
        assert all(item["status"] == "passed" and [c["name"] for c in item["cases"]] == list(CASES) for item in lanes)
        assert len({item["gpu_uuid"] for item in lanes}) == 2
        report.update(status="passed", tests=4, lanes=lanes)
    except Exception as error:
        report.update(status="failed", errors=1, error_type=type(error).__name__, error=str(error)[:1000])
        raise
    finally:
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for log in logs:
            log.close()
        report["finished_at"] = time.time()
        status.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
