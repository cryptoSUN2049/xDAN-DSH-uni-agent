"""Rebuild a pinned Harbor image context from Git objects and verified wheels.

No network, dependency installation, Docker execution or working-tree copying.
The operator must obtain the execution manifest from a trusted pinned release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

SOURCE_MAP = {
    "Dockerfile": "deployment/harbor/Dockerfile",
    "checks/keyless_sdk_smoke.py": "deployment/checks/keyless_sdk_smoke.py",
    **{
        p: p
        for p in (
            "uni_agent/__init__.py",
            "uni_agent/version/version",
            "uni_agent/agents/__init__.py",
            "uni_agent/agents/base.py",
            "uni_agent/agents/registry.py",
            "uni_agent/agents/dsh/__init__.py",
            "uni_agent/agents/dsh/agent.py",
            "uni_agent/agents/dsh/runner.py",
        )
    },
}
SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
WHEEL = re.compile(r"wheelhouse/[A-Za-z0-9][A-Za-z0-9_.+-]*\.whl")
REQUIRED_WHEELS = {
    "wheelhouse/deepseek_harness_sdk-0.1.3a2-py3-none-any.whl",
    "wheelhouse/deepseek_harness_runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64.whl",
}


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError("Pinned Git source is unavailable; fetch the exact commit first")
    return result.stdout


def _wheel_hash(path, output=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 512 * 1024 * 1024:
            raise ValueError("Wheel must be a regular file below 512 MiB")
        digest = hashlib.sha256()
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Wheel changed during verification")
        return digest.hexdigest()


def prepare_context(*, repo: Path, source_commit: str, manifest: dict, artifact_dir: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output context must be a new directory")
    if not COMMIT.fullmatch(source_commit) or source_commit != manifest.get("integration_revision"):
        raise ValueError("Explicit full source commit must equal manifest integration_revision")
    if (
        manifest.get("schema") != "dsh.harbor-execution-image-inputs.v1"
        or manifest.get("platform") != "linux/amd64"
        or manifest.get("python_distribution_version") != "0.1.3a2"
        or not COMMIT.fullmatch(manifest.get("dsh_revision", ""))
    ):
        raise ValueError("Expected the pinned Session v2 amd64 image manifest")
    files = manifest.get("files")
    if not isinstance(files, dict) or any(not isinstance(v, str) or not SHA.fullmatch(v) for v in files.values()):
        raise ValueError("Invalid manifest file hashes")
    wheel_paths = sorted(p for p in files if isinstance(p, str) and WHEEL.fullmatch(p) and ".." not in p)
    expected_paths = set(SOURCE_MAP) | set(wheel_paths) | {"source-revision", "wheelhouse/SHA256SUMS"}
    if set(files) != expected_paths or not REQUIRED_WHEELS.issubset(wheel_paths):
        raise ValueError("Manifest contains missing or unknown context paths")
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ValueError("Artifact directory must be a real directory")
    if _git(repo, "rev-parse", "--verify", source_commit + "^{commit}").decode().strip() != source_commit:
        raise ValueError("Source commit identity mismatch")
    contents = {target: _git(repo, "show", f"{source_commit}:{source}") for target, source in SOURCE_MAP.items()}
    contents["source-revision"] = (source_commit + "\n").encode()
    contents["wheelhouse/SHA256SUMS"] = "".join(f"{files[name]}  {Path(name).name}\n" for name in wheel_paths).encode()
    for name, content in contents.items():
        if _sha(content) != files[name]:
            raise ValueError(f"Pinned source or generated manifest digest mismatch: {name}")
    for name in wheel_paths:
        path = artifact_dir / Path(name).name
        if path.is_symlink() or not path.is_file() or _wheel_hash(path) != files[name]:
            raise ValueError(f"Approved artifact is missing or has the wrong digest: {Path(name).name}")

    # Verify all inputs before claiming output. A later I/O/race failure leaves
    # a visibly partial directory, never a successful verification receipt.
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, content in contents.items():
        target = output / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as destination:
            destination.write(content)
        target.chmod(0o600)
    for name in wheel_paths:
        target = output / name
        with target.open("xb") as destination:
            actual = _wheel_hash(artifact_dir / Path(name).name, destination)
        target.chmod(0o600)
        if actual != files[name]:
            raise ValueError("Artifact changed while constructing context")
    actual_files = {p.relative_to(output).as_posix(): _wheel_hash(p) for p in output.rglob("*") if p.is_file()}
    if actual_files != files:
        raise ValueError("Final context does not match the complete pinned manifest")
    return {
        "schema": "dsh.harbor-context-rebuild.v1",
        "verified": True,
        "source_commit": source_commit,
        "dsh_revision": manifest["dsh_revision"],
        "python_distribution_version": manifest["python_distribution_version"],
        "context": str(output.resolve()),
        "files": actual_files,
        "network_used": False,
        "docker_build_executed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare_context(
        repo=args.repo,
        source_commit=args.source_commit,
        manifest=json.loads(args.manifest.read_text()),
        artifact_dir=args.artifact_dir,
        output=args.output,
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
