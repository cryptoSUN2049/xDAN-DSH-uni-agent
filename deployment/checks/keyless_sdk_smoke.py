"""Initialize/shutdown the real fixed SDK, without requesting a model completion.

Run inside the amd64 task image with Docker --network none. This is a boot
check, not evidence of an agent rollout or a reward.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import tempfile
from pathlib import Path


def main() -> None:
    from deepseek_harness import HarnessClient, HarnessConfig
    from deepseek_harness_runtime import resolve_bundled_launch_args

    from uni_agent.agents.dsh import runner

    architecture = platform.machine().lower()
    if platform.system() != "Linux" or architecture not in {"x86_64", "amd64"}:
        raise RuntimeError(f"Expected Linux amd64, got {platform.system()}/{architecture}")
    expected = {
        "deepseek-harness-sdk": "0.1.2a1",
        "deepseek-harness-runtime-bin": "0.1.2a1",
        "pydantic": "2.12.5",
    }
    versions = {package: importlib.metadata.version(package) for package in expected}
    if versions != expected or not callable(runner.run):
        raise RuntimeError(f"Unexpected SDK installation: {versions}")
    launch_args = resolve_bundled_launch_args("exe")
    with tempfile.TemporaryDirectory(prefix="dsh-keyless-") as folder:
        config = HarnessConfig(
            profile="sdk-minimal",
            cwd=folder,
            dsh_home=str(Path(folder) / "home"),
            initialize_timeout_seconds=120,
            request_timeout_seconds=120,
            env={
                "DSH_RUNTIME_MODE": "exe",
                "DEEPSEEK_API_KEY": "sk-dummy-for-boot",
                "DEEPSEEK_BASE_URL": "http://127.0.0.1:9",
                "DSH_PERMISSION_MODE": "danger-full-access",
                "DSH_TELEMETRY_DISABLED": "1",
            },
        )
        with HarnessClient(config) as client:
            result = client.initialize(provider="deepseek-official", cwd=folder, model="deepseek-v4-pro")
            if result.serverInfo is None or result.serverInfo.name != "deepseek-harness-sdk-runtime":
                raise RuntimeError("Unexpected SDK initialize response")
    print(
        json.dumps(
            {
                "schema": "dsh.keyless-sdk-smoke.v1",
                "status": "passed",
                "scope": "initialize-shutdown-only",
                "architecture": architecture,
                "versions": versions,
                "runtime_executable": launch_args[0],
                "runner_sha256": "sha256:" + hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
