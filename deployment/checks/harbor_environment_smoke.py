"""Exercise the borrowed adapter against one real, network-free Harbor container."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths

from uni_agent.sandbox.harbor import BorrowedHarborSandbox


async def run(task_dir: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    paths = TrialPaths(trial_dir=output)
    paths.mkdir()
    session_id = "dsh-borrowed-" + uuid.uuid4().hex[:12]
    environment = DockerEnvironment(
        environment_dir=task_dir / "environment",
        environment_name="dsh-borrowed-smoke",
        session_id=session_id,
        trial_paths=paths,
        task_env_config=EnvironmentConfig(cpus=1, memory_mb=512, storage_mb=1024),
    )
    report = {"session_id": session_id, "passed": False, "cleanup_completed": False}
    try:
        await environment.start(force_build=False)
        sandbox = BorrowedHarborSandbox(environment)
        payload = bytes(range(256)) + b"\x00\xff\n"
        await sandbox.write_file("/app/a space/data.bin", payload)
        assert await sandbox.read_file("/app/a space/data.bin") == payload
        result = await sandbox.exec(
            ["printf", "%s", "literal $(id); ' \""],
            timeout=10,
            workdir="/app",
        )
        assert result.exit_code == 0 and result.stdout == "literal $(id); ' \""
        result = await sandbox.exec_shell(
            'printf "%s:%s" "$SMOKE_VALUE" "$PWD"', timeout=10, workdir="/app", env={"SMOKE_VALUE": "ok value"}
        )
        assert result.exit_code == 0 and result.stdout == "ok value:/app"
        result = await sandbox.exec(["bash", "-c", "exit 7"], timeout=10)
        assert result.exit_code == 7
        report.update(passed=True, binary_roundtrip=True, argv_literal=True, env_cwd=True, exit_code=True)
    finally:
        try:
            await environment.stop(delete=True)
            report["cleanup_completed"] = True
        finally:
            (output / "borrowed-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(run(args.task_dir.resolve(), args.output.resolve()), timeout=180))
