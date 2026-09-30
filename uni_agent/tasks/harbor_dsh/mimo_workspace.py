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


def _git(root: Path, *args: str, timeout: int = 30, allowed=(0,)) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if len(result.stdout) + len(result.stderr) > 16 * 1024 * 1024:
        raise ValueError("Git history output exceeds the operator budget")
    if result.returncode not in allowed:
        raise ValueError(f"Git history operation failed: {args[0]}: {result.stderr[-1000:]}")
    return result


def _history(root: Path, base: str) -> dict:
    ancestry = set(_git(root, "rev-list", base).stdout.splitlines())
    outside_refs = _git(root, "rev-list", "--all", "--not", base).stdout.splitlines()
    objects = _git(root, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)").stdout
    outside_objects = sorted(
        line.split()[0] for line in objects.splitlines() if line.endswith(" commit") and line.split()[0] not in ancestry
    )
    refs = _git(root, "for-each-ref", "--format=%(refname) %(objectname)").stdout.splitlines()
    return {
        "reachable_outside_base_count": len(outside_refs),
        "commit_objects_outside_base_count": len(outside_objects),
        "reachable_examples": outside_refs[:5],
        "object_examples": outside_objects[:5],
        "refs_count": len(refs),
        "ref_examples": refs[:20],
        "refs_sha256": "sha256:" + hashlib.sha256(("\n".join(refs) + "\n").encode()).hexdigest(),
    }


def _sha256_stream(stream) -> str:
    """Hash exact bytes with a fixed buffer on stdlib Python 3.8 and later."""
    digest = hashlib.sha256()
    buffer = bytearray(256 * 1024)
    view = memoryview(buffer)
    while size := stream.readinto(buffer):
        digest.update(view[:size])
    return digest.hexdigest()


def _worktree_identity(root: Path, *, max_bytes: int, max_files: int) -> str:
    records, total = [], 0
    for name, info in _entries(root, max_files):
        path = root / name
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
            if total > max_bytes:
                raise ValueError("Workspace byte budget exceeded during history admission")
            with path.open("rb") as stream:
                identity = _sha256_stream(stream)
        elif stat.S_ISLNK(info.st_mode):
            identity = os.readlink(path)
        else:
            identity = "directory"
        records.append((name, stat.S_IMODE(info.st_mode), identity))
    return "sha256:" + hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


def _strip_history(root: Path, base: str) -> None:
    # Same cleanup as upstream DatasetEnvironment._strip_future_commits at
    # 467f0a19016f0ac4d63b8d17a1f0da9ba07f232c. Detach by updating only HEAD:
    # checkout/reset must not discard task-image compatibility modifications.
    _git(root, "update-ref", "--no-deref", "HEAD", base)
    for remote in _git(root, "remote").stdout.splitlines():
        _git(root, "remote", "remove", remote)
    for ref in _git(root, "for-each-ref", "--format=%(refname)").stdout.splitlines():
        if ref.startswith("refs/tags/"):
            ancestor = _git(root, "merge-base", "--is-ancestor", ref, base, allowed=(0, 1, 128))
            if ancestor.returncode == 0:
                continue
        _git(root, "update-ref", "--no-deref", "-d", ref)
    git_dir = root / ".git"
    for name in ("ORIG_HEAD", "FETCH_HEAD", "MERGE_HEAD", "AUTO_MERGE", "REBASE_HEAD", "CHERRY_PICK_HEAD"):
        (git_dir / name).unlink(missing_ok=True)
    _git(root, "reflog", "expire", "--expire=now", "--all")
    _git(root, "-c", "gc.pruneExpire=now", "-c", "gc.cruftPacks=false", "gc", "--prune=now", timeout=120)


def capture_base(
    root: Path, *, history_policy: str = "reject", max_bytes: int = 536870912, max_files: int = 100000
) -> dict:
    root = root.resolve(strict=True)
    if history_policy not in {"reject", "strip"}:
        raise ValueError("History policy must be reject or explicit strip")

    def git(*args):
        return _git(root, *args).stdout.strip()

    if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("MiMo cwd must be the repository root")
    result = {"base_ref": git("rev-parse", "HEAD"), "base_tree": git("rev-parse", "HEAD^{tree}")}
    if any(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None for value in result.values()):
        raise ValueError("Invalid repository base identity")
    git_dir = root / ".git"
    if (
        not git_dir.is_dir()
        or git_dir.is_symlink()
        or Path(git("rev-parse", "--absolute-git-dir")).resolve() != git_dir
        or (git_dir / "objects/info/alternates").exists()
        or (git_dir / "info/grafts").exists()
    ):
        raise ValueError("History admission requires an independent Git directory without alternates/grafts")
    before = _history(root, result["base_ref"])
    if history_policy == "reject" and (
        before["reachable_outside_base_count"] or before["commit_objects_outside_base_count"]
    ):
        raise ValueError("MiMo image history is not truncated; explicit strip policy required")
    worktree = _worktree_identity(root, max_bytes=max_bytes, max_files=max_files)
    if history_policy == "strip":
        _strip_history(root, result["base_ref"])
    after = _history(root, result["base_ref"])
    if (
        after["reachable_outside_base_count"]
        or after["commit_objects_outside_base_count"]
        or git("rev-parse", "HEAD") != result["base_ref"]
        or git("rev-parse", "HEAD^{tree}") != result["base_tree"]
        or _worktree_identity(root, max_bytes=max_bytes, max_files=max_files) != worktree
    ):
        raise ValueError("Git history admission did not preserve a clean baseline and exact workspace")
    result["history"] = {
        "policy": history_policy,
        "before": before,
        "after": after,
        "worktree_sha256": worktree,
        "workspace_preserved": True,
    }
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
    try:
        output.resolve().relative_to(root)
    except ValueError:
        pass
    else:
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
            digest = _sha256_stream(source)
        return {"snapshot_sha256": "sha256:" + digest, "files": len(entries), "bytes": output.stat().st_size}
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def restore_workspace(
    root: Path, archive_path: Path, *, base_ref: str, max_bytes: int, max_files: int, history_policy: str = "reject"
) -> dict:
    root = root.resolve(strict=True)
    if _git(root, "rev-parse", "HEAD").stdout.strip() != base_ref:
        raise ValueError("Independent verifier repository base differs from the captured base")
    admission = capture_base(root, history_policy=history_policy, max_bytes=max_bytes, max_files=max_files)
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
    return admission


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["capture", "snapshot", "restore"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--base-ref")
    parser.add_argument("--max-bytes", type=int, default=536870912)
    parser.add_argument("--max-files", type=int, default=100000)
    parser.add_argument("--history-policy", choices=("reject", "strip"), default="reject")
    args = parser.parse_args()
    if args.action == "capture":
        result = capture_base(
            args.root, history_policy=args.history_policy, max_bytes=args.max_bytes, max_files=args.max_files
        )
    elif args.action == "snapshot":
        result = snapshot_workspace(args.root, args.archive, max_bytes=args.max_bytes, max_files=args.max_files)
    else:
        admission = restore_workspace(
            args.root,
            args.archive,
            base_ref=args.base_ref,
            max_bytes=args.max_bytes,
            max_files=args.max_files,
            history_policy=args.history_policy,
        )
        result = {"restored": True, "history_admission": admission}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
