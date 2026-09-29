"""Record bounded, read-only GPU evidence for an owned training run."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def query(fields, kind):
    result = subprocess.run(
        ["nvidia-smi", f"--query-{kind}={fields}", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    args = parser.parse_args()
    start = time.time()
    if not start < args.deadline <= start + 21600:
        raise ValueError("Require a future deadline within six hours")
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        while time.time() < args.deadline:
            row = {"run_id": args.run_id, "observed_at": time.time()}
            try:
                status = json.loads(args.status.read_text()) if args.status.exists() else {}
                if status and status.get("run_id") != args.run_id:
                    raise ValueError("Operator run identity mismatch")
                row["operator_status"] = status.get("status", "not_yet_created")
                row["gpus"] = query("index,uuid,utilization.gpu,memory.used,memory.total", "gpu")
                row["compute_processes"] = query("pid,gpu_uuid,used_memory", "compute-apps")
                row["process_names"] = {}
                for line in row["compute_processes"]:
                    pid = line.split(",", 1)[0].strip()
                    if pid.isdecimal():
                        comm = Path("/proc") / pid / "comm"
                        if comm.exists():
                            row["process_names"][pid] = comm.read_text().strip()
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                row["error_type"] = type(error).__name__
                row["error"] = str(error)[:300]
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            if row.get("operator_status") == "exited" or row.get("error_type") == "ValueError":
                break
            time.sleep(min(10, max(0, args.deadline - time.time())))


if __name__ == "__main__":
    main()
