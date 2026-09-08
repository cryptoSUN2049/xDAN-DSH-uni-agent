"""Check DSH setup inside a real Harbor-owned, network-free environment."""

import argparse
import asyncio
import json
import tempfile
import uuid
from pathlib import Path

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths

from uni_agent.agents.dsh.harbor_agent import DshHarborAgent


async def main(output: Path, image: str):
    output.mkdir(parents=True, exist_ok=False)
    paths = TrialPaths(trial_dir=output)
    paths.mkdir()
    with tempfile.TemporaryDirectory() as folder:
        envdir = Path(folder)
        (envdir / "docker-compose.yaml").write_text(
            "services:\n  main:\n    platform: linux/amd64\n    network_mode: none\n"
        )
        identity = "dsh-setup-" + uuid.uuid4().hex[:12]
        env = DockerEnvironment(
            environment_dir=envdir,
            environment_name="dsh-setup-smoke",
            session_id=identity,
            trial_paths=paths,
            task_env_config=EnvironmentConfig(docker_image=image, cpus=2, memory_mb=2048, storage_mb=2048),
        )
        report = {"session_id": identity, "passed": False, "cleanup_completed": False, "model_called": False}
        try:
            await env.start(force_build=False)
            bridge = DshHarborAgent(
                logs_dir=output / "agent",
                gateway_base_url="http://127.0.0.1:9/sessions/setup-only/v1",
                model_name="Qwen3-4B",
            )
            await bridge.setup(env)
            report["setup"] = json.loads((output / "agent/dsh/setup.json").read_text())
            report["passed"] = True
        finally:
            try:
                await env.stop(delete=True)
                report["cleanup_completed"] = True
            finally:
                (output / "setup-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(main(args.output.resolve(), args.image), timeout=180))
