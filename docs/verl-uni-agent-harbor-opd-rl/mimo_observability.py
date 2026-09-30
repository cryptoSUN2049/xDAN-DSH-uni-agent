"""Run native VERL and retain its Ray actors until real terminal metrics are scraped."""

import json
import math
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

# Historical default only; new runs pass their explicitly authorized absolute cutoff.
DEADLINE = 1790709401
CLEANUP_RESERVE = 180
PREFIX = "rl_insight_monitor_"
METRICS = ("training_global_step", "actor_grad_norm", "critic_rewards_mean")
PROMETHEUS = "http://127.0.0.1:9090"


def validate_deadline(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("Observability deadline must be a finite positive Unix timestamp")
    return value


def resolve_deadline(config):
    return validate_deadline(getattr(config.trainer, "observability_deadline_unix", DEADLINE))


def metric_query(project, experiment):
    names = "|".join(PREFIX + name for name in METRICS)
    return (
        "{__name__=~"
        + json.dumps(names)
        + ",project="
        + json.dumps(project)
        + ",experiment_name="
        + json.dumps(experiment)
        + "}"
    )


def verify_ack(response, project, experiment, step, started_at):
    """Reject stale, ambiguous, mismatched or non-finite backend samples."""
    try:
        if response["status"] != "success" or response["data"]["resultType"] != "vector":
            return None
        rows = response["data"]["result"]
        if len(rows) != len(METRICS):
            return None
        values = {}
        for row in rows:
            labels = row["metric"]
            if labels.get("project") != project or labels.get("experiment_name") != experiment:
                return None
            name = labels["__name__"]
            if not name.startswith(PREFIX) or name[len(PREFIX) :] not in METRICS:
                return None
            name = name[len(PREFIX) :]
            timestamp, raw_value = row["value"]
            value = float(raw_value)
            if name in values or not math.isfinite(value) or not math.isfinite(float(timestamp)):
                return None
            if float(timestamp) < started_at:
                return None
            values[name] = value
        if values.get("training_global_step") != step:
            return None
        return values
    except (KeyError, TypeError, ValueError):
        return None


def query_prometheus(query, timeout):
    url = PROMETHEUS + "/api/v1/query?" + urlencode({"query": query})
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_for_ack(
    project,
    experiment,
    step,
    started_at,
    output,
    *,
    deadline_unix=DEADLINE,
    query=query_prometheus,
    clock=time.monotonic,
    sleep=time.sleep,
    wall_clock=time.time,
):
    deadline_unix = validate_deadline(deadline_unix)
    budget = max(0, min(45, deadline_unix - CLEANUP_RESERVE - wall_clock()))
    end = clock() + budget
    expression = metric_query(project, experiment)
    report = {
        "schema": "mimo.native-observability-ack.v1",
        "status": "failed",
        "project": project,
        "experiment_name": experiment,
        "step": step,
        "training_started_at": started_at,
        "budget_seconds": budget,
        "deadline_unix": deadline_unix,
        "query": expression,
    }
    while (remaining := end - clock()) > 0:
        try:
            response = query(expression, min(3, remaining))
            report["backend_response"] = response
            values = verify_ack(response, project, experiment, step, started_at)
            if values is not None:
                report.update(status="passed", values=values)
                break
        except (URLError, TimeoutError, ValueError) as error:
            report["last_error_type"] = type(error).__name__
        sleep(min(1, max(0, end - clock())))
    report["finished_at"] = wall_clock()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"observability_ack": report["status"], "report": str(output)}), flush=True)
    if report["status"] != "passed":
        raise TimeoutError("Prometheus did not acknowledge this run's native terminal metrics")
    return report


def run_then_ack(native_run, acknowledge, *, now=time.time):
    started_at = now()
    native_run()
    return acknowledge(started_at)


def retain_monitor_hub(config):
    """Hold the job-scoped hub across native Tracking.finish(), which drops its client."""
    from rl_insight.client.ray_monitor_client import get_or_create_monitor_hub
    from rl_insight.utils.monitor_config_loader import load_monitor_config

    return get_or_create_monitor_hub(load_monitor_config(config.trainer.get("rl_insight", {}) or {}))


def make_observed_runner(ray, native_runner):
    """Retain both the native runner and its hub while terminal events are scraped."""

    @ray.remote(num_cpus=1)
    class ObservedTaskRunner:
        def run(self, config):
            deadline_unix = resolve_deadline(config)
            self.monitor_hub = retain_monitor_hub(config)
            self.native_runner = native_runner.remote()
            trainer = config.trainer
            return run_then_ack(
                lambda: ray.get(self.native_runner.run.remote(config)),
                lambda started: wait_for_ack(
                    trainer.project_name,
                    trainer.experiment_name,
                    trainer.total_training_steps,
                    started,
                    Path(trainer.default_local_dir).parent / "observability-ack.json",
                    deadline_unix=deadline_unix,
                ),
            )

    return ObservedTaskRunner


def main():  # pragma: no cover - exercised by the real native training entry, not CPU unit doubles
    import hydra
    import ray

    from verl.trainer import main_ppo as native

    @hydra.main(config_path=str(Path(native.__file__).parent / "config"), config_name="ppo_trainer", version_base=None)
    def entry(config):
        resolve_deadline(config)
        if not config.trainer.use_v1 or not {"wandb", "rl_insight"}.issubset(config.trainer.logger):
            raise ValueError("Observed entry requires native V1 with wandb and rl_insight")
        native.auto_set_device(config)
        native.validate_config(
            config=config,
            use_reference_policy=native.need_reference_policy(config),
            use_critic=native.need_critic(config),
        )
        native.run_ppo(config, task_runner_class=make_observed_runner(ray, native.TaskRunnerV1))

    entry()


if __name__ == "__main__":  # pragma: no cover
    main()
