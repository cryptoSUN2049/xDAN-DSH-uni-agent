"""Run oracle, nop and score-forgery probes using real isolated Harbor trials."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from harbor.models.trial.config import TrialConfig
from harbor.trial.hooks import TrialEvent

from uni_agent.tasks.harbor_dsh.isolated_trial import create_isolated_trial


async def run(task_dir: Path, output: Path, artifact_boundaries: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    test_path = task_dir / "tests/test.sh"
    original = hashlib.sha256(test_path.read_bytes()).hexdigest()
    report = {"passed": False, "model_called": False, "cases": []}
    try:
        cases = (
            (("symlink", None), ("directory", None), ("oversize", None))
            if artifact_boundaries
            else (("oracle", 1), ("nop", 0), ("tamper", 0))
        )
        for mode, expected in cases:
            config = TrialConfig.model_validate(
                {
                    "task": {"path": str(task_dir)},
                    "trial_name": "isolated-" + mode,
                    "trials_dir": str(output),
                    "environment": {"type": "docker", "delete": True},
                    "agent": {"name": "oracle" if mode == "oracle" else "nop"},
                }
            )
            trial = create_isolated_trial(config, allowed_task_dir=task_dir)
            evidence = {"mode": mode, "expected_reward": expected}

            async def inspect_agent(_event, trial=trial, evidence=evidence, mode=mode):
                result = await trial.agent_environment._run_docker_compose_command(["ps", "-q", "main"])
                container_id = result.stdout.strip()
                process = await asyncio.create_subprocess_exec(
                    "docker", "inspect", container_id, stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
                if process.returncode != 0:
                    raise RuntimeError("Cannot inspect agent container")
                container = json.loads(stdout)[0]
                evidence["agent_container"] = container_id
                evidence["agent_mounts"] = container["Mounts"]
                if container["Mounts"]:
                    raise RuntimeError("Agent unexpectedly has mounts")
                if mode == "tamper":
                    result = await trial.agent_environment.exec(
                        "mkdir -p /tests /logs/verifier; printf 'wrong\\n' > /app/answer.txt; "
                        "printf '1\\n' > /logs/verifier/reward.txt; "
                        "printf '#!/bin/sh\\necho 1 > /logs/verifier/reward.txt\\n' > /tests/test.sh",
                        timeout_sec=10,
                    )
                    if result.return_code != 0:
                        raise RuntimeError("Tamper probe did not execute")
                    evidence["forged_agent_score"] = True
                if mode in {"symlink", "directory", "oversize"}:
                    commands = {
                        "symlink": "ln -s /etc/passwd /app/answer.txt",
                        "directory": "mkdir /app/answer.txt",
                        "oversize": "python -c \"open('/app/answer.txt','wb').write(b'x'*4097)\"",
                    }
                    result = await trial.agent_environment.exec(commands[mode], timeout_sec=10)
                    if result.return_code != 0:
                        raise RuntimeError("Artifact boundary probe did not execute")

            trial.add_hook(TrialEvent.AGENT_START, inspect_agent)
            result = await asyncio.wait_for(trial.run(), timeout=240)
            evidence["exception"] = (
                None if result.exception_info is None else result.exception_info.model_dump(mode="json")
            )
            evidence["rewards"] = None if result.verifier_result is None else result.verifier_result.rewards
            report["cases"].append(evidence)
            if expected is None:
                if result.exception_info is None or "Rejected unsafe or malformed answer artifact" not in str(
                    result.exception_info
                ):
                    raise RuntimeError(f"Expected exact artifact rejection: {evidence}")
                if (
                    result.verifier_result is not None
                    or (output / ("isolated-" + mode) / "artifacts/app/answer.txt").exists()
                ):
                    raise RuntimeError("Rejected artifact was downloaded or scored")
                evidence["artifact_rejection_verified"] = True
            else:
                if result.exception_info is not None or result.verifier_result is None:
                    raise RuntimeError(f"Trial failed: {mode}: {evidence}")
                if result.verifier_result.rewards != {"reward": float(expected)}:
                    raise RuntimeError(f"Unexpected reward: {evidence}")
            cleanup = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "-aq",
                "--filter",
                "id=" + evidence["agent_container"],
                stdout=asyncio.subprocess.PIPE,
            )
            remaining, _ = await asyncio.wait_for(cleanup.communicate(), timeout=15)
            if cleanup.returncode != 0 or remaining.strip():
                raise RuntimeError("Agent container cleanup could not be verified")
            evidence["agent_cleanup_verified"] = True
            if hashlib.sha256(test_path.read_bytes()).hexdigest() != original:
                raise RuntimeError("Host verifier changed")
        report["host_verifier_sha256"] = original
        report["passed"] = True
    finally:
        (output / "isolation-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-boundaries", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        asyncio.wait_for(run(args.task_dir.resolve(), args.output.resolve(), args.artifact_boundaries), timeout=720)
    )
