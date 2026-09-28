"""CPU-only Docker builder in a bounded Modal VM Sandbox.

Run this client on the remote CPU host, never on the developer's Mac. Probe
first, then build a prepared context. Registry credentials travel only through
docker login's stdin, and the builder is terminated on every outcome.

Official API: https://modal.com/docs/guide/vm-sandboxes (Python SDK >= 1.4).
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import re
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from deployment.bootstrap.prepare_harbor_context import _wheel_hash
from deployment.harbor.mimo.prepare_context import IMAGE, _json, inspect_binds_image
from deployment.harbor.mimo.publish_binding import finalize_binding


@dataclass
class BuilderConfig:
    mode: str
    original_image: str
    output: Path
    timeout_seconds: int = 180
    cpu: float = 1
    memory_mib: int = 4096
    builder_base_image: str = "ubuntu:24.04"
    app_name: str = "mimo-dsh-cpu-builder"
    context: Path | None = None
    image_tag: str | None = None
    registry_user: str | None = None
    registry_token_file: Path | None = None
    published_image: str | None = None
    task_cwd: str | None = None


def _validate(config):
    if config.output.exists() or config.output.is_symlink():
        raise FileExistsError("Builder evidence output must be new")
    if config.mode not in {"probe", "build", "verify"} or not IMAGE.fullmatch(config.original_image):
        raise ValueError("Select probe/build/verify and a fixed original registry digest")
    if config.task_cwd and (not config.task_cwd.startswith("/") or ".." in Path(config.task_cwd).parts):
        raise ValueError("Task cwd must be an absolute path without traversal")
    if (
        not 30 <= config.timeout_seconds <= 7200
        or not 0.25 <= config.cpu <= 4
        or not 1024 <= config.memory_mib <= 16384
    ):
        raise ValueError("Builder must have a bounded deadline, CPU and memory allocation")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._:/@-]+", config.builder_base_image):
        raise ValueError("Invalid builder image reference")
    if config.mode == "probe":
        return None
    if not re.fullmatch(r"ghcr\.io/[a-z0-9._/-]+:[a-zA-Z0-9_.-]+", config.image_tag or "") or (
        config.image_tag.rsplit(":", 1)[1] == "latest"
    ):
        raise ValueError("Build requires a lowercase GHCR repository and explicit non-latest tag")
    if config.mode == "verify" and (
        not IMAGE.fullmatch(config.published_image or "")
        or not config.published_image.startswith(config.image_tag.rsplit(":", 1)[0] + "@sha256:")
    ):
        raise ValueError("Verification requires a fixed digest in the approved GHCR repository")
    if not config.registry_user or not config.registry_token_file or not config.context:
        raise ValueError("Build requires context, registry user and private token file")
    token_file = config.registry_token_file
    if token_file.is_symlink() or not token_file.is_file() or token_file.stat().st_mode & 0o077:
        raise ValueError("Registry token must be a private regular file (mode 0600)")
    if token_file.resolve().is_relative_to(config.context.resolve()):
        raise ValueError("Registry credentials must not be inside the build context")
    token = token_file.read_text().strip()
    if not token or any(character.isspace() for character in token):
        raise ValueError("Registry token file must contain one non-empty token")
    manifest = json.loads((config.context / "context-manifest.json").read_text())
    if manifest.get("image_binding", {}).get("original_image") != config.original_image:
        raise ValueError("Prepared context does not bind this original image")
    _context_files(config.context, manifest)
    return manifest


def _context_files(context, manifest):
    files = []
    for name, expected in manifest["files"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe context manifest path")
        source = context / path
        if source.is_symlink() or not source.is_file() or _wheel_hash(source) != expected:
            raise ValueError(f"Prepared context changed: {name}")
        files.append((source, name))
    return files


def _private_registry_target(config, token, *, allow_missing):
    """Fail closed for existing public packages; publish only to token owner's namespace."""
    owner, package = config.image_tag.removeprefix("ghcr.io/").rsplit(":", 1)[0].split("/", 1)

    def get(path):
        request = Request(
            "https://api.github.com" + path,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"},
        )
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    if get("/user").get("login", "").lower() != owner:
        raise ValueError("Private build target must belong to the authenticated GitHub user")
    try:
        package_info = get("/user/packages/container/" + quote(package, safe=""))
    except HTTPError as exc:
        if allow_missing and exc.code == 404:
            return "new_package_default_private"
        raise RuntimeError("Cannot verify GHCR package privacy") from None
    if package_info.get("visibility") != "private":
        raise ValueError("DSH image target must be a private GHCR package")
    return "private"


def _create(config):
    import modal

    version = tuple(int(part) for part in importlib.metadata.version("modal").split(".")[:2])
    if version < (1, 4):
        raise RuntimeError("Modal >= 1.4 is required for VM Sandbox filesystem transfer")
    image = (
        modal.Image.from_registry(config.builder_base_image)
        .env({"DEBIAN_FRONTEND": "noninteractive"})
        .apt_install("docker.io", "docker-buildx", "ca-certificates")
    )
    app = modal.App.lookup(config.app_name, create_if_missing=True)
    return modal.Sandbox.create(
        "/usr/bin/dockerd",
        "--host=unix:///var/run/docker.sock",
        app=app,
        image=image,
        timeout=config.timeout_seconds,
        cpu=(config.cpu, config.cpu),
        memory=config.memory_mib,
        experimental_options={"vm_runtime": True},
    )


def execute(config: BuilderConfig, *, create_sandbox=None) -> dict:
    manifest = _validate(config)
    config.output.mkdir(mode=0o700, parents=True)
    sandbox = None
    result = {
        "schema": "dsh.mimo-remote-builder.v1",
        "status": "provisioning",
        "mode": config.mode,
        "original_image": config.original_image,
        "timeout_seconds": config.timeout_seconds,
        "cpu": config.cpu,
        "memory_mib": config.memory_mib,
        "gpu": None,
        "builder_base_image": config.builder_base_image,
        "terminated": False,
    }

    def persist():
        temporary = config.output / "status.json.tmp"
        temporary.write_bytes(_json(result))
        temporary.replace(config.output / "status.json")

    persist()
    try:
        if config.mode in {"build", "verify"}:
            result["registry_privacy_before"] = _private_registry_target(
                config, config.registry_token_file.read_text().strip(), allow_missing=config.mode == "build"
            )
            persist()
        sandbox = (create_sandbox or _create)(config)
        result.update(status="running", sandbox_id=sandbox.object_id)
        persist()
        deadline = time.monotonic() + config.timeout_seconds

        def remaining():
            seconds = math.floor(deadline - time.monotonic())
            if seconds <= 0:
                raise TimeoutError("Builder deadline exhausted")
            return seconds

        def run(stage, *command, stdin=None):
            result["stage"] = stage
            persist()
            process = sandbox.exec(*command, timeout=remaining())
            if stdin is not None:
                process.stdin.write((stdin + "\n").encode())
                process.stdin.write_eof()
                process.stdin.drain()
            with ThreadPoolExecutor(max_workers=2) as executor:
                out = executor.submit(process.stdout.read)
                err = executor.submit(process.stderr.read)
                code = process.wait()
                stdout, stderr = out.result(), err.result()
            if stdin:
                stdout, stderr = stdout.replace(stdin, "[REDACTED]"), stderr.replace(stdin, "[REDACTED]")
            (config.output / f"{stage}.stdout.log").write_text(stdout)
            (config.output / f"{stage}.stderr.log").write_text(stderr)
            if code != 0:
                raise RuntimeError(f"Builder stage {stage} failed with exit code {code}")
            return stdout

        run(
            "docker-ready",
            "sh",
            "-c",
            "for i in $(seq 1 60); do docker info >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1",
        )
        info = json.loads(run("docker-info", "docker", "info", "--format", "{{json .}}"))
        (config.output / "docker-info.json").write_bytes(_json(info))
        run("pull-original", "docker", "pull", "--platform", "linux/amd64", config.original_image)
        original = json.loads(run("inspect-original", "docker", "image", "inspect", config.original_image))[0]
        (config.output / "original-inspect.json").write_bytes(_json(original))
        if not inspect_binds_image(original, config.original_image) or (
            original.get("Os"),
            original.get("Architecture"),
        ) != ("linux", "amd64"):
            raise ValueError("Pulled original image identity/platform mismatch")
        if config.mode == "probe":
            result["status"] = "probe_passed"
            return result

        assert config.context and config.image_tag and config.registry_token_file and manifest
        prepared_original = json.loads((config.context / "base-inspect.json").read_text())
        if any(original.get(key) != prepared_original.get(key) for key in ("Config", "RootFS")):
            raise ValueError("Live original image differs from context inspect")

        def runtime_path(stage, reference):
            raw = run(
                stage,
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--pull=never",
                "--entrypoint",
                "/usr/bin/env",
                reference,
            )
            paths = [line.removeprefix("PATH=") for line in raw.splitlines() if line.startswith("PATH=")]
            if len(paths) != 1:
                raise ValueError("Expected exactly one actual Docker runtime PATH")
            return paths[0]

        original_path = runtime_path("original-runtime-env", config.original_image)
        if config.task_cwd:
            run(
                "original-task-probe",
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--pull=never",
                "--workdir",
                config.task_cwd,
                "--entrypoint",
                "/bin/sh",
                config.original_image,
                "-c",
                "set -eu; pwd; command -v python3; python3 --version; command -v git; "
                "git rev-parse --show-toplevel; git rev-parse HEAD; git rev-parse HEAD^{tree}",
            )
        if config.mode == "build":
            files = _context_files(config.context, manifest)
            directories = sorted({str(Path("/build/context", name).parent) for _, name in files})
            run("context-directories", "mkdir", "-p", *directories)
            for source, name in files:
                remaining()
                sandbox.filesystem.copy_from_local(source, "/build/context/" + name)
            run(
                "build",
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "--network=none",
                "--pull=false",
                "--tag",
                config.image_tag,
                "/build/context",
            )
            smoke = json.loads(
                run(
                    "keyless-before-push",
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--pull=never",
                    "--entrypoint",
                    "/opt/dsh/bin/python",
                    config.image_tag,
                    "/opt/dsh/checks/smoke.py",
                )
            )
            (config.output / "keyless-before-push.json").write_bytes(_json(smoke))
        token = config.registry_token_file.read_text().strip()
        run(
            "registry-login",
            "docker",
            "login",
            "ghcr.io",
            "--username",
            config.registry_user,
            "--password-stdin",
            stdin=token,
        )
        del token
        if config.mode == "build":
            run("push", "docker", "push", config.image_tag)
            result["registry_privacy_after"] = _private_registry_target(
                config, config.registry_token_file.read_text().strip(), allow_missing=False
            )
            tagged = json.loads(run("inspect-pushed", "docker", "image", "inspect", config.image_tag))[0]
            repository = config.image_tag.rsplit(":", 1)[0]
            references = [ref for ref in tagged.get("RepoDigests", []) if ref.startswith(repository + "@sha256:")]
            if len(references) != 1:
                raise ValueError("Push did not produce exactly one matching immutable registry digest")
            derived_ref = references[0]
        else:
            derived_ref = config.published_image
        run("readback", "docker", "pull", derived_ref)
        derived = json.loads(run("inspect-derived", "docker", "image", "inspect", derived_ref))[0]
        runtime_environment = {
            "schema": "dsh.mimo-runtime-environment.v1",
            "original_image": config.original_image,
            "dsh_image": derived_ref,
            "original_path": original_path,
            "derived_path": runtime_path("derived-runtime-env", derived_ref),
        }
        (config.output / "runtime-environment.json").write_bytes(_json(runtime_environment))
        smoke = json.loads(
            run(
                "keyless-readback",
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--pull=never",
                "--entrypoint",
                "/opt/dsh/bin/python",
                derived_ref,
                "/opt/dsh/checks/smoke.py",
            )
        )
        (config.output / "derived-inspect.json").write_bytes(_json(derived))
        (config.output / "keyless-readback.json").write_bytes(_json(smoke))
        binding = finalize_binding(
            context=config.context,
            derived_image=derived_ref,
            derived_inspect=derived,
            smoke=smoke,
            output=config.output / "image-binding.json",
            runtime_environment=runtime_environment,
        )
        result.update(status="image_published_and_verified", image_binding=binding)
        return result
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        if sandbox is not None:
            try:
                sandbox.terminate(wait=True)
                result["terminated"] = True
            except BaseException as exc:
                result["termination_error_type"] = type(exc).__name__
                result["status"] = "cleanup_failed"
                persist()
                raise RuntimeError("Builder termination could not be verified") from exc
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "build", "verify"))
    parser.add_argument("--original-image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--cpu", type=float, default=1)
    parser.add_argument("--memory-mib", type=int, default=4096)
    parser.add_argument("--builder-base-image", default="ubuntu:24.04")
    parser.add_argument("--app-name", default="mimo-dsh-cpu-builder")
    parser.add_argument("--context", type=Path)
    parser.add_argument("--image-tag")
    parser.add_argument("--registry-user")
    parser.add_argument("--registry-token-file", type=Path)
    parser.add_argument("--published-image")
    parser.add_argument("--task-cwd")
    config = BuilderConfig(**vars(parser.parse_args()))

    def expired(_signum, _frame):
        raise TimeoutError("Client deadline exceeded (includes bounded builder-image preparation)")

    def interrupted(_signum, _frame):
        raise InterruptedError("Builder client interrupted; terminating the owned sandbox")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(config.timeout_seconds + 900)
    try:
        print(json.dumps(execute(config), sort_keys=True))
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
