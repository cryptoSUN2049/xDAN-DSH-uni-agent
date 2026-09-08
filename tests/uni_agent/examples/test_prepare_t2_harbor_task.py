"""Harbor packaging contracts: same public task, frozen inputs, no training dependencies."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

from examples.dsh.capability_tasks.log_tool.task_bundle import build_rows

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "sha256:" + "a" * 64
pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def prepare(tmp_path):
    from examples.harbor.prepare_t2_task import prepare

    output = tmp_path / "release"
    manifest = prepare(root=ROOT, output=output, agent_image_digest=IMAGE)
    return output, manifest


def test_same_prompt_fixture_and_frozen_patch(tmp_path):
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH, T2_PATCH_SHA256

    output, manifest = prepare(tmp_path)
    task = output / "task"
    rows, _ = build_rows(ROOT, environment_digest=IMAGE, patches=[str(ROOT / "examples/dsh/evolution.patch.yml")])
    row = next(row for row in rows if row["uid"] == "log-tool-dev-01")
    assert (task / "instruction.md").read_text() == row["prompt"][0]["content"]
    assert (task / "tests/fixture.json").read_bytes() == (
        ROOT / "examples/dsh/capability_tasks/log_tool/fixtures/dev-01.json"
    ).read_bytes()
    assert sha((task / "environment/evolution.patch.yml").read_bytes()) == T2_PATCH_SHA256
    assert T2_PATCH_PATH in (task / "environment/Dockerfile").read_text()
    assert manifest["case_id"] == "log-tool-dev-01"
    assert manifest["evaluation_visibility"] == "public-development-not-hidden"


def test_task_has_separate_networkless_verifier_and_no_agent_file_artifacts(tmp_path):
    output, _ = prepare(tmp_path)
    task = output / "task"
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["artifacts"] == []
    assert config["environment"]["docker_image"] == IMAGE
    assert config["verifier"]["environment_mode"] == "separate"
    assert "platform: linux/amd64" in (task / "environment/docker-compose.yaml").read_text()
    assert "network_mode: bridge" in (task / "environment/docker-compose.yaml").read_text()
    compose = (task / "tests/docker-compose.yaml").read_text()
    assert "platform: linux/amd64" in compose and "network_mode: none" in compose
    dockerfile = (task / "tests/Dockerfile").read_text()
    assert "python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea" in dockerfile
    assert "--platform=linux/amd64" in dockerfile
    assert "pip install" not in dockerfile
    assert "--fixture /tests/fixture.json" in (task / "tests/test.sh").read_text()
    assert sorted(p.name for p in (task / "environment").iterdir()) == [
        "Dockerfile",
        "docker-compose.yaml",
        "evolution.patch.yml",
    ]


def test_manifest_binds_all_files_and_operator_fixture_without_self_reference(tmp_path):
    output, manifest = prepare(tmp_path)
    assert json.loads((output / "manifest.json").read_text()) == manifest
    files = {
        p.relative_to(output / "task").as_posix(): p.read_bytes() for p in (output / "task").rglob("*") if p.is_file()
    }
    expected = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    task_digest = sha(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode())
    assert manifest["task_ref"] == {"id": "t2-log-tool-dev-01", "version": "v1", "sha256": task_digest}
    assert manifest["files"] == {"task/" + name: sha(raw) for name, raw in files.items()}
    assert manifest["t2_fixture"] == {
        "task_ref": manifest["task_ref"],
        "fixture_path": str(output / "task/tests/fixture.json"),
        "fixture_sha256": sha(files["tests/fixture.json"]),
    }
    assert len(manifest["source_commit"]) == 40
    assert (
        manifest["agent_parent_image_digest"]
        == "sha256:846b46c90ebd71b3ababbd4a1cb50459a99d6fde97d42f6503e84a78ce60fc97"
    )
    assert manifest["runtime"]["python_distribution_version"] == "0.1.3a2"
    assert all(not p.is_symlink() for p in output.rglob("*"))


def test_bundled_verifier_runs_with_only_standard_library(tmp_path):
    output, _ = prepare(tmp_path)
    source = output / "task/tests/src"
    result = subprocess.run(
        [sys.executable, "-S", "-B", "-m", "examples.harbor.t2_verifier", "--help"],
        cwd=source,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--fixture" in result.stdout and "--input-dir" in result.stdout
    assert not list(source.rglob("__pycache__"))
    assert not (source / "deployment/checks/dsh_log_tool_smoke.py").exists()


@pytest.mark.parametrize("image", ["latest", "repo:latest", "sha256:bad", IMAGE + "\nRUN bad"])
def test_rejects_unfixed_agent_image_before_writing(tmp_path, image):
    from examples.harbor.prepare_t2_task import prepare

    output = tmp_path / "release"
    with pytest.raises((ValueError, RuntimeError), match="digest"):
        prepare(root=ROOT, output=output, agent_image_digest=image)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["directory", "file", "dangling-symlink"])
def test_refuses_existing_output_without_changing_it(tmp_path, kind):
    from examples.harbor.prepare_t2_task import prepare

    output = tmp_path / "release"
    if kind == "directory":
        output.mkdir()
        (output / "keep").write_text("owned")
    elif kind == "file":
        output.write_text("owned")
    else:
        output.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="new"):
        prepare(root=ROOT, output=output, agent_image_digest=IMAGE)
    assert output.is_symlink() if kind == "dangling-symlink" else output.exists()
    if kind == "directory":
        assert (output / "keep").read_text() == "owned"


@pytest.mark.parametrize("tamper", ["different-bytes", "symlink"])
def test_rejects_unreviewed_patch_before_writing(tmp_path, tamper):
    from examples.harbor.prepare_t2_task import prepare

    root = tmp_path / "root"
    patch = root / "examples/dsh/evolution.patch.yml"
    patch.parent.mkdir(parents=True)
    if tamper == "symlink":
        patch.symlink_to(ROOT / "examples/dsh/evolution.patch.yml")
    else:
        patch.write_text("changed patch")
    with pytest.raises((ValueError, RuntimeError), match="patch|regular|symlink"):
        prepare(root=root, output=tmp_path / "release", agent_image_digest=IMAGE)
    assert not (tmp_path / "release").exists()


def test_repeated_preparation_produces_identical_task_identity(tmp_path):
    from examples.harbor.prepare_t2_task import prepare

    a = prepare(root=ROOT, output=tmp_path / "a", agent_image_digest=IMAGE)
    b = prepare(root=ROOT, output=tmp_path / "b", agent_image_digest=IMAGE)
    assert a["task_ref"] == b["task_ref"]
    assert a["files"] == b["files"]


def test_rejects_different_source_checkout_instead_of_mislabeling_imported_builder(tmp_path):
    from examples.harbor.prepare_t2_task import prepare

    root = tmp_path / "different-checkout"
    patch = root / "examples/dsh/evolution.patch.yml"
    patch.parent.mkdir(parents=True)
    patch.write_bytes((ROOT / "examples/dsh/evolution.patch.yml").read_bytes())
    with pytest.raises(ValueError, match="root must match"):
        prepare(root=root, output=tmp_path / "release", agent_image_digest=IMAGE)
    assert not (tmp_path / "release").exists()
