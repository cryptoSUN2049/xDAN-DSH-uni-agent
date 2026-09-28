"""CPU-only SFT scalar forwarding; JSONL/W&B remain the full-history authority.

Gauge sends are at-least-once. A saved cursor proves accepted sends, never a
Prometheus scrape. Backend visibility must be verified independently.
"""

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import time
from pathlib import Path

ALLOWED = {
    "train/loss",
    "train/grad_norm",
    "train/lr",
    "train/lr(1e-3)",
    "train/mfu",
    "train/global_tokens",
    "train/total_tokens(B)",
    "perf/max_memory_allocated_gb",
    "perf/max_memory_reserved_gb",
    "perf/cpu_memory_used_gb",
    "train/step_time",
    "val/loss",
    "test/loss",
}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as handle:
        json.dump(value, handle, allow_nan=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def parse_record(raw):
    record = json.loads(raw)
    step = record.get("step")
    data = record.get("data")
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise ValueError("step must be a nonnegative integer")
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    selected = {}
    for key, value in data.items():
        if key not in ALLOWED:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric {key} must be numeric")
        if not math.isfinite(value):
            raise ValueError(f"metric {key} must be finite")
        selected[key] = value
    return step, selected


class Cursor:
    """Fail closed on prefix edits, replacement or truncation; retain half-lines."""

    def __init__(self, metrics, state):
        self.metrics = Path(metrics)
        self.state_path = Path(state)
        self.value = {
            "version": 1,
            "metrics": str(self.metrics.resolve()),
            "identity": None,
            "offset": 0,
            "prefix_sha256": hashlib.sha256(b"").hexdigest(),
            "records": 0,
            "latest": {},
            "step": -1,
        }
        if self.state_path.exists():
            saved = json.loads(self.state_path.read_text())
            if saved.get("version") != 1 or saved.get("metrics") != self.value["metrics"]:
                raise ValueError("cursor version or source mismatch")
            if (
                isinstance(saved.get("offset"), bool)
                or not isinstance(saved.get("offset"), int)
                or saved["offset"] < 0
                or not isinstance(saved.get("records"), int)
                or saved["records"] < 0
                or not isinstance(saved.get("latest"), dict)
            ):
                raise ValueError("invalid cursor state")
            for key, value in saved["latest"].items():
                if key not in ALLOWED | {"sft/global_step", "sft/last_update_unixtime"}:
                    raise ValueError("unknown persisted gauge")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("invalid persisted gauge")
            self.value = saved

    def drain(self, send):
        if not self.metrics.exists():
            if self.value["identity"] is not None:
                raise ValueError("metrics file disappeared")
            return 0
        count = 0
        with self.metrics.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            identity = [stat.st_dev, stat.st_ino]
            if self.value["identity"] not in (None, identity):
                raise ValueError("metrics file replaced")
            offset = self.value["offset"]
            if stat.st_size < offset:
                raise ValueError("metrics file truncated")
            digest = hashlib.sha256()
            remaining = offset
            while remaining:
                chunk = handle.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError("metrics file truncated during read")
                digest.update(chunk)
                remaining -= len(chunk)
            if digest.hexdigest() != self.value["prefix_sha256"]:
                raise ValueError("metrics prefix changed")
            while raw := handle.readline():
                if not raw.endswith(b"\n"):
                    break
                step, selected = parse_record(raw)
                if step < self.value["step"]:
                    raise ValueError("step regressed")
                latest = {**self.value["latest"], **selected}
                latest["sft/global_step"] = step
                latest["sft/last_update_unixtime"] = time.time()
                send(latest)
                digest.update(raw)
                self.value = {
                    **self.value,
                    "identity": identity,
                    "offset": handle.tell(),
                    "prefix_sha256": digest.hexdigest(),
                    "records": self.value["records"] + 1,
                    "latest": latest,
                    "step": step,
                }
                atomic_json(self.state_path, self.value)
                count += 1
            current = self.metrics.stat()
            if [current.st_dev, current.st_ino] != identity:
                raise ValueError("metrics file replaced during read")
        return count

    def assert_complete(self):
        if not self.metrics.exists() or not self.value["records"]:
            raise ValueError("training terminated without metrics")
        if self.metrics.stat().st_size != self.value["offset"]:
            raise ValueError("training terminated with an incomplete JSONL record")


def supervise(cursor, send, exit_code, stopped, poll=1, hold=35):
    """Restore gauges after source verification; drain terminal file before hold."""
    restored = False
    terminal_at = None
    while not stopped():
        count = cursor.drain(send)
        if not restored:
            if not count and cursor.value["latest"]:
                send(cursor.value["latest"])
            restored = True
        if Path(exit_code).exists():
            code = int(Path(exit_code).read_text().strip())
            cursor.assert_complete()
            if terminal_at is None or count:
                terminal_at = time.monotonic()
            if time.monotonic() - terminal_at >= hold:
                return code
        time.sleep(poll)
    raise InterruptedError("sidecar received termination signal")


class InsightSink:
    """Version-pinned adapter. Hub ACK is deliberately not called scrape proof."""

    def __init__(self, args):
        from importlib.metadata import version

        if version("rl-insight") != "0.3.0":
            raise RuntimeError("sidecar requires audited rl-insight==0.3.0")
        import ray
        import rl_insight
        from rl_insight import api

        self.ray = ray
        self.insight = rl_insight
        self.api = api
        if ray.is_initialized():
            raise RuntimeError("refusing an already initialized Ray runtime")
        os.environ["RL_INSIGHT_SERVER_URL"] = args.server_url
        ray.init(
            address="local",
            num_cpus=2,
            num_gpus=0,
            include_dashboard=False,
            object_store_memory=104857600,
            _memory=536870912,
            _temp_dir=str(Path(args.ray_temp_dir).resolve()),
        )
        try:
            rl_insight.init(
                project=args.project,
                experiment_name=args.experiment,
                config={"prometheus": {"metrics_report_port": args.metrics_port}},
            )
            if not api._STATE.enabled or api._STATE.client is None:
                raise RuntimeError("rl-insight initialization disabled monitoring")
            self.actor = api._STATE.client._actor
            self.last_status = self.barrier()
        except Exception:
            ray.shutdown()
            raise

    def barrier(self):
        return self.ray.get(self.actor.get_status.remote(), timeout=30)

    def __call__(self, values):
        for name, value in values.items():
            self.insight.metric_gauge(re.sub(r"[^a-zA-Z0-9_:]", "_", name), value)
        self.last_status = self.barrier()

    def close(self):
        self.insight.finish()
        self.ray.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("metrics", "state", "status", "exit-code", "experiment", "ray-temp-dir", "server-url"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--project", default="xDAN-performance-9b")
    parser.add_argument("--metrics-port", type=int, default=19092)
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("--scrape-seconds", type=float, default=15)
    parser.add_argument("--hold-seconds", type=float, default=35)
    args = parser.parse_args(argv)
    for name in ("poll_seconds", "scrape_seconds", "hold_seconds"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"{name} must be positive and finite")
    if not 1024 <= args.metrics_port <= 65535:
        parser.error("metrics-port must be between 1024 and 65535")
    hold = max(args.hold_seconds, 2 * args.scrape_seconds + args.poll_seconds)
    stopped = [False]
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda signum, frame: stopped.__setitem__(0, True))
    lock_path = Path(args.state).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    sink = None
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("sidecar already holds cursor lock", flush=True)
            return 2
        try:
            cursor = Cursor(args.metrics, args.state)
            sink = InsightSink(args)
            atomic_json(args.status, {"status": "running", "backend_verified": False})
            code = supervise(cursor, sink, args.exit_code, lambda: stopped[0], args.poll_seconds, hold)
            atomic_json(
                args.status,
                {
                    "status": "forwarding_complete",
                    "backend_verified": False,
                    "training_exit_code": code,
                    "records": cursor.value["records"],
                    "step": cursor.value["step"],
                    "hold_seconds": hold,
                    "hub_status": sink.last_status,
                },
            )
            return 0
        except Exception as error:
            atomic_json(
                args.status,
                {
                    "status": "failed",
                    "backend_verified": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            return 1
        finally:
            if sink is not None:
                sink.close()


if __name__ == "__main__":
    raise SystemExit(main())
