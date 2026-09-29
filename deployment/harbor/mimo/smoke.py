"""Run with docker --network none and /opt/dsh/bin/python; never calls a model."""

import contextlib
import hashlib
import io
import json
from pathlib import Path


def main():
    from deepseek_harness_runtime import resolve_bundled_launch_args

    from deployment.checks.keyless_sdk_smoke import main as keyless_smoke
    from uni_agent.agents.dsh import runner

    binding = json.loads(Path("/opt/dsh/build-inputs.json").read_text())
    lock = binding["lock"]
    binary = Path(resolve_bundled_launch_args("exe")[0])
    identities = {
        "runtime_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "runtime_rg_sha256": hashlib.sha256(Path(str(binary) + "-rg").read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
    }
    expected = {
        "runtime_binary_sha256": lock["runtime_binary_sha256"],
        "runtime_rg_sha256": lock["runtime_rg_sha256"],
        "runner_sha256": binding["source_files"]["uni_agent/agents/dsh/runner.py"],
    }
    if identities != expected:
        raise RuntimeError("Installed runtime identities do not match the fixed release")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        keyless_smoke()
    boot = json.loads(captured.getvalue())
    if boot.get("status") != "passed":
        raise RuntimeError("Keyless SDK boot failed")
    print(json.dumps({**boot, **identities, "schema": "dsh.mimo-image-smoke.v1"}, sort_keys=True))


if __name__ == "__main__":
    main()
