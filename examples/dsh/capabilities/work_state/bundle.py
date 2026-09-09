"""Byte-preserving, controller-owned multi-file snapshots. Never repair model content."""

import base64
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from uni_agent.tasks.dsh.memory_artifacts import _directory, _read, _relative, _write

SCHEMA = "dsh.work-state-bundle.v1"


def _allowed(values):
    if isinstance(values, str | bytes):
        raise ValueError("Expected an exact path sequence")
    values = list(values)
    if any(not isinstance(value, str) for value in values):
        raise ValueError("Expected string paths")
    if len(values) > 64 or len(values) != len(set(values)):
        raise ValueError("Duplicate or excessive allowed paths")
    for value in values:
        if len(value) > 256 or "\x00" in value:
            raise ValueError("Invalid path length")
        _relative(value)
    ordered = sorted(values)
    if any(b.startswith(a + "/") for a in ordered for b in ordered):
        raise ValueError("A file cannot also be a parent directory")
    return ordered


def _limit(value):
    if type(value) is not int or not 0 < value <= 16 * 1024 * 1024:
        raise ValueError("Invalid bundle budget")


def _parent(root_fd, relative, create=False):
    fd = os.dup(root_fd)
    try:
        for part in _relative(relative)[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def pack_bundle(source_root: Path, allowed_paths: Sequence[str], max_bytes=65536) -> bytes:
    _limit(max_bytes)
    allowed = _allowed(allowed_paths)
    files, missing, total = {}, [], 0
    root_fd = _directory(Path(source_root))
    try:
        for relative in allowed:
            try:
                parent = _parent(root_fd, relative)
                try:
                    raw = _read(parent, _relative(relative)[-1], max_bytes)
                finally:
                    os.close(parent)
            except FileNotFoundError:
                missing.append(relative)
                continue
            total += len(raw)
            if total > max_bytes:
                raise ValueError("Bundle exceeds total byte budget")
            files[relative] = dict(base64=base64.b64encode(raw).decode("ascii"), sha256=_sha(raw), size=len(raw))
    finally:
        os.close(root_fd)
    return json.dumps(
        dict(schema=SCHEMA, files=files, missing=missing), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def unpack_bundle(bundle: bytes, target_root: Path, allowed_paths: Sequence[str], *, max_bytes=65536) -> dict:
    _limit(max_bytes)
    allowed = _allowed(allowed_paths)
    if not isinstance(bundle, bytes) or len(bundle) > max_bytes * 2 + 65536:
        raise ValueError("Invalid bundle byte envelope")
    record = json.loads(bundle, object_pairs_hook=_object)
    if not isinstance(record, dict) or set(record) != {"schema", "files", "missing"} or record["schema"] != SCHEMA:
        raise ValueError("Invalid bundle schema")
    files, missing = record["files"], record["missing"]
    if not isinstance(files, dict) or not isinstance(missing, list):
        raise ValueError("Invalid bundle inventory")
    if _allowed(list(files) + missing) != allowed:
        raise ValueError("Inventory does not exactly partition allowed paths")
    decoded, inventory, total = {}, {}, 0
    for name, entry in files.items():
        if not isinstance(entry, dict) or set(entry) != {"base64", "sha256", "size"}:
            raise ValueError("Invalid file inventory entry")
        if not isinstance(entry["base64"], str):
            raise ValueError("Expected base64 text")
        raw = base64.b64decode(entry["base64"], validate=True)
        total += len(raw)
        if type(entry["size"]) is not int or entry["size"] != len(raw) or _sha(raw) != entry["sha256"]:
            raise ValueError("File content hash/size mismatch")
        if total > max_bytes:
            raise ValueError("Bundle exceeds total byte budget")
        decoded[name], inventory[name] = raw, dict(sha256=entry["sha256"], size=len(raw))
    target = Path(target_root).absolute()
    _relative(target.name)
    parent = _directory(target.parent)
    try:
        os.mkdir(target.name, 0o700, dir_fd=parent)
        root_fd = os.open(target.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        for name, raw in sorted(decoded.items()):
            parent = _parent(root_fd, name, create=True)
            try:
                _write(parent, _relative(name)[-1], raw)
                if _read(parent, _relative(name)[-1], max_bytes, private=True) != raw:
                    raise ValueError("Materialized file changed")
            finally:
                os.close(parent)
    finally:
        os.close(root_fd)
    return dict(files=inventory, missing=sorted(missing))
