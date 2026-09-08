import hashlib
import json
import os

import pytest

from uni_agent.tasks.dsh.memory_artifacts import freeze_memory_artifact, load_memory_artifact


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.fixture
def args(tmp_path):
    root = tmp_path / "writer"
    root.mkdir()
    (root / "memory.json").write_bytes(b'{"constraint":"retain evidence"}')
    return dict(
        source_root=root,
        relative_path="memory.json",
        expected_source_sha256=sha((root / "memory.json").read_bytes()),
        source_version="task-v1",
        chain_id="chain-1",
        writer_session_id="session-A",
        max_bytes=1024,
        output_dir=tmp_path / "frozen",
    )


def read_args(args, frozen):
    return dict(
        directory=args["output_dir"],
        expected_manifest_sha256=frozen.manifest_sha256,
        chain_id="chain-1",
        writer_session_id="session-A",
        source_version="task-v1",
        reader_session_id="session-B",
        max_bytes=1024,
    )


def test_freeze_load_independent_reader_and_exact_bytes(args):
    frozen = freeze_memory_artifact(**args)
    result = load_memory_artifact(**read_args(args, frozen))
    assert result.content == (args["source_root"] / "memory.json").read_bytes()
    assert result.reader_session_id == "session-B"
    assert result.content_sha256 == args["expected_source_sha256"]
    assert args["output_dir"].stat().st_mode & 0o777 == 0o700
    for p in args["output_dir"].iterdir():
        assert p.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        freeze_memory_artifact(**args)


@pytest.mark.parametrize(
    "bad", ["traversal", "absolute", "symlink", "hardlink", "fifo", "oversize", "digest", "parent_link"]
)
def test_freeze_rejects_untrusted_source_without_publishing(args, bad):
    source = args["source_root"] / "memory.json"
    if bad == "traversal":
        args["relative_path"] = "../writer/memory.json"
    elif bad == "absolute":
        args["relative_path"] = str(source)
    elif bad == "symlink":
        source.rename(source.with_suffix(".real"))
        source.symlink_to(source.with_suffix(".real"))
    elif bad == "hardlink":
        os.link(source, source.with_suffix(".link"))
    elif bad == "fifo":
        source.unlink()
        os.mkfifo(source)
    elif bad == "oversize":
        args["max_bytes"] = 1
    elif bad == "digest":
        args["expected_source_sha256"] = sha(b"wrong")
    else:
        linked = args["source_root"].parent / "linked"
        linked.symlink_to(args["source_root"], target_is_directory=True)
        args["source_root"] = linked
    with pytest.raises((ValueError, OSError)):
        freeze_memory_artifact(**args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize(
    "bad", ["chain_id", "writer_session_id", "source_version", "reader", "manifest", "content", "budget"]
)
def test_load_requires_external_identity_and_content_binding(args, bad):
    frozen = freeze_memory_artifact(**args)
    values = read_args(args, frozen)
    if bad in ["chain_id", "writer_session_id", "source_version"]:
        values[bad] = "wrong"
    elif bad == "reader":
        values["reader_session_id"] = "session-A"
    elif bad == "budget":
        values["max_bytes"] = 1
    elif bad == "manifest":
        p = args["output_dir"] / "manifest.json"
        data = json.loads(p.read_bytes())
        data["chain_id"] = "wrong"
        p.write_text(json.dumps(data))
    else:
        (args["output_dir"] / "memory.bin").write_bytes(b"changed")
    with pytest.raises(ValueError):
        load_memory_artifact(**values)


def test_source_change_during_read_is_rejected(args, monkeypatch):
    from uni_agent.tasks.dsh import memory_artifacts as module

    source = args["source_root"] / "memory.json"
    inode = source.stat().st_ino
    original = module.os.fstat
    reads = 0

    def changed(fd):
        nonlocal reads
        info = original(fd)
        if info.st_ino == inode:
            reads += 1
            if reads == 2:
                source.write_bytes(b"changed concurrently")
                return original(fd)
        return info

    monkeypatch.setattr(module.os, "fstat", changed)
    with pytest.raises(ValueError, match="changed during"):
        freeze_memory_artifact(**args)
    assert not args["output_dir"].exists()


@pytest.mark.parametrize("bad", ["source_parent_link", "target_parent_link", "target_link", "target_exists"])
def test_nested_paths_and_target_identity_never_follow_links(args, bad):
    if bad == "source_parent_link":
        (args["source_root"] / "sub").symlink_to(args["source_root"], target_is_directory=True)
        args["relative_path"] = "sub/memory.json"
    elif bad == "target_parent_link":
        alias = args["output_dir"].parent / "alias"
        alias.symlink_to(args["output_dir"].parent, target_is_directory=True)
        args["output_dir"] = alias / "frozen"
    elif bad == "target_link":
        args["output_dir"].symlink_to(args["source_root"], target_is_directory=True)
    else:
        args["output_dir"].mkdir()
    with pytest.raises((ValueError, OSError)):
        freeze_memory_artifact(**args)
    assert not (args["source_root"] / "manifest.json").exists()


@pytest.mark.parametrize("bad", ["symlink", "hardlink", "directory", "public_file", "public_directory"])
def test_frozen_reader_rejects_unsafe_files(args, bad):
    frozen = freeze_memory_artifact(**args)
    path = args["output_dir"] / "memory.bin"
    if bad == "symlink":
        path.unlink()
        path.symlink_to(args["source_root"] / "memory.json")
    elif bad == "hardlink":
        os.link(path, args["output_dir"] / "alias.bin")
    elif bad == "directory":
        path.unlink()
        path.mkdir()
    elif bad == "public_file":
        path.chmod(0o644)
    else:
        args["output_dir"].chmod(0o755)
    with pytest.raises((ValueError, OSError)):
        load_memory_artifact(**read_args(args, frozen))


@pytest.mark.parametrize("bad", ["duplicate", "extra", "size_bool", "source_escape", "nan"])
def test_even_externally_hashed_manifest_must_follow_contract(args, bad):
    frozen = freeze_memory_artifact(**args)
    path = args["output_dir"] / "manifest.json"
    data = json.loads(path.read_bytes())
    if bad == "duplicate":
        raw = ('{"chain_id":"chain-1",' + path.read_text()[1:]).encode()
    elif bad == "nan":
        data["size_bytes"] = float("nan")
        raw = json.dumps(data).encode()
    else:
        if bad == "extra":
            data["reader_path"] = "/secret"
        elif bad == "size_bool":
            data["size_bytes"] = True
        else:
            data["source_path"] = "../other.json"
        raw = json.dumps(data).encode()
    path.write_bytes(raw)
    values = read_args(args, frozen)
    values["expected_manifest_sha256"] = sha(raw)
    with pytest.raises(ValueError):
        load_memory_artifact(**values)


@pytest.mark.parametrize(
    "field,value",
    [("chain_id", ""), ("writer_session_id", "../A"), ("source_version", ""), ("max_bytes", True), ("max_bytes", 0)],
)
def test_invalid_operator_contract_fails_before_publication(args, field, value):
    args[field] = value
    with pytest.raises(ValueError):
        freeze_memory_artifact(**args)
    assert not args["output_dir"].exists()


def test_nested_whitelist_and_detached_snapshot(args):
    source = args["source_root"] / "memory.json"
    nested = args["source_root"] / "notes"
    nested.mkdir()
    source.rename(nested / "handoff.json")
    args["relative_path"] = "notes/handoff.json"
    frozen = freeze_memory_artifact(**args)
    (nested / "handoff.json").write_bytes(b"writer changed after freezing")
    result = load_memory_artifact(**read_args(args, frozen))
    assert result.content == b'{"constraint":"retain evidence"}'
