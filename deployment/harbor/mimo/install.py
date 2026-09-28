"""Container build helper: install only into the isolated /opt/dsh prefix."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    prefix = Path("/opt/dsh")
    inputs = Path("/opt/dsh-build")
    if sys.version_info[:2] != (3, 12) or Path(sys.prefix).resolve() != prefix:
        raise RuntimeError("Installation must use the isolated CPython 3.12 prefix")
    binding = json.loads((inputs / "build-inputs.json").read_text())
    lock = binding["lock"]
    for name, expected in lock["wheels"].items():
        if hashlib.sha256((inputs / "wheelhouse" / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Wheel changed after preparation: {name}")
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-index",
            "--no-cache-dir",
            "--only-binary=:all:",
            "--find-links=" + str(inputs / "wheelhouse"),
            "deepseek-harness-sdk==0.1.3a2",
            "deepseek-harness-runtime-bin==0.1.3a2",
            "pydantic==2.12.5",
        ],
        check=True,
    )
    subprocess.run([sys.executable, "-I", "-m", "pip", "--isolated", "check"], check=True)
    for name, expected in binding["source_files"].items():
        source = inputs / "source" / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Source changed after preparation: {name}")
        destination = prefix / "uni-agent" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    site_packages = prefix / "lib/python3.12/site-packages"
    if not site_packages.is_dir():
        raise RuntimeError("Portable Python does not provide the expected isolated site-packages")
    (site_packages / "uni-agent-dsh.pth").write_text(str(prefix / "uni-agent") + "\n")
    launcher = prefix / "bin/python"
    if launcher.is_symlink():
        launcher.unlink()
    launcher.write_text('#!/bin/sh\nexec /opt/dsh/bin/python3.12 -I "$@"\n')
    launcher.chmod(0o755)
    probe = """import hashlib, importlib.metadata, json, pathlib
from deepseek_harness_runtime import resolve_bundled_launch_args
from uni_agent.agents.dsh import runner
expected = json.loads(pathlib.Path('/opt/dsh-build/build-inputs.json').read_text())
for package in ('deepseek-harness-sdk', 'deepseek-harness-runtime-bin'):
    assert importlib.metadata.version(package) == expected['lock']['python_distribution_version']
binary = pathlib.Path(resolve_bundled_launch_args('exe')[0])
assert hashlib.sha256(binary.read_bytes()).hexdigest() == expected['lock']['runtime_binary_sha256']
sidecar = pathlib.Path(str(binary) + '-rg')
assert hashlib.sha256(sidecar.read_bytes()).hexdigest() == expected['lock']['runtime_rg_sha256']
runner_hash = hashlib.sha256(pathlib.Path(runner.__file__).read_bytes()).hexdigest()
assert runner_hash == expected['source_files']['uni_agent/agents/dsh/runner.py']
print(json.dumps({'status': 'installed_identity_verified', 'runtime': str(binary)}))
"""
    subprocess.run([str(launcher), "-c", probe], check=True, env={**os.environ, "DSH_RUNTIME_MODE": "exe"})
    (prefix / "build-inputs.json").write_text(json.dumps(binding, indent=2) + "\n")
    for directory in (prefix, prefix / "bin", prefix / "uni-agent"):
        directory.chmod(0o755)
    shutil.rmtree(inputs)


if __name__ == "__main__":
    main()
