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
    assert command("restore", verifier, "--archive", archive, "--base-ref", base["base_ref"]) == {"restored": True}
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
