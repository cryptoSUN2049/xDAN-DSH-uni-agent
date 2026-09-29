"""CPU-only synthetic transport preflight; never records a real training experiment."""

import hashlib
import json
import os
import runpy
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import ray
from omegaconf import OmegaConf

from verl.utils.tracking import RLInsightLogger, Tracking

ROOT = Path(os.environ["MIMO_OBSERVABILITY_PREFLIGHT_ROOT"])
HELPER = Path(os.environ["MIMO_OBSERVABILITY_HELPER"])
# Like a directly executed entry script, this namespace is not importable by name.
# Ray must serialize the helper functions by value, not rely on a docs-directory import.
make_observed_runner = runpy.run_path(str(HELPER))["make_observed_runner"]
PROJECT = "mimo-observability-preflight"
EXPERIMENT = "mimo9b-observability-preflight-20260929-v3"


@ray.remote(num_cpus=1)
class NativeLoggerProbe:
    def run(self, config):
        tracker = Tracking(PROJECT, EXPERIMENT, default_backend=["rl_insight"])
        tracker.log({"training/global_step": 4, "actor/grad_norm": 0.125, "critic/rewards/mean": 0.75}, step=4)
        start = time.time_ns()
        RLInsightLogger.trace_span(
            "synthetic_observability_preflight",
            start_time_ns=start,
            end_time_ns=start + 1000,
            attributes={"project": PROJECT, "experiment_name": EXPERIMENT, "synthetic_preflight": True},
        )
        tracker.finish()


def main():
    ROOT.mkdir(parents=True, exist_ok=False)
    started = time.time()
    report = {
        "schema": "mimo.observability-preflight.v1",
        "status": "running",
        "synthetic_preflight": True,
        "training_acceptance": False,
        "project": PROJECT,
        "experiment_name": EXPERIMENT,
        "started_at": started,
        "helper_sha256": hashlib.sha256(HELPER.read_bytes()).hexdigest(),
    }

    def save():
        (ROOT / "status.json").write_text(json.dumps(report, indent=2) + "\n")

    save()
    runner = None
    try:
        ray.init(
            address="local",
            num_cpus=3,
            num_gpus=0,
            namespace=EXPERIMENT,
            _temp_dir="/root/mimo-private/robs-" + str(os.getpid()),
            include_dashboard=False,
        )
        config = OmegaConf.create(
            {
                "trainer": {
                    "project_name": PROJECT,
                    "experiment_name": EXPERIMENT,
                    "total_training_steps": 4,
                    "default_local_dir": str(ROOT / "checkpoints"),
                }
            }
        )
        runner = make_observed_runner(ray, NativeLoggerProbe).remote()
        report["ack"] = ray.get(runner.run.remote(config))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            query = urlencode(
                {
                    "tags": f'experiment_name="{EXPERIMENT}"',
                    "start": int(started) - 5,
                    "end": int(time.time()) + 5,
                    "limit": 20,
                }
            )
            with urlopen("http://127.0.0.1:3200/api/search?" + query, timeout=3) as response:
                traces = json.load(response)
            if traces.get("traces"):
                report["tempo_search"] = traces
                break
            time.sleep(1)
        else:
            raise TimeoutError("Tempo did not return the distinct synthetic preflight trace")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__, error=str(error)[:1000])
        raise
    finally:
        if runner is not None:
            ray.kill(runner, no_restart=True)
        ray.shutdown()
        report["finished_at"] = time.time()
        save()


if __name__ == "__main__":
    main()
