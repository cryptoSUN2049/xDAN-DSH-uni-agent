"""Bounded real Modal/Harbor environment cleanup probe; no Student or training."""

import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
from uuid import uuid4

from harbor.models.task.config import EnvironmentConfig, NetworkPolicy
from harbor.models.trial.paths import TrialPaths

from deployment.services.harbor_modal_ingress import require_external_private_path
from examples.harbor.prepare_t2_task import VERIFIER_IMAGE
from uni_agent.tasks.harbor_dsh.modal_environment import ModalExecutionScope, TrackedModalEnvironment


async def run(output_dir: Path) -> dict:
    output_dir = output_dir.absolute()
    require_external_private_path(output_dir)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = {
        "schema": "uni-agent.modal-environment-smoke.v1",
        "scope": "real provider lifecycle only; no DSH trial, reward or training",
        "image": VERIFIER_IMAGE,
        "versions": {name: importlib.metadata.version(name) for name in ("harbor", "modal")},
        "provider_timeout_seconds": 60,
        "commands": [],
        "passed": False,
    }
    scope = ModalExecutionScope(cleanup_timeout=30)
    failure = None
    try:
        async with scope:
            # Timeout also covers image resolution. Scope still owns late allocation
            # and independent cleanup if this outer operation is cancelled.
            async with asyncio.timeout(240):
                for role in ("agent", "verifier"):
                    paths = TrialPaths(trial_dir=output_dir / role)
                    environment_dir = output_dir / role / "environment"
                    environment_dir.mkdir(parents=True)
                    env = TrackedModalEnvironment(
                        environment_dir=environment_dir,
                        environment_name="ua-opd-probe-" + role,
                        session_id="ua-opd-" + role + "-" + uuid4().hex,
                        trial_paths=paths,
                        task_env_config=EnvironmentConfig(
                            docker_image=VERIFIER_IMAGE,
                            cpus=1,
                            memory_mb=256,
                            storage_mb=512,
                            network_mode="no-network",
                        ),
                        network_policy=NetworkPolicy(network_mode="no-network"),
                        app_name="uni-agent-verl-opd-validation",
                        sandbox_timeout_secs=60,
                    )
                    try:
                        await env.start(force_build=False)
                        result = await env.exec("printf uni-agent-modal-probe", timeout_sec=10)
                        record["commands"].append(
                            {
                                "role": role,
                                "session_id": env.session_id,
                                "return_code": result.return_code,
                                "stdout": result.stdout,
                            }
                        )
                        if result.return_code != 0 or result.stdout != "uni-agent-modal-probe":
                            raise RuntimeError("Real environment marker command failed")
                    finally:
                        await env.stop(delete=True)
        expected = {item["session_id"] for item in record["commands"]}
        observed = {item["session_id"] for item in scope.evidence}
        if len(expected) != 2 or expected != observed or not scope.cleanup_confirmed:
            raise RuntimeError("Real agent/verifier resource cleanup not confirmed")
        record["passed"] = True
    except BaseException as error:
        failure = error
        record["error_type"] = type(error).__name__
    finally:
        record["cleanup_confirmed"] = scope.cleanup_confirmed
        record["resources"] = scope.evidence
        path = output_dir / "result.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(record, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    if failure is not None:
        raise failure
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New private directory outside the repo")
    args = parser.parse_args()
    record = asyncio.run(run(args.output_dir))
    print(json.dumps({"passed": record["passed"], "result": str(args.output_dir / "result.json")}))


if __name__ == "__main__":
    main()
