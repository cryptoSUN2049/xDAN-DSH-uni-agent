import hashlib
import io
import json
import subprocess
import tarfile

import pytest

from uni_agent.tasks.harbor_dsh.mimo_workspace import capture_base, restore_workspace, snapshot_workspace
from uni_agent.tasks.harbor_dsh.mimo_workspace import main as workspace_main

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def repository(root):
    root.mkdir()
    git(root, "init", "-q")
    (root / "old.txt").write_text("original")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "initial")
    return root


@pytest.mark.parametrize("size", [0, 513, 262161, 1048579])
def test_stream_hash_preserves_exact_sha_with_bounded_reads(size):
    from uni_agent.tasks.harbor_dsh.mimo_workspace import _sha256_stream

    data = (bytes(range(256)) * ((size + 255) // 256))[:size]

    class BoundedStream(io.BytesIO):
        def readinto(self, buffer):
            assert len(buffer) <= 1024 * 1024
            return super().readinto(buffer)

    assert _sha256_stream(BoundedStream(data)) == hashlib.sha256(data).hexdigest()


class LegacyArchivePath:
    """Expose old pathlib APIs without changing the host's pathlib internals."""

    def __init__(self, path):
        self.path = path

    def resolve(self):
        return LegacyArchivePath(self.path.resolve())

    def __getattr__(self, name):
        if name == "is_relative_to":
            raise AttributeError(name)
        return getattr(self.path, name)


@pytest.mark.parametrize("relative", [".", "inside.tar", "nested/inside.tar"])
def test_snapshot_rejects_workspace_output_without_newer_pathlib_api(tmp_path, relative):
    root = repository(tmp_path / "repo")
    with pytest.raises(ValueError, match="outside the workspace"):
        snapshot_workspace(root, LegacyArchivePath(root / relative), max_bytes=100000, max_files=100)
    assert (root / "old.txt").read_text() == "original"


def test_workspace_transport_needs_no_newer_hashlib_or_pathlib_api(tmp_path, monkeypatch):
    monkeypatch.delattr(hashlib, "file_digest", raising=False)
    student = repository(tmp_path / "repo")
    verifier = tmp_path / "verifier"
    git(student, "clone", "-q", str(student), str(verifier))
    base = capture_base(student)
    archive = tmp_path / "repo-sibling" / "snapshot.tar"
    archive.parent.mkdir()
    receipt = snapshot_workspace(student, LegacyArchivePath(archive), max_bytes=100000, max_files=100)
    assert receipt["snapshot_sha256"] == "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    restore_workspace(verifier, archive, base_ref=base["base_ref"], max_bytes=100000, max_files=100)
    assert (verifier / "old.txt").read_text() == "original"


def test_workspace_command_interface_captures_transports_and_restores(tmp_path, monkeypatch, capsys):
    student = repository(tmp_path / "student")
    verifier = tmp_path / "verifier"
    git(student, "clone", "-q", str(student), str(verifier))

    def command(*args):
        monkeypatch.setattr("sys.argv", ["mimo-workspace", *map(str, args)])
        workspace_main()
        return json.loads(capsys.readouterr().out)

    base = command("capture", student)
    (student / "new.txt").write_text("edited")
    archive = tmp_path / "snapshot.tar"
    snapshot = command("snapshot", student, "--archive", archive)
    assert snapshot["files"] == 2
    restored = command("restore", verifier, "--archive", archive, "--base-ref", base["base_ref"])
    assert restored["restored"] is True
    assert restored["history_admission"]["base_ref"] == base["base_ref"]
    assert (verifier / "new.txt").read_text() == "edited"


def test_workspace_preserves_new_deleted_binary_executable_and_symlink_files(tmp_path):
    student = repository(tmp_path / "student")
    verifier = tmp_path / "verifier"
    git(student, "clone", "-q", str(student), str(verifier))
    base = capture_base(student)
    (student / "old.txt").unlink()
    (student / ".hidden").write_bytes(b"\x00\xffbinary")
    (student / "script").write_text("#!/bin/sh\nexit 0\n")
    (student / "script").chmod(0o751)
    (student / "link").symlink_to("script")
    archive = tmp_path / "workspace.tar"
    snapshot = snapshot_workspace(student, archive, max_bytes=100000, max_files=100)
    restore_workspace(verifier, archive, base_ref=base["base_ref"], max_bytes=100000, max_files=100)
    assert not (verifier / "old.txt").exists()
    assert (verifier / ".hidden").read_bytes() == b"\x00\xffbinary"
    assert (verifier / "script").stat().st_mode & 0o777 == 0o751
    assert (verifier / "link").is_symlink()
    assert git(verifier, "rev-parse", "HEAD") == base["base_ref"]
    assert snapshot["files"] == 3


@pytest.mark.parametrize("name", ["../escape", "/escape", ".git/config", "a/../../escape"])
def test_restore_rejects_unsafe_archive_before_mutating_repository(tmp_path, name):
    root = repository(tmp_path / "repo")
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as output:
        info = tarfile.TarInfo(name)
        info.size = 1
        output.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        restore_workspace(root, archive, base_ref=capture_base(root)["base_ref"], max_bytes=100000, max_files=100)
    assert (root / "old.txt").read_text() == "original"


def test_snapshot_rejects_external_symlink_and_file_budget(tmp_path):
    root = repository(tmp_path / "repo")
    (root / "escape").symlink_to("../outside")
    with pytest.raises(ValueError, match="symlink"):
        snapshot_workspace(root, tmp_path / "bad.tar", max_bytes=100000, max_files=100)
    (root / "escape").unlink()
    with pytest.raises(ValueError, match="budget"):
        snapshot_workspace(root, tmp_path / "large.tar", max_bytes=1, max_files=100)


def test_restore_rejects_wrong_base_before_mutation(tmp_path):
    root = repository(tmp_path / "repo")
    archive = tmp_path / "workspace.tar"
    snapshot_workspace(root, archive, max_bytes=100000, max_files=100)
    with pytest.raises(ValueError, match="base"):
        restore_workspace(root, archive, base_ref="0" * 40, max_bytes=100000, max_files=100)
    assert (root / "old.txt").read_text() == "original"


def test_existing_snapshot_is_never_overwritten_or_removed(tmp_path):
    root = repository(tmp_path / "repo")
    archive = tmp_path / "existing.tar"
    archive.write_bytes(b"owned evidence")
    with pytest.raises(ValueError, match="already exists"):
        snapshot_workspace(root, archive, max_bytes=100000, max_files=100)
    assert archive.read_bytes() == b"owned evidence"


def test_snapshot_includes_nested_and_hardlinked_files(tmp_path):
    import os

    root = repository(tmp_path / "repo")
    verifier = tmp_path / "verifier"
    git(root, "clone", "-q", str(root), str(verifier))
    (root / "sub").mkdir()
    (root / "sub/file").write_text("new content")
    os.link(root / "sub/file", root / "hardlink")
    archive = tmp_path / "full.tar"
    snapshot_workspace(root, archive, max_bytes=100000, max_files=100)
    restore_workspace(verifier, archive, base_ref=capture_base(root)["base_ref"], max_bytes=100000, max_files=100)
    assert (verifier / "sub/file").read_text() == (verifier / "hardlink").read_text() == "new content"


@pytest.mark.parametrize(
    "case", ["duplicate", "external-symlink", "symlink-parent", "device", "setuid", "files", "bytes"]
)
def test_malformed_archive_is_rejected_without_partial_restore(tmp_path, case):
    root = repository(tmp_path / "repo")
    archive = tmp_path / "invalid.tar"
    with tarfile.open(archive, "w") as output:
        info = tarfile.TarInfo("x")
        if case in {"external-symlink", "symlink-parent"}:
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside" if case == "external-symlink" else "inside"
        elif case == "device":
            info.type = tarfile.CHRTYPE
        elif case == "setuid":
            info.mode = 0o4777
        output.addfile(info)
        if case in {"duplicate", "symlink-parent", "files"}:
            second = tarfile.TarInfo("x" if case == "duplicate" else "x/child" if case == "symlink-parent" else "y")
            output.addfile(second)
    with pytest.raises(ValueError):
        restore_workspace(
            root,
            archive,
            base_ref=capture_base(root)["base_ref"],
            max_bytes=1 if case == "bytes" else 100000,
            max_files=1 if case == "files" else 100,
        )
    assert (root / "old.txt").read_text() == "original"


def test_capture_rejects_nested_repository_workdir(tmp_path):
    root = repository(tmp_path / "repo")
    (root / "nested").mkdir()
    with pytest.raises(ValueError, match="repository root"):
        capture_base(root / "nested")


def future_repository(root):
    root = repository(root)
    base = git(root, "rev-parse", "HEAD")
    git(root, "tag", "ancestor-release")
    (root / "old.txt").write_text("future reference fix")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "future")
    future = git(root, "rev-parse", "HEAD")
    git(root, "tag", "future-release")
    git(root, "update-ref", "refs/remotes/origin/main", future)
    git(root, "remote", "add", "origin", "https://example.invalid/repo")
    git(root, "checkout", "-q", "--detach", base)
    return root, base, future


def test_default_history_rejects_future_without_mutating_refs_or_worktree(tmp_path):
    root, base, future = future_repository(tmp_path / "repo")
    refs = git(root, "show-ref")
    with pytest.raises(ValueError, match="history is not truncated"):
        capture_base(root)
    assert git(root, "show-ref") == refs
    assert git(root, "rev-parse", "HEAD") == base
    assert git(root, "cat-file", "-t", future) == "commit"
    assert (root / "old.txt").read_text() == "original"


def test_strip_preserves_dirty_workspace_base_and_ancestor_tag_and_prunes_future(tmp_path):
    root, base, future = future_repository(tmp_path / "repo")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    (root / "old.txt").write_text("uncommitted compatibility changes")
    (root / "binary").write_bytes(b"\x00\xff")
    (root / "binary").chmod(0o751)
    (root / "link").symlink_to("binary")
    state = capture_base(root, history_policy="strip")
    assert state["base_ref"] == base and state["base_tree"] == tree
    assert state["history"]["workspace_preserved"] is True
    assert state["history"]["before"]["reachable_outside_base_count"] == 1
    assert state["history"]["after"]["commit_objects_outside_base_count"] == 0
    assert git(root, "tag", "--list") == "ancestor-release"
    assert git(root, "remote") == ""
    assert git(root, "reflog", "--all") == ""
    assert subprocess.run(["git", "-C", str(root), "cat-file", "-e", future], capture_output=True).returncode != 0
    assert (root / "old.txt").read_text() == "uncommitted compatibility changes"
    assert (root / "binary").read_bytes() == b"\x00\xff"
    assert (root / "binary").stat().st_mode & 0o777 == 0o751
    assert (root / "link").is_symlink()
    assert capture_base(root)["base_ref"] == base


def test_reflog_only_future_is_rejected_then_physically_pruned(tmp_path):
    root, base, future = future_repository(tmp_path / "repo")
    for ref in git(root, "for-each-ref", "--format=%(refname)").splitlines():
        git(root, "update-ref", "-d", ref)
    assert git(root, "rev-list", "--all", "--not", base) == ""
    with pytest.raises(ValueError, match="history is not truncated"):
        capture_base(root)
    state = capture_base(root, history_policy="strip")
    assert state["history"]["before"]["commit_objects_outside_base_count"] == 1
    assert subprocess.run(["git", "-C", str(root), "cat-file", "-e", future], capture_output=True).returncode != 0


def test_gc_failure_is_not_accepted(tmp_path, monkeypatch):
    from uni_agent.tasks.harbor_dsh import mimo_workspace

    root, _, _ = future_repository(tmp_path / "repo")
    original = mimo_workspace._git

    def failing_git(path, *args, **kwargs):
        if "gc" in args:
            raise ValueError("simulated GC failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(mimo_workspace, "_git", failing_git)
    with pytest.raises(ValueError, match="GC failure"):
        capture_base(root, history_policy="strip")


def test_restore_applies_same_explicit_history_policy(tmp_path):
    root, base, _ = future_repository(tmp_path / "repo")
    archive = tmp_path / "workspace.tar"
    snapshot_workspace(root, archive, max_bytes=100000, max_files=100)
    with pytest.raises(ValueError, match="history is not truncated"):
        restore_workspace(root, archive, base_ref=base, max_bytes=100000, max_files=100)
    restore_workspace(root, archive, base_ref=base, max_bytes=100000, max_files=100, history_policy="strip")
    assert (root / "old.txt").read_text() == "original"
