"""CPU/Modal calibration of the native separate verifier; no model requests."""

import argparse
import asyncio
import contextlib
import hashlib
import json
import shlex
import time
from pathlib import Path

from harbor.models.trial.config import TrialConfig

from uni_agent.tasks.harbor_dsh.environment_backend import TRACKED_MODAL_IMPORT
from uni_agent.tasks.harbor_dsh.executor import _task_digest
from uni_agent.tasks.harbor_dsh.isolated_trial import create_isolated_trial
from uni_agent.tasks.harbor_dsh.mimo import MIMO_STRATEGY, load_mimo_binding
from uni_agent.tasks.harbor_dsh.modal_environment import ModalExecutionScope

CANDIDATE_SHA = "2229cbd226fa8f2add77b39247ecea70832cdcb748f60239f70e60162d1dfdbc"


async def checked_exec(environment, command):
    result = await environment.exec(command=command, timeout_sec=120, user="root")
    if result.return_code != 0:
        raise RuntimeError(f"Calibration command failed: {result.stderr[-2000:]}")
    return result.stdout


async def run_case(args, name, expected_reward):
    binding = load_mimo_binding(args.task / "mimo-binding.json")
    task_sha256 = _task_digest(args.task)
    expected_tests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.task / "tests").iterdir()
    }
    config = TrialConfig.model_validate(
        {
            "task": {"path": str(args.task)},
            "trials_dir": str(args.private_root),
            "trial_name": "mimo-verifier-injection-" + name,
            "agent": {
                "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
                "model_name": "cpu-pipeline-calibration-no-inference",
                "kwargs": {
                    "gateway_base_url": args.gateway_origin + "/sessions/calibration-" + name + "/v1",
                    "profile": "sdk-minimal",
                    "patches": [],
                    "workdir": binding.cwd,
                    "runner_python": binding.runner_python,
                },
            },
            "environment": {
                "type": "modal",
                "import_path": TRACKED_MODAL_IMPORT,
                "delete": True,
                "kwargs": {"sandbox_timeout_secs": 900, "registry_secret": args.registry_secret},
            },
        }
    )
    scope = ModalExecutionScope()
    result = {"case": name, "task_sha256": task_sha256, "started_at": time.time()}
    trial = None
    try:
        async with scope:
            trial = create_isolated_trial(
                config,
                allowed_task_dir=args.task,
                strategy=MIMO_STRATEGY,
                gateway_session_id="calibration-" + name,
                mimo_binding=binding,
            )
            # Inspect after the production hook uploads tests. The inherited
            # _run_separate_verifier and Verifier.verify remain unmodified.
            separate = trial._separate_verifier_env

            @contextlib.asynccontextmanager
            async def observed_separate(*a, **kw):
                async with separate(*a, **kw) as environment:
                    command = "sha256sum " + " ".join(shlex.quote("/tests/" + n) for n in sorted(expected_tests))
                    output = await checked_exec(environment, command)
                    actual = {Path(line.split()[1]).name: line.split()[0] for line in output.splitlines()}
                    assert actual == expected_tests, "Verifier tests differ from frozen task bundle"
                    result["verifier_test_sha256"] = actual
                    yield environment

            trial._separate_verifier_env = observed_separate
            try:
                await trial.agent_environment.start(force_build=False)
                await checked_exec(trial.agent_environment, "test ! -e /tests/test.sh")
                result["agent_tests_absent_before"] = True
                await trial._artifact_handler.capture_base(trial.agent_environment)
                if name == "candidate":
                    await trial.agent_environment.upload_file(args.candidate, "/tmp/public-only-candidate.patch")
                    await checked_exec(
                        trial.agent_environment,
                        "git -C " + shlex.quote(binding.cwd) + " apply /tmp/public-only-candidate.patch",
                    )
                artifacts = trial.paths.trial_dir / "calibration-artifacts"
                await trial._artifact_handler.download_artifacts(
                    trial.agent_environment, artifacts, source_artifacts_dir="/artifacts", services={"main"}
                )
                verifier = await trial._run_separate_verifier(
                    key="trial", timeout_sec=360, artifacts_dir=artifacts, user="root"
                )
                assert verifier.rewards == {"reward": expected_reward}, verifier.rewards
                receipt_path = trial.paths.verifier_dir / "mimo-receipt.json"
                receipt = json.loads(receipt_path.read_text())
                assert receipt["status"] == "graded" and receipt["reward"] == expected_reward
                assert receipt["snapshot_sha256"] == trial._artifact_handler._state["snapshot_sha256"]
                await checked_exec(trial.agent_environment, "test ! -e /tests/test.sh")
                result.update(
                    reward=verifier.rewards,
                    receipt=receipt,
                    agent_tests_absent_after=True,
                    native_skip_tests_upload=True,
                )
                case_output = args.output / name
                case_output.mkdir()
                for path in trial.paths.verifier_dir.iterdir():
                    if path.is_file():
                        (case_output / path.name).write_bytes(path.read_bytes())
                assert _task_digest(args.task) == task_sha256, "Frozen task changed during calibration"
            finally:
                await trial.agent_environment.stop(delete=True)
    finally:
        if trial is not None:
            trial._close_logger_handler()
        result.update(
            resources=list(scope.evidence), cleanup_confirmed=scope.cleanup_confirmed, finished_at=time.time()
        )
        (args.output / (name + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    assert scope.cleanup_confirmed and len(scope.evidence) == 2
    assert all(type(item["returncode"]) is int for item in scope.evidence)
    return result


async def main(args):
    assert hashlib.sha256(args.candidate.read_bytes()).hexdigest() == CANDIDATE_SHA
    args.output.mkdir(parents=True, exist_ok=False)
    args.private_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    status = {"schema": "dsh.mimo-verifier-injection-calibration.v1", "status": "running", "model_requests": 0}
    path = args.output / "status.json"
    path.write_text(json.dumps(status, indent=2) + "\n")
    try:
        async with asyncio.timeout(1200):
            status["cases"] = [await run_case(args, "baseline", 0.0), await run_case(args, "candidate", 1.0)]
        status["status"] = "passed"
    except BaseException as error:
        status.update(status="failed", exception_type=type(error).__name__)
        raise
    finally:
        path.write_text(json.dumps(status, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("task", "candidate", "output", "private-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--gateway-origin", default="https://mimo9b-rl.xdan.work")
    parser.add_argument("--registry-secret", default="mimo-dsh-ghcr-20260928")
    asyncio.run(main(parser.parse_args()))
