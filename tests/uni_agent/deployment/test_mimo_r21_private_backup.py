"""Only synthetic credentials are used; no Pod API, GPU or live private tree is accessed."""

import importlib.util
import io
import os
import sys
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.exceptions import InvalidTag


@pytest.fixture
def backup(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r21_private_backup.py"
    spec = importlib.util.spec_from_file_location("private_backup_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    key = private / "backup-key.bin"
    key.write_bytes(b"K" * 32)
    key.chmod(0o600)
    monkeypatch.setattr(module, "PRIVATE", private)
    monkeypatch.setattr(module, "DESTINATION", tmp_path / "encrypted")
    monkeypatch.setenv("RUNPOD_POD_ID", module.POD)
    netrc = tmp_path / "synthetic-netrc"
    monkeypatch.setattr(module, "Path", lambda p: netrc if p == "/root/.netrc" else Path(p))
    return module, private, key, netrc


def unpack(module, report, key):
    sealed = Path(report["path"]).read_bytes()
    raw = module.AESGCM(key).decrypt(sealed[:12], sealed[12:], module.AAD)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        assert all(member.isfile() for member in archive.getmembers())
        return {member.name: archive.extractfile(member).read() for member in archive.getmembers()}


def test_authenticated_roundtrip_filters_private_artifacts(backup, tmp_path):
    module, private, key, netrc = backup
    raw = b"synthetic-private-payload-not-a-real-credential"
    (private / "raw.json").write_bytes(raw)
    nested = private / "nested"
    nested.mkdir()
    (nested / "run-spec.json").write_text('{"synthetic": true}')
    netrc.write_text("synthetic-netrc-only")
    for folder in [private / "bin", nested / "token-journal"]:
        folder.mkdir()
        (folder / "excluded").write_text("excluded")
    large = private / "large.log"
    with large.open("wb") as output:
        output.truncate(16 * 1024 * 1024 + 1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "never-archive").write_text("synthetic outside")
    (private / "linked-directory").symlink_to(outside, target_is_directory=True)
    (private / "linked-file").symlink_to(outside / "never-archive")
    os.mkfifo(private / "socket-like-fifo")
    report = module.backup()
    members = unpack(module, report, key.read_bytes())
    assert members == {
        "private/raw.json": raw,
        "private/nested/run-spec.json": b'{"synthetic": true}',
        "root-netrc": b"synthetic-netrc-only",
    }
    assert report["files"] == 3 and report["key_in_archive"] is False
    assert report["authentication_roundtrip_passed"] and not report["plaintext_on_network_volume"]
    assert raw not in Path(report["path"]).read_bytes()
    assert key.read_bytes().decode() not in Path(report["path"]).with_suffix(".public.json").read_text()


def test_key_hardlink_is_excluded_by_identity_not_filename(backup):
    module, private, key, _ = backup
    (private / "alias-key").hardlink_to(key)
    report = module.backup()
    assert unpack(module, report, key.read_bytes()) == {}
    assert report["files"] == 0


def test_nonce_changes_and_wrong_aad_or_tamper_cannot_decrypt(backup, monkeypatch):
    module, private, key, _ = backup
    (private / "raw").write_text("synthetic")
    times = iter([100, 101])
    monkeypatch.setattr(module.time, "time_ns", lambda: next(times))
    first, second = module.backup(), module.backup()
    a, b = Path(first["path"]).read_bytes(), Path(second["path"]).read_bytes()
    assert a[:12] != b[:12] and first["path"] != second["path"]
    assert unpack(module, first, key.read_bytes()) == unpack(module, second, key.read_bytes())
    with pytest.raises(InvalidTag):
        module.AESGCM(key.read_bytes()).decrypt(a[:12], a[12:], b"foreign-pod")
    changed = a[12:-1] + bytes([a[-1] ^ 1])
    with pytest.raises(InvalidTag):
        module.AESGCM(key.read_bytes()).decrypt(a[:12], changed, module.AAD)


@pytest.mark.parametrize("existing", ["ciphertext", "public-report"])
def test_no_existing_output_is_overwritten(backup, monkeypatch, existing):
    module, _, _, _ = backup
    module.DESTINATION.mkdir()
    monkeypatch.setattr(module.time, "time_ns", lambda: 123)
    target = module.DESTINATION / ("private-123.aesgcm" if existing == "ciphertext" else "private-123.public.json")
    target.write_bytes(b"already-owned-output")
    with pytest.raises(FileExistsError):
        module.backup()
    assert target.read_bytes() == b"already-owned-output"


@pytest.mark.parametrize("fault", ["pod", "root-mode", "root-symlink", "key-mode", "key-symlink", "netrc-symlink"])
def test_private_boundaries(backup, monkeypatch, tmp_path, fault):
    module, private, key, netrc = backup
    if fault == "pod":
        monkeypatch.setenv("RUNPOD_POD_ID", "unrelated-pod")
    elif fault == "root-mode":
        private.chmod(0o755)
    elif fault == "root-symlink":
        link = tmp_path / "root-link"
        link.symlink_to(private, target_is_directory=True)
        monkeypatch.setattr(module, "PRIVATE", link)
    elif fault == "key-mode":
        key.chmod(0o644)
    elif fault == "key-symlink":
        target = tmp_path / "other-key"
        key.rename(target)
        key.symlink_to(target)
    elif fault == "netrc-symlink":
        target = tmp_path / "not-a-real-netrc"
        target.write_text("do not follow")
        netrc.symlink_to(target)
        report = module.backup()
        assert unpack(module, report, key.read_bytes()) == {}
        return
    with pytest.raises((ValueError, OSError)):
        module.backup()
    assert not module.DESTINATION.exists()


@pytest.mark.parametrize("size", [0, 31, 33])
def test_invalid_key_length_is_rejected(backup, size):
    module, _, key, _ = backup
    key.write_bytes(b"X" * size)
    with pytest.raises(ValueError, match="256-bit"):
        module.backup()


@pytest.mark.parametrize("interval", [-1, 1, 59])
def test_cli_rejects_tight_loop_before_reading_private_data(backup, monkeypatch, interval):
    module, _, _, _ = backup
    operation = Mock()
    monkeypatch.setattr(module, "backup", operation)
    monkeypatch.setattr(sys, "argv", ["backup", "--interval-seconds", str(interval)])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    operation.assert_not_called()


def test_cli_once_and_minimum_repetition(backup, monkeypatch):
    module, _, _, _ = backup
    operation = Mock(return_value={"synthetic": True})
    sleep = Mock()
    monkeypatch.setattr(module, "backup", operation)
    monkeypatch.setattr(module.time, "sleep", sleep)
    monkeypatch.setattr(sys, "argv", ["backup"])
    module.main()
    operation.assert_called_once_with()
    sleep.assert_not_called()
    operation.reset_mock()
    operation.side_effect = [{"synthetic": True}, KeyboardInterrupt]
    monkeypatch.setattr(sys, "argv", ["backup", "--interval-seconds", "60"])
    with pytest.raises(KeyboardInterrupt):
        module.main()
    sleep.assert_called_once_with(60)
