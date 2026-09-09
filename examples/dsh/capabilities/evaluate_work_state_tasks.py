"""Run four independent singleton reloads; retain failures without admitting them."""

import argparse
import json
import os
import re
import signal
import subprocess
from pathlib import Path

from examples.dsh.capabilities import prepare_memory_training as recipe

TASK_IDS = tuple(f"work-state-{family}-v1-s303" for family in ("ws01", "ws03", "ws05", "ws06"))
SAMPLING_FIELDS = (
    "VAL_ROLLOUT_N",
    "VAL_MAX_SAMPLES",
    "MAX_PROMPT_LENGTH",
    "MAX_RESPONSE_LENGTH",
    "PPO_MAX_TOKEN_LEN_PER_GPU",
    "ROLLOUT_MAX_NUM_SEQS",
    "CONCURRENCY",
    "GATEWAY_COUNT",
)
IDENTITY_FIELDS = (
    "integration_head",
    "verl_head",
    "verl_effective_source",
    "model_revision_declared",
    "model_files",
    "runtime",
    "checkpoint_origin",
    "wall_seconds",
)


def audit_memory_training(run_root, **kwargs):
    # Avoid importing the trainer stack during CLI parsing/preparation.
    from examples.dsh.capabilities.audit_memory_training import audit_memory_training as audit

    return audit(run_root, **kwargs)


def require_idle_gpu():
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.stdout.strip():
        raise RuntimeError("GPU cleanup is unconfirmed; no further dispatch")


def _save(path, value):
    temporary = path.with_suffix(".pending")
    with temporary.open("x") as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, indent=2, allow_nan=False)
        output.write("\n")
    temporary.replace(path)


def _audit_is_corrupt(report):
    if any(
        report[key]
        for key in (
            "errors",
            "unknown_or_unadmitted_consumption",
            "duplicate_consumption",
            "overlapping_crosswalk_keys",
        )
    ):
        return True
    # Missing final dump after a failed task is absence, not invented consumption.
    allowed = {"missing_submission", "missing_consumed_keys"}
    return any(set(group["reasons"]) - allowed for group in report["groups"])


def _verify_selected_task(report, run, task):
    if (
        report["summary"]["consumed_groups"] != 1
        or report["summary"]["consumed_rows"] != 2
        or len(report["groups"]) != 1
    ):
        raise ValueError("Singleton evaluation requires one consumed A/B pair")
    group = report["groups"][0]
    crosswalk = Path(group["path"])
    if (
        not crosswalk.resolve().is_relative_to((run / "chains" / "groups").resolve())
        or recipe.digest(crosswalk) != group["crosswalk_sha256"]
    ):
        raise ValueError("Audited crosswalk location/hash changed")
    record = json.loads(crosswalk.read_text())
    if (
        record["run_id"] != task["run_id"]
        or record["partition"] != "val"
        or [item["role"] for item in record["items"]] != ["A", "B"]
    ):
        raise ValueError("Singleton evaluation crosswalk identity changed")
    for item in record["items"]:
        envelope_path = Path(item["stage_receipt_path"]).with_name("agent-result.json")
        if not envelope_path.resolve().is_relative_to((run / "chains").resolve()):
            raise ValueError("Stage envelope is outside this run")
        metadata = json.loads(envelope_path.read_text())["metadata"]
        fixture_path = Path(metadata["fixture_path"])
        if (
            not fixture_path.resolve().is_relative_to((run / "chains").resolve())
            or recipe.digest(fixture_path) != metadata["fixture_sha256"]
        ):
            raise ValueError("Stage fixture location/hash changed")
        if json.loads(fixture_path.read_text())["task"]["task_id"] != task["task_id"]:
            raise ValueError("Consumption belongs to a different evaluation task")


def _identity(manifest):
    identity = {key: manifest[key] for key in IDENTITY_FIELDS}
    identity["sampling_environment"] = {key: manifest["environment"][key] for key in SAMPLING_FIELDS}
    if any(identity["sampling_environment"][key] != "1" for key in ("VAL_ROLLOUT_N", "VAL_MAX_SAMPLES")):
        raise ValueError("Independent evaluation requires singleton n1")
    return identity


def evaluate(*, root, suite_id, runtime_executable, runner_python, model_path, model_revision, mother_run, resume_from):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", suite_id):
        raise ValueError("Invalid suite identity")
    root = Path(root).absolute()
    for source in (mother_run, resume_from):
        old = Path(source).resolve()
        if root.resolve().is_relative_to(old) or old.is_relative_to(root.resolve()):
            raise ValueError("Suite must be independent of mother and checkpoint")
    root.mkdir(mode=0o700)  # Never adopt or overwrite a previous suite.
    summary = dict(
        schema="dsh.work-state-independent-evaluation.v1",
        suite_id=suite_id,
        mother_run=str(mother_run),
        resume_from=str(resume_from),
        identity=None,
        tasks=[dict(task_id=task, status="not_run", run_id=f"{suite_id}-{task.split('-')[2]}") for task in TASK_IDS],
        stop_reason=None,
        all_attempted=False,
        all_verified=False,
        exit_code=1,
    )

    def persist():
        summary["all_attempted"] = all("execution" in task for task in summary["tasks"])
        summary["all_verified"] = summary["stop_reason"] is None and all(
            task["status"] == "verified" for task in summary["tasks"]
        )
        summary["exit_code"] = 0 if summary["all_verified"] else 1
        _save(root / "summary.json", summary)

    persist()
    for task in summary["tasks"]:
        phase = "gpu-preflight"
        try:
            require_idle_gpu()
            data, run = root / (task["run_id"] + "-data"), root / task["run_id"]
            task.update(status="preparing", run_root=str(run), preparation_root=str(data))
            persist()
            phase = "prepare"
            recipe.prepare(
                output_dir=data,
                run_root=run,
                run_id=task["run_id"],
                runtime_executable=runtime_executable,
                runner_python=runner_python,
                model_path=model_path,
                model_revision=model_revision,
                family="work-state-v1",
                mode="reload",
                mother_run=mother_run,
                resume_from=resume_from,
                evaluation_task_ids=[task["task_id"]],
            )
            phase = "check"
            manifest = recipe.check(data / "manifest.json")
            identity = _identity(manifest)
            if summary["identity"] is None:
                summary["identity"] = identity
            elif identity != summary["identity"]:
                raise ValueError("Evaluation source/checkpoint/budget identity changed")
            task["manifest_sha256"] = recipe.digest(data / "manifest.json")
            task["status"] = "running"
            persist()
            phase = "launch"
            execution = recipe.launch(data / "manifest.json")
            if type(execution.get("exit_code")) is not int:
                raise ValueError("Supervisor did not confirm process exit")
            task["execution"] = execution
            task["status"] = "execution_failed" if execution["exit_code"] else "awaiting_audit"
            persist()
            phase = "post-run-check"
            if _identity(recipe.check(data / "manifest.json", after_run=True)) != identity:
                raise ValueError("Post-run source/checkpoint/budget identity changed")
            phase = "audit"
            report = audit_memory_training(run, memory_root=run / "chains", expected_run_id=task["run_id"])
            audit_path = run / "consumption-audit.json"
            with audit_path.open("x") as output:
                json.dump(report, output, indent=2, allow_nan=False)
                output.write("\n")
            task["audit"] = dict(
                path=str(audit_path),
                sha256=recipe.digest(audit_path),
                passed=report["passed"],
                consumption_verified=report["consumption_verified"],
                summary=report["summary"],
            )
            if report["run_id"] != task["run_id"] or _audit_is_corrupt(report):
                raise ValueError("Independent consumption evidence failed integrity checks")
            if execution["exit_code"] == 0:
                if report["passed"] is not True or report["consumption_verified"] is not True:
                    raise ValueError("Successful process lacks verified trainer consumption")
                _verify_selected_task(report, run, task)
                task["status"] = "verified"
            phase = "cleanup"
            require_idle_gpu()
            _save(root / (task["run_id"] + "-result.json"), task)
            persist()
        except (KeyboardInterrupt, SystemExit):
            task["status"] = "cancelled"
            summary["stop_reason"] = dict(phase=phase, exception_type="Cancellation")
            persist()
            raise
        except Exception as error:
            task["status"] = "audit_failed" if phase == "audit" else "blocked"
            summary["stop_reason"] = dict(phase=phase, exception_type=type(error).__name__, message=str(error))
            _save(root / (task["run_id"] + "-result.json"), task)
            persist()
            break
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "root",
        "suite-id",
        "runtime-executable",
        "runner-python",
        "model-path",
        "model-revision",
        "mother-run",
        "resume-from",
    ):
        parser.add_argument("--" + name, required=True)
    args = vars(parser.parse_args())

    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        result = evaluate(**args)
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps({key: result[key] for key in ("suite_id", "all_attempted", "all_verified", "exit_code")}))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
