"""Prepare an offline DSH layer on a digest-pinned original MiMo task image.

This does not pull, build, push, provision, or probe an endpoint. The portable
CPython archive is an explicit, independently pinned operator input, because
the task image's own Python and packages must remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import tarfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from deployment.bootstrap.prepare_harbor_context import SOURCE_MAP, _git, _wheel_hash

SOURCE_PATHS = tuple(path for path in SOURCE_MAP.values() if path != "deployment/harbor/Dockerfile")
SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}")
USER = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*(?::[a-zA-Z0-9_][a-zA-Z0-9_.-]*)?")


def _json(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def inspect_binds_image(inspected: dict, expected: str) -> bool:
    """Docker omits docker.io in RepoDigests; preserve repository and digest."""
    references = inspected.get("RepoDigests", [])
    return expected in references or (
        expected.startswith("docker.io/") and expected.removeprefix("docker.io/") in references
    )


def validate_gateway_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Gateway must be an HTTPS origin without path, credentials, query, or fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid Gateway port") from exc
    return value


def _validate_archive(path: Path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        total_size = 0
        for member in members:
            parts = PurePosixPath(member.name).parts
            total_size += member.size
            if (
                not parts
                or parts[0] != "python"
                or ".." in parts
                or not (member.isfile() or member.isdir() or member.issym() or member.islnk())
            ):
                raise ValueError("Python archive contains an unsafe entry")
            if member.issym() or member.islnk():
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(member.name), member.linkname)
                    if member.issym()
                    else member.linkname
                )
                if not target.startswith("python/"):
                    raise ValueError("Python archive link escapes its prefix")
        if total_size > 1024**3 or not any(m.name == "python/bin/python3.12" and m.isfile() for m in members):
            raise ValueError("Expected a bounded CPython 3.12 install-only archive")


def _validate_lock(lock):
    if (
        lock.get("schema") != "dsh.mimo-release-lock.v1"
        or lock.get("dsh_revision") != "b2369692ea530007075ebcd18d39fdba0bbd3982"
        or lock.get("python_distribution_version") != "0.1.3a2"
        or lock.get("profile") != "sdk-minimal"
        or lock.get("patches") != []
        or lock.get("runtime_mode") != "exe"
        or lock.get("runner_python") != "/opt/dsh/bin/python"
        or lock.get("platform") != "linux/amd64"
        or lock.get("python_version") != "3.12"
    ):
        raise ValueError("Expected the fixed b236969 / 0.1.3a2 MiMo DSH release")
    wheels = lock.get("wheels", {})
    if not isinstance(wheels, dict) or not wheels:
        raise ValueError("Release lock must contain wheel hashes")
    for name, digest in wheels.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*\.whl", name) or not SHA.fullmatch(digest):
            raise ValueError("Invalid locked wheel")
    for name in ("runtime_binary_sha256", "runtime_rg_sha256"):
        if not SHA.fullmatch(lock.get(name, "")):
            raise ValueError("Missing runtime binary identity")


def prepare_context(
    *,
    repo: Path,
    source_commit: str,
    artifact_dir: Path,
    python_archive: Path,
    python_sha256: str,
    original_image: str,
    base_inspect: dict,
    gateway_origin: str,
    lock: dict,
    output: Path,
) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output context must be new")
    _validate_lock(lock)
    validate_gateway_origin(gateway_origin)
    if not IMAGE.fullmatch(original_image):
        raise ValueError("Original image must be a registry repository@sha256 digest")
    config = base_inspect.get("Config") or {}
    base_user = config.get("User") or "root"
    if (
        base_inspect.get("Os") != "linux"
        or base_inspect.get("Architecture") != "amd64"
        or not inspect_binds_image(base_inspect, original_image)
        or config.get("OnBuild")
        or not USER.fullmatch(base_user)
    ):
        raise ValueError("Base inspect must bind an amd64 registry digest, safe user, and no ONBUILD hooks")
    if not COMMIT.fullmatch(source_commit):
        raise ValueError("Source commit must be a full Git SHA")
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ValueError("Artifact directory must be a real directory")
    if python_archive.is_symlink() or not SHA.fullmatch(python_sha256) or _wheel_hash(python_archive) != python_sha256:
        raise ValueError("Portable Python archive digest mismatch")
    _validate_archive(python_archive)
    for name, expected in lock["wheels"].items():
        path = artifact_dir / name
        if path.is_symlink() or not path.is_file() or _wheel_hash(path) != expected:
            raise ValueError(f"Locked wheel missing or changed: {name}")
    source = {"source/" + name: _git(repo, "show", f"{source_commit}:{name}") for name in SOURCE_PATHS}
    build_inputs = {
        "lock": lock,
        "source_commit": source_commit,
        "source_files": {name.removeprefix("source/"): _sha(data) for name, data in source.items()},
    }
    dockerfile = (
        f"FROM {original_image}\nUSER root\n"
        'RUN ["/bin/sh", "-c", "test ! -e /opt/dsh && test ! -L /opt/dsh && '
        'test ! -e /opt/dsh-build && test ! -L /opt/dsh-build"]\n'
        "COPY python.tar.gz /opt/dsh-build/python.tar.gz\n"
        'RUN ["/bin/sh", "-c", "mkdir /opt/dsh && tar -xzf /opt/dsh-build/python.tar.gz '
        '-C /opt/dsh --strip-components=1"]\n'
        "COPY wheelhouse/ /opt/dsh-build/wheelhouse/\n"
        "COPY source/ /opt/dsh-build/source/\n"
        "COPY install.py build-inputs.json /opt/dsh-build/\n"
        'RUN ["/opt/dsh/bin/python3.12", "-I", "/opt/dsh-build/install.py"]\n'
        "COPY smoke.py /opt/dsh/checks/smoke.py\n"
        f"USER {base_user}\n"
    ).encode()
    files = {
        **source,
        "Dockerfile": dockerfile,
        "install.py": Path(__file__).with_name("install.py").read_bytes(),
        "smoke.py": Path(__file__).with_name("smoke.py").read_bytes(),
        "build-inputs.json": _json(build_inputs),
        "base-inspect.json": _json(base_inspect),
    }
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, content in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    copied = {"python.tar.gz": (python_archive, python_sha256)}
    copied.update({"wheelhouse/" + name: (artifact_dir / name, digest) for name, digest in lock["wheels"].items()})
    for name, (source_path, expected) in copied.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as destination:
            if _wheel_hash(source_path, destination) != expected:
                raise ValueError("Artifact changed while preparing context")
    hashes = {p.relative_to(output).as_posix(): _wheel_hash(p) for p in output.rglob("*") if p.is_file()}
    receipt = {
        "schema": "dsh.mimo-image-context.v1",
        "status": "prepared_not_built",
        "image_binding": {"original_image": original_image, "dsh_image": None},
        "platform": "linux/amd64",
        "source_commit": source_commit,
        "runtime_binary_sha256": lock["runtime_binary_sha256"],
        "lock_sha256": _sha(_json(lock)),
        "runner_python": lock["runner_python"],
        "profile": lock["profile"],
        "patches": [],
        "gateway_origin": gateway_origin,
        "gateway_route_verified": False,
        "base_user": config.get("User", ""),
        "files": hashes,
    }
    (output / "context-manifest.json").write_bytes(_json(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "artifact-dir", "python-archive", "base-inspect", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-commit", "python-sha256", "original-image", "gateway-origin"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("dsh-release-lock.json"))
    args = vars(parser.parse_args())
    args["lock"] = json.loads(args["lock"].read_text())
    inspected = json.loads(args["base_inspect"].read_text())
    args["base_inspect"] = inspected[0] if isinstance(inspected, list) and len(inspected) == 1 else inspected
    print(json.dumps(prepare_context(**args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
