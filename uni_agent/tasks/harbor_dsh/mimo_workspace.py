"""Bounded filesystem-only MiMo workspace transport; runnable with stdlib Python.

The operator captures the original Git identity before the agent starts. The
snapshot includes ignored/untracked files and deletions, but excludes .git.
Tasks whose result depends on Git metadata or non-filesystem state are outside
this lane's contract. Never execute a helper read from the student workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


def capture_base(root: Path) -> dict:
    root = root.resolve(strict=True)

    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=30).strip()

    if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("MiMo cwd must be the repository root")
    result = {"base_ref": git("rev-parse", "HEAD"), "base_tree": git("rev-parse", "HEAD^{tree}")}
    if any(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None for value in result.values()):
        raise ValueError("Invalid repository base identity")
    return result


def _name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or not path.parts
        or path.is_absolute()
        or path.as_posix() != name
        or ".." in path.parts
        or path.parts[0] == ".git"
    ):
        raise ValueError("Unsafe workspace archive path")
    return path


def _link(name: str, target: str) -> None:
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    if not target or target.startswith("/") or resolved == ".." or resolved.startswith("../"):
        raise ValueError("Workspace symlink must remain inside the workspace")
    if resolved == ".git" or resolved.startswith(".git/"):
        raise ValueError("Workspace symlink must not target Git metadata")


def _entries(root: Path, max_files: int) -> list[tuple[str, os.stat_result]]:
    entries = []
    for parent, directories, files in os.walk(root, followlinks=False):
        if Path(parent) == root:
            directories[:] = [name for name in directories if name != ".git"]
            files = [name for name in files if name != ".git"]
        for name in sorted(directories + files):
            if len(entries) >= max_files:
                raise ValueError("Workspace file budget exceeded")
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            _name(relative)
            info = path.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise ValueError("Workspace contains an unsupported filesystem object")
            if stat.S_ISLNK(info.st_mode):
                _link(relative, os.readlink(path))
            entries.append((relative, info))
    return sorted(entries)


def _identity(info):
    return info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def snapshot_workspace(root: Path, output: Path, *, max_bytes: int, max_files: int) -> dict:
    root = root.resolve(strict=True)
    if output.resolve().is_relative_to(root):
        raise ValueError("Snapshot output must be outside the workspace")
    if output.exists() or output.is_symlink():
        raise ValueError("Snapshot output already exists")
    entries = _entries(root, max_files)
    if max_bytes <= 0 or max_files <= 0 or len(entries) > max_files:
        raise ValueError("Workspace file budget exceeded")
    size = sum(info.st_size for _, info in entries if stat.S_ISREG(info.st_mode))
    # Bound both unpacked bytes and tar framing, before creating the archive.
    archive_bound = sum(512 + ((info.st_size + 511) // 512) * 512 for _, info in entries) + 10240
    if size > max_bytes or archive_bound > max_bytes:
        raise ValueError("Workspace byte budget exceeded")
    try:
        with output.open("xb") as stream, tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, before in entries:
                path = root / name
                # Archive each hardlinked regular file by value. Reproducing
                # inode sharing is unnecessary for this filesystem contract.
                archive.inodes.clear()
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                if info.isfile():
                    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(descriptor, "rb") as source:
                        if _identity(os.fstat(source.fileno())) != _identity(before):
                            raise ValueError("Workspace changed during snapshot")
                        archive.addfile(info, source)
                        if _identity(os.fstat(source.fileno())) != _identity(before):
                            raise ValueError("Workspace changed during snapshot")
                else:
                    archive.addfile(info)
                if stream.tell() > max_bytes:
                    raise ValueError("Workspace archive byte budget exceeded")
        after = _entries(root, max_files)
        if [(name, _identity(info)) for name, info in entries] != [(name, _identity(info)) for name, info in after]:
            raise ValueError("Workspace changed during snapshot")
        if output.stat().st_size > max_bytes:
            raise ValueError("Workspace archive byte budget exceeded")
        with output.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        return {"snapshot_sha256": "sha256:" + digest, "files": len(entries), "bytes": output.stat().st_size}
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def restore_workspace(root: Path, archive_path: Path, *, base_ref: str, max_bytes: int, max_files: int) -> None:
    root = root.resolve(strict=True)
    if capture_base(root)["base_ref"] != base_ref:
        raise ValueError("Independent verifier repository base differs from the captured base")
    if max_bytes <= 0 or max_files <= 0 or archive_path.stat().st_size > max_bytes:
        raise ValueError("Workspace archive budget exceeded")
    with tarfile.open(archive_path, "r:") as archive:
        members = []
        names = {}
        size = 0
        for member in archive:
            path = _name(member.name)
            if member.name in names or len(members) >= max_files:
                raise ValueError("Duplicate path or workspace file budget exceeded")
            if not (member.isfile() or member.isdir() or member.issym()) or member.mode & ~0o777:
                raise ValueError("Unsupported workspace member type or permissions")
            if member.issym():
                _link(member.name, member.linkname)
            size += member.size
            if size > max_bytes or member.size < 0:
                raise ValueError("Workspace expanded byte budget exceeded")
            names[member.name] = member
            members.append((path, member))
        for path, _ in members:
            for parent in path.parents:
                if parent.as_posix() in names and not names[parent.as_posix()].isdir():
                    raise ValueError("Workspace archive traverses a non-directory member")
        # All archive validation finishes before the original workspace changes.
        for path in root.iterdir():
            if path.name != ".git":
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        for path, member in members:
            target = root / str(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(exist_ok=True)
            elif member.issym():
                target.symlink_to(member.linkname)
            else:
                with archive.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            if not member.issym():
                target.chmod(member.mode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["capture", "snapshot", "restore"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--base-ref")
    parser.add_argument("--max-bytes", type=int, default=536870912)
    parser.add_argument("--max-files", type=int, default=100000)
    args = parser.parse_args()
    if args.action == "capture":
        result = capture_base(args.root)
    elif args.action == "snapshot":
        result = snapshot_workspace(args.root, args.archive, max_bytes=args.max_bytes, max_files=args.max_files)
    else:
        restore_workspace(
            args.root, args.archive, base_ref=args.base_ref, max_bytes=args.max_bytes, max_files=args.max_files
        )
        result = {"restored": True}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
