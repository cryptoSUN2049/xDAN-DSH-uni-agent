"""Controller-owned single-file memory snapshots; no SDK, reward or sandbox.

The controller must retain the returned manifest digest independently and create
fresh reader processes/workspaces itself. A different session string alone does
not prove isolation. Source versions are explicit operator assertions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_SCHEMA = "dsh.memory-artifact.v1"
_FIELDS = {"schema", "chain_id", "writer_session_id", "source_version", "source_path", "content_sha256", "size_bytes"}


@dataclass(frozen=True)
class FrozenMemoryArtifact:
    manifest_sha256: str
    content_sha256: str
    size_bytes: int


@dataclass(frozen=True)
class LoadedMemoryArtifact:
    content: bytes
    content_sha256: str
    manifest_sha256: str
    chain_id: str
    writer_session_id: str
    reader_session_id: str
    source_version: str


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _identity(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise ValueError("Invalid explicit memory identity")


def _digest(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("Invalid expected memory digest")


def _budget(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("Memory budget must be a positive integer")


def _relative(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Expected an exact relative file whitelist")
    parts = value.split("/")
    if PurePosixPath(value).is_absolute() or any(p in ("", ".", "..") for p in parts):
        raise ValueError("Memory source path escapes its whitelist")
    return tuple(parts)


def _directory(path: Path) -> int:
    absolute = Path(path).absolute()
    if ".." in absolute.parts:
        raise ValueError("Directory traversal is forbidden")
    fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink


def _read(parent: int, name: str, limit: int, *, private: bool = False) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise ValueError("Memory requires a bounded single-link regular file")
        if private and (before.st_uid != os.getuid() or before.st_mode & 0o077):
            raise ValueError("Frozen memory must be private and owned")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if len(raw) > limit or _signature(before) != _signature(after) or _signature(after) != _signature(current):
            raise ValueError("Memory file changed during snapshot read")
        return raw


def _write(parent: int, name: str, raw: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    with os.fdopen(fd, "wb") as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError("Filesystem did not enforce private artifact creation")
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def freeze_memory_artifact(
    *,
    source_root: Path,
    relative_path: str,
    expected_source_sha256: str,
    source_version: str,
    chain_id: str,
    writer_session_id: str,
    max_bytes: int,
    output_dir: Path,
) -> FrozenMemoryArtifact:
    for value in (source_version, chain_id, writer_session_id):
        _identity(value)
    _budget(max_bytes)
    _digest(expected_source_sha256)
    parts = _relative(relative_path)
    root = _directory(source_root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            os.close(root)
            root = child
        raw = _read(root, parts[-1], max_bytes)
    finally:
        os.close(root)
    if _sha(raw) != expected_source_sha256:
        raise ValueError("Source memory digest mismatch")
    manifest = dict(
        schema=_SCHEMA,
        chain_id=chain_id,
        writer_session_id=writer_session_id,
        source_version=source_version,
        source_path=relative_path,
        content_sha256=_sha(raw),
        size_bytes=len(raw),
    )
    manifest_raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(manifest_raw) > 16384:
        raise ValueError("Memory manifest exceeds fixed budget")
    target = Path(output_dir).absolute()
    parent = _directory(target.parent)
    try:
        os.mkdir(target.name, 0o700, dir_fd=parent)
        child = os.open(target.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(child)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Filesystem did not enforce private directory creation")
            _write(child, "memory.bin", raw)
            _write(child, "manifest.json", manifest_raw)
            os.fsync(child)
        finally:
            os.close(child)
        os.fsync(parent)
    finally:
        os.close(parent)
    return FrozenMemoryArtifact(_sha(manifest_raw), _sha(raw), len(raw))


def _manifest(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate memory manifest field")
            result[key] = value
        return result

    value = json.loads(
        raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON"))
    )
    if not isinstance(value, dict) or set(value) != _FIELDS or value["schema"] != _SCHEMA:
        raise ValueError("Invalid frozen memory manifest")
    return value


def load_memory_artifact(
    *,
    directory: Path,
    expected_manifest_sha256: str,
    chain_id: str,
    writer_session_id: str,
    source_version: str,
    reader_session_id: str,
    max_bytes: int,
) -> LoadedMemoryArtifact:
    for value in (chain_id, writer_session_id, source_version, reader_session_id):
        _identity(value)
    if reader_session_id == writer_session_id:
        raise ValueError("Memory reader must use a new session identity")
    _budget(max_bytes)
    _digest(expected_manifest_sha256)
    root = _directory(directory)
    try:
        info = os.fstat(root)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Frozen directory must be private and owned")
        raw_manifest = _read(root, "manifest.json", 16384, private=True)
        if _sha(raw_manifest) != expected_manifest_sha256:
            raise ValueError("Frozen manifest digest mismatch")
        manifest = _manifest(raw_manifest)
        for key, expected in {
            "chain_id": chain_id,
            "writer_session_id": writer_session_id,
            "source_version": source_version,
        }.items():
            if manifest[key] != expected:
                raise ValueError("Frozen memory identity mismatch")
        _relative(manifest["source_path"])
        _digest(manifest["content_sha256"])
        if type(manifest["size_bytes"]) is not int or not 0 <= manifest["size_bytes"] <= max_bytes:
            raise ValueError("Frozen memory size exceeds reader budget")
        content = _read(root, "memory.bin", max_bytes, private=True)
        if len(content) != manifest["size_bytes"] or _sha(content) != manifest["content_sha256"]:
            raise ValueError("Frozen memory content mismatch")
    finally:
        os.close(root)
    return LoadedMemoryArtifact(
        content,
        manifest["content_sha256"],
        expected_manifest_sha256,
        chain_id,
        writer_session_id,
        reader_session_id,
        source_version,
    )
