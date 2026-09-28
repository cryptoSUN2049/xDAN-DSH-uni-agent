"""MiMo source identities and hidden-test packaging are preserved without GPU imports."""

import copy
import hashlib
import json
import sys

import pytest
import tomllib

from examples.mimo_dsh_rl.prepare_tasks import load_image_mapping, parse_instance, prepare_task

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
REVISION = "639865fd3374018d6cb29b9fb82dd531406fcf5f"
MAPPED = "docker.io/xiaomimimo/mimo-v2.6-rl-oss:code-1"
IMAGES = {
    "original_image": MAPPED.split(":")[0] + "@sha256:" + "a" * 64,
    "dsh_image": "ghcr.io/example/mimo-dsh@sha256:" + "b" * 64,
}
PATCH = (
    "diff --git a/check.sh b/check.sh\nnew file mode 100755\n--- /dev/null\n+++ b/check.sh\n@@ -0,0 +1 @@\n+exit 0\n"
)


def row():
    instance = {
        "dataset_type": "opensource-code",
        "docker_image": "code-1:latest",
        "cwd": "/workspace/repo",
        "instance_id": "code-1",
        "problem_statement": "Fix the bug.\nPreserve the public API.",
        "test_patch": PATCH,
        "test_command": "bash /workspace/repo/check.sh",
        "verifier_timeout_sec": 1800,
    }
    return {
        "data_source": "opensource-code",
        "prompt": [{"role": "user", "content": instance["problem_statement"]}],
        "extra_info": {"instance_id": "code-1", "instance_json": json.dumps(instance)},
    }


def prepare(tmp_path, **kwargs):
    return prepare_task(
        row(),
        output=tmp_path / "release",
        image_mapping={"code-1:latest": MAPPED},
        image_binding=IMAGES,
        source_revision=REVISION,
        **kwargs,
    )


@pytest.mark.parametrize("key", ["cwd", "test_patch", "test_command", "verifier_timeout_sec"])
def test_rejects_missing_required_fields(key):
    source = row()
    instance = json.loads(source["extra_info"]["instance_json"])
    del instance[key]
    source["extra_info"]["instance_json"] = json.dumps(instance)
    with pytest.raises(ValueError, match="fields"):
        parse_instance(source)


@pytest.mark.parametrize("cwd", ["repo", "/workspace/../repo", "/", "/logs/verifier"])
def test_rejects_unsafe_workspaces(cwd):
    source = row()
    instance = json.loads(source["extra_info"]["instance_json"])
    instance["cwd"] = cwd
    source["extra_info"]["instance_json"] = json.dumps(instance)
    with pytest.raises(ValueError, match="cwd"):
        parse_instance(source)


def test_image_mapping_does_not_guess_and_rejects_conflicts(tmp_path):
    source = tmp_path / "mapping.jsonl"
    source.write_text(json.dumps({"dataset_image": "code-1:latest", "dockerhub_image": MAPPED}) + "\n")
    assert load_image_mapping(source) == {"code-1:latest": MAPPED}
    source.write_text(
        source.read_text() + json.dumps({"dataset_image": "code-1:latest", "dockerhub_image": "other:tag"})
    )
    with pytest.raises(ValueError, match="conflict"):
        load_image_mapping(source)


def test_packages_original_cwd_and_hidden_patch_only_for_verifier(tmp_path):
    source = row()
    unchanged = copy.deepcopy(source)
    manifest = prepare(tmp_path)
    task = tmp_path / "release/task"
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["environment"]["workdir"] == "/workspace/repo"
    assert config["environment"]["docker_image"] == IMAGES["dsh_image"]
    assert config["verifier"]["environment_mode"] == "separate"
    assert config["verifier"]["environment"]["docker_image"] == IMAGES["original_image"]
    assert (task / "instruction.md").read_text() == source["prompt"][0]["content"]
    assert (task / "tests/test.patch").read_text() == PATCH
    assert not list(task.rglob("*compose*"))
    assert "test_patch" not in (task / "mimo-binding.json").read_text()
    assert "test.patch" not in (task / "environment/Dockerfile").read_text()
    assert manifest["source_revision"] == REVISION
    assert manifest["original_image"] == IMAGES["original_image"]
    assert manifest["source_row_hash"].startswith("sha256:")
    assert manifest["status"] == "prepared-only"
    assert source == unchanged


def test_all_task_bytes_bound_and_output_never_overwritten(tmp_path):
    manifest = prepare(tmp_path)
    task = tmp_path / "release/task"
    hashes = {
        str(path.relative_to(task)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in task.rglob("*")
        if path.is_file()
    }
    assert (
        manifest["task_ref"]["sha256"]
        == "sha256:" + hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    assert json.loads((tmp_path / "release/manifest.json").read_text()) == manifest
    with pytest.raises(ValueError, match="new"):
        prepare(tmp_path)


def test_missing_mapping_and_mutable_image_are_rejected_before_writes(tmp_path):
    for mapping, images in [
        ({}, IMAGES),
        ({"code-1:latest": MAPPED}, {**IMAGES, "dsh_image": "ghcr.io/example/dsh:latest"}),
    ]:
        with pytest.raises(ValueError):
            prepare_task(
                row(),
                output=tmp_path / "release",
                image_mapping=mapping,
                image_binding=images,
                source_revision=REVISION,
            )
        assert not (tmp_path / "release").exists()


def test_unpinned_revision_rejected(tmp_path):
    with pytest.raises(ValueError, match="revision"):
        prepare_task(
            row(),
            output=tmp_path / "release",
            image_mapping={"code-1:latest": MAPPED},
            image_binding=IMAGES,
            source_revision="main",
        )


def test_gateway_profile_allows_only_operator_origin(tmp_path):
    prepare(tmp_path, gateway_origin="https://gateway.example.invalid")
    task = tmp_path / "release/task"
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["environment"]["network_mode"] == "allowlist"
    assert config["environment"]["allowed_hosts"] == ["gateway.example.invalid"]
    assert config["verifier"]["environment"]["network_mode"] == "no-network"


def test_conflicting_authoritative_prompt_is_not_silently_rewritten(tmp_path):
    source = row()
    source["prompt"][0]["content"] = "Different task"
    with pytest.raises(ValueError, match="prompt"):
        prepare_task(
            source,
            output=tmp_path / "release",
            image_mapping={"code-1:latest": MAPPED},
            image_binding=IMAGES,
            source_revision=REVISION,
        )


def test_invalid_gateway_origin_does_not_write_release(tmp_path):
    with pytest.raises(ValueError, match="origin"):
        prepare(tmp_path, gateway_origin="https://user:password@gateway.example.invalid/path")
    assert not (tmp_path / "release").exists()


def test_prepare_cli_builds_declared_source_revision(tmp_path, monkeypatch, capsys):
    from examples.mimo_dsh_rl.prepare_tasks import main

    source = tmp_path / "row.json"
    source.write_text(json.dumps(row()))
    mapping = tmp_path / "mapping.jsonl"
    mapping.write_text(json.dumps({"dataset_image": "code-1:latest", "dockerhub_image": MAPPED}) + "\n")
    images = tmp_path / "images.json"
    images.write_text(json.dumps(IMAGES))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_tasks",
            "--row-json",
            str(source),
            "--image-mapping",
            str(mapping),
            "--image-binding",
            str(images),
            "--source-revision",
            REVISION,
            "--output",
            str(tmp_path / "release"),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["source_revision"] == REVISION


@pytest.mark.parametrize("value", [None, "not-json", "[]"])
def test_invalid_instance_json_reports_contract_error(value):
    source = row()
    source["extra_info"]["instance_json"] = value
    with pytest.raises(ValueError):
        parse_instance(source)


def test_traditional_unified_diff_is_preserved_byte_for_byte(tmp_path):
    source = row()
    instance = json.loads(source["extra_info"]["instance_json"])
    instance["test_patch"] = "--- /dev/null\n+++ b/check.sh\n@@ -0,0 +1 @@\n+exit 0\n"
    source["extra_info"]["instance_json"] = json.dumps(instance)
    prepare_task(
        source,
        output=tmp_path / "release",
        image_mapping={"code-1:latest": MAPPED},
        image_binding=IMAGES,
        source_revision=REVISION,
    )
    assert (tmp_path / "release/task/tests/test.patch").read_text() == instance["test_patch"]
