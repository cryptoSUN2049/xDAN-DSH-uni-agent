import base64
import json
import os
import subprocess

import pytest


def test_raw_files_missing_and_empty_roundtrip(tmp_path):
    from examples.dsh.capabilities.work_state.bundle import pack_bundle, unpack_bundle

    source = tmp_path / "source"
    source.mkdir()
    (source / "handoff.md").write_bytes(b"\xffnot JSON")
    allowed = ["index.json", "handoff.md", "notes/detail.txt"]
    raw = pack_bundle(source, allowed)
    assert raw == pack_bundle(source, list(reversed(allowed)))
    result = unpack_bundle(raw, tmp_path / "reader", allowed)
    assert result["missing"] == ["index.json", "notes/detail.txt"]
    assert (tmp_path / "reader/handoff.md").read_bytes() == b"\xffnot JSON"
    assert not (tmp_path / "reader/index.json").exists()
    empty = pack_bundle(source, ["absent"])
    assert unpack_bundle(empty, tmp_path / "empty", ["absent"])["files"] == {}


@pytest.mark.parametrize("allowed", [["../secret"], ["/absolute"], ["a", "a"], ["a", "a-b", "a/c"], ["a\\b"]])
def test_invalid_allowlist_rejected_before_writing(tmp_path, allowed):
    from examples.dsh.capabilities.work_state.bundle import pack_bundle

    with pytest.raises(ValueError):
        pack_bundle(tmp_path, allowed)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "parent_symlink", "root_symlink"])
def test_non_regular_or_linked_paths_rejected(tmp_path, kind):
    from examples.dsh.capabilities.work_state.bundle import pack_bundle

    source = tmp_path / "source"
    source.mkdir()
    secret = tmp_path / "secret"
    secret.write_bytes(b"secret")
    target, root, name = source / "item", source, "item"
    if kind == "symlink":
        target.symlink_to(secret)
    elif kind == "hardlink":
        os.link(secret, target)
    elif kind == "directory":
        target.mkdir()
    elif kind == "parent_symlink":
        target.symlink_to(tmp_path, target_is_directory=True)
        name = "item/secret"
    else:
        root = tmp_path / "alias"
        root.symlink_to(source, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        pack_bundle(root, [name])


def test_nested_roundtrip_budget_and_no_target_reuse(tmp_path):
    from examples.dsh.capabilities.work_state.bundle import pack_bundle, unpack_bundle

    source = tmp_path / "source"
    (source / "notes").mkdir(parents=True)
    (source / "notes/a").write_bytes(b"123")
    (source / "notes/b").write_bytes(b"456")
    with pytest.raises(ValueError):
        pack_bundle(source, ["notes/a"], max_bytes=2)
    with pytest.raises(ValueError):
        pack_bundle(source, ["notes/a", "notes/b"], max_bytes=5)
    bundle = pack_bundle(source, ["notes/a", "notes/b"], max_bytes=6)
    with pytest.raises(ValueError):
        unpack_bundle(bundle, tmp_path / "too-small", ["notes/a", "notes/b"], max_bytes=5)
    assert not (tmp_path / "too-small").exists()
    unpack_bundle(bundle, tmp_path / "out", ["notes/a", "notes/b"])
    assert (tmp_path / "out/notes/a").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        unpack_bundle(bundle, tmp_path / "out", ["notes/a", "notes/b"])


@pytest.mark.parametrize("change", ["sha", "size", "path", "duplicate", "base64", "missing_overlap"])
def test_tampered_inventory_refused_before_create(tmp_path, change):
    from examples.dsh.capabilities.work_state.bundle import pack_bundle, unpack_bundle

    (tmp_path / "a").write_bytes(b"data")
    obj = json.loads(pack_bundle(tmp_path, ["a"]))
    if change == "sha":
        obj["files"]["a"]["sha256"] = "sha256:" + "0" * 64
    elif change == "size":
        obj["files"]["a"]["size"] = True
    elif change == "path":
        obj["files"]["../a"] = obj["files"].pop("a")
    elif change == "base64":
        obj["files"]["a"]["base64"] = base64.b64encode(b"wrong").decode()
    elif change == "missing_overlap":
        obj["missing"] = ["a"]
    raw = json.dumps(obj).encode()
    if change == "duplicate":
        raw = raw.replace(b'"missing": []', b'"missing": [], "missing": []')
    with pytest.raises(ValueError):
        unpack_bundle(raw, tmp_path / "out", ["a"])
    assert not (tmp_path / "out").exists()


def test_profile_composes_actual_node_policy_with_missing_reader_entry(tmp_path):
    from examples.dsh.capabilities.work_state.profile import build_work_state_patch

    goal, index, result = tmp_path / "goal", tmp_path / "index", tmp_path / "result"
    goal.write_text("goal")
    patch = build_work_state_patch(
        role="reader",
        chain_id="c",
        session_id="b",
        source_version="v",
        read_files=[goal, index],
        write_files=[result],
        read_missing=[index],
    )
    plugin = patch[-1]["insert"][0]
    program = (
        "const p=JSON.parse(process.argv[1]);const m=await import(p.name);const permits=m.createPolicy(p.config);"
        "console.log(JSON.stringify([permits({name:'str_replace_editor',arguments:{command:'view',path:p.config.readMissing[0]}}),"
        "permits({name:'str_replace_editor',arguments:{command:'create',path:p.config.writeFiles[0]}}),"
        "permits({name:'str_replace_editor',arguments:{command:'create',path:p.config.readFiles[0]}})]));"
    )
    probe = subprocess.run(
        ["node", "--input-type=module", "-e", program, json.dumps(plugin)], check=True, text=True, capture_output=True
    )
    assert json.loads(probe.stdout) == [True, True, False]
    assert patch[:2] == [{"id": "persistent-bash", "disabled": True}, {"id": "persistent-pwsh", "disabled": True}]
