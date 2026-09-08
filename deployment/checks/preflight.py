"""Read-only deployment inventory; a passing report is not a training acceptance."""

import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
from pathlib import Path

REQUIRED = ("torch", "vllm", "ray", "transformers", "verl", "uni-agent", "deepseek-harness-sdk")
IDENTITIES = (
    "integration_revision",
    "verl",
    "dsh_release",
    "python_dependencies_lock",
    "student_model_revision",
    "task_release_digest",
    "verifier_digest",
    "harness_digest",
)


def readiness(manifest, installed, system, gpu_ok, revisions):
    failures = [f"unresolved identity: {key}" for key in IDENTITIES if not manifest.get(key)]
    failures.extend(f"missing package: {name}" for name in REQUIRED if not installed.get(name))
    if system != "Linux":
        failures.append("Linux runtime required")
    if not gpu_ok:
        failures.append("GPU inventory unavailable")
    for key in ("integration_revision", "verl"):
        if manifest.get(key) != revisions.get(key):
            failures.append(f"revision mismatch: {key}")
    return failures


def command(args, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=20, check=False)
        return result.returncode == 0, result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return False, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    root = Path(__file__).resolve().parents[2]
    installed = {}
    for name in REQUIRED:
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
    gpu_ok, gpu = command(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    revisions = {
        "integration_revision": command(["git", "rev-parse", "HEAD"], root)[1],
        "verl": command(["git", "rev-parse", "HEAD"], root / "verl")[1],
    }
    failures = readiness(manifest, installed, platform.system(), gpu_ok, revisions)
    print(
        json.dumps(
            {
                "schema": "dsh.deployment.inventory.v1",
                "scope": "inventory-only",
                "inventory_passed": not failures,
                "training_accepted": False,
                "python": platform.python_version(),
                "system": platform.system(),
                "gpu": gpu,
                "packages": installed,
                "revisions": revisions,
                "docker_cli": bool(shutil.which("docker")),
                "docker_socket": Path("/var/run/docker.sock").is_socket(),
                "failures": failures,
            },
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
