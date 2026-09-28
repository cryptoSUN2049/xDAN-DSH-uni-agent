import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from deployment.harbor.mimo.prepare_context import SOURCE_PATHS, prepare_context
from deployment.harbor.mimo.publish_binding import DOCKER_DEFAULT_PATH, finalize_binding


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name in SOURCE_PATHS:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture " + name + "\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=t@example.invalid", "commit", "-qm", "init"],
        check=True,
    )
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    lock = json.loads(Path("deployment/harbor/mimo/dsh-release-lock.json").read_text())
    for name in lock["wheels"]:
        content = name.encode()
        (artifacts / name).write_bytes(content)
        lock["wheels"][name] = digest(content)
    archive = tmp_path / "python.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        content = b"fake standalone python executable"
        member = tarfile.TarInfo("python/bin/python3.12")
        member.size = len(content)
        member.mode = 0o755
        output.addfile(member, io.BytesIO(content))
    original = "docker.io/mimo/task@sha256:" + "a" * 64
    return dict(
        repo=repo,
        source_commit=revision,
        artifact_dir=artifacts,
        python_archive=archive,
        python_sha256=digest(archive.read_bytes()),
        original_image=original,
        base_inspect={
            "RepoDigests": [original],
            "Os": "linux",
            "Architecture": "amd64",
            "RootFS": {"Layers": ["sha256:" + "c" * 64]},
            "Config": {"User": "runner", "WorkingDir": "/testbed", "Env": ["PATH=/usr/bin"]},
        },
        gateway_origin="https://mimo.example.com",
        lock=lock,
        output=tmp_path / "context",
    )


def test_context_preserves_base_and_uses_exact_git_source(inputs):
    (inputs["repo"] / SOURCE_PATHS[0]).write_text("dirty files must not enter image")
    receipt = prepare_context(**inputs)
    assert receipt["status"] == "prepared_not_built"
    assert receipt["image_binding"] == {"original_image": inputs["original_image"], "dsh_image": None}
    assert receipt["runner_python"] == "/opt/dsh/bin/python"
    context = inputs["output"]
    assert (context / "source" / SOURCE_PATHS[0]).read_text().startswith("fixture ")
    dockerfile = (context / "Dockerfile").read_text()
    assert "FROM " + inputs["original_image"] in dockerfile
    assert "USER runner" in dockerfile
    assert "ENV " not in dockerfile
    assert "WORKDIR " not in dockerfile
    assert "apt-get" not in dockerfile
    assert "CMD " not in dockerfile
    for name, expected in receipt["files"].items():
        assert digest((context / name).read_bytes()) == expected


@pytest.mark.parametrize(
    "fault",
    [
        "tag",
        "image_id",
        "wrong_platform",
        "unbound_digest",
        "onbuild",
        "bad_wheel",
        "bad_python",
        "http",
        "path",
        "credentials",
    ],
)
def test_invalid_inputs_do_not_create_a_context(inputs, fault):
    if fault == "tag":
        inputs["original_image"] = "mimo/task:latest"
    elif fault == "image_id":
        inputs["original_image"] = "sha256:" + "a" * 64
    elif fault == "wrong_platform":
        inputs["base_inspect"]["Architecture"] = "arm64"
    elif fault == "unbound_digest":
        inputs["base_inspect"]["RepoDigests"] = []
    elif fault == "onbuild":
        inputs["base_inspect"]["Config"]["OnBuild"] = ["RUN change-dependencies"]
    elif fault == "bad_wheel":
        next(inputs["artifact_dir"].glob("*.whl")).write_bytes(b"changed")
    elif fault == "bad_python":
        inputs["python_sha256"] = "0" * 64
    elif fault == "http":
        inputs["gateway_origin"] = "http://mimo.example.com"
    elif fault == "path":
        inputs["gateway_origin"] += "/sessions/other/v1"
    else:
        inputs["gateway_origin"] = "https://secret@example.com"
    with pytest.raises(ValueError):
        prepare_context(**inputs)
    assert not inputs["output"].exists()


def test_archive_traversal_rejected_before_output(inputs):
    with tarfile.open(inputs["python_archive"], "w:gz") as archive:
        member = tarfile.TarInfo("python/../../outside")
        archive.addfile(member, io.BytesIO())
    inputs["python_sha256"] = digest(inputs["python_archive"].read_bytes())
    with pytest.raises(ValueError, match="archive"):
        prepare_context(**inputs)
    assert not inputs["output"].exists()


def publication_inputs(inputs):
    manifest = prepare_context(**inputs)
    ref = "ghcr.io/example/mimo-dsh@sha256:" + "d" * 64
    image = {**inputs["base_inspect"], "RepoDigests": [ref]}
    image["RootFS"] = {"Layers": [*image["RootFS"]["Layers"], "sha256:" + "e" * 64]}
    return dict(
        context=inputs["output"],
        derived_image=ref,
        derived_inspect=image,
        smoke={
            "schema": "dsh.mimo-image-smoke.v1",
            "status": "passed",
            "scope": "initialize-shutdown-only",
            "versions": {
                "deepseek-harness-sdk": "0.1.3a2",
                "deepseek-harness-runtime-bin": "0.1.3a2",
                "pydantic": "2.12.5",
            },
            "runtime_binary_sha256": inputs["lock"]["runtime_binary_sha256"],
            "runtime_rg_sha256": inputs["lock"]["runtime_rg_sha256"],
            "runner_sha256": manifest["files"]["source/uni_agent/agents/dsh/runner.py"],
        },
        output=inputs["output"].parent / "image-binding.json",
    )


def test_only_verified_published_image_is_bound(inputs):
    publication = publication_inputs(inputs)
    result = finalize_binding(**publication)
    assert result["original_image"] == inputs["original_image"]
    assert result["dsh_image"] == publication["derived_image"]
    assert result["gateway_route_verified"] is False
    assert json.loads(publication["output"].read_text()) == result


@pytest.mark.parametrize(
    "fault", [None, "nondefault_path", "extra_env", "missing_proof", "wrong_image", "different_runtime"]
)
def test_default_path_normalization_requires_exact_runtime_equivalence(inputs, fault):
    inputs["base_inspect"]["Config"].pop("Env")
    publication = publication_inputs(inputs)
    publication["derived_inspect"]["Config"] = {
        **publication["derived_inspect"]["Config"],
        "Env": ["PATH=" + DOCKER_DEFAULT_PATH],
    }
    proof = {
        "schema": "dsh.mimo-runtime-environment.v1",
        "original_image": inputs["original_image"],
        "dsh_image": publication["derived_image"],
        "original_path": DOCKER_DEFAULT_PATH,
        "derived_path": DOCKER_DEFAULT_PATH,
    }
    publication["runtime_environment"] = proof
    if fault == "nondefault_path":
        publication["derived_inspect"]["Config"]["Env"] = ["PATH=/opt/dsh/bin:/usr/bin"]
    elif fault == "extra_env":
        publication["derived_inspect"]["Config"]["Env"].append("PYTHONPATH=/opt/dsh")
    elif fault == "missing_proof":
        publication["runtime_environment"] = None
    elif fault == "wrong_image":
        proof["dsh_image"] = "ghcr.io/example/other@sha256:" + "a" * 64
    elif fault == "different_runtime":
        proof["original_path"] = "/usr/bin"
    if fault:
        with pytest.raises(ValueError, match="Env"):
            finalize_binding(**publication)
        assert not publication["output"].exists()
    else:
        result = finalize_binding(**publication)
        assert result["config_normalizations"][0]["kind"] == "docker_default_path_materialized"


@pytest.mark.parametrize(
    "fault", ["unpublished", "wrong_parent", "env_change", "runtime_change", "source_change", "no_boot"]
)
def test_bad_publication_never_emits_image_binding(inputs, fault):
    publication = publication_inputs(inputs)
    if fault == "unpublished":
        publication["derived_inspect"]["RepoDigests"] = []
    elif fault == "wrong_parent":
        publication["derived_inspect"]["RootFS"]["Layers"][0] = "sha256:" + "f" * 64
    elif fault == "env_change":
        publication["derived_inspect"]["Config"]["Env"] = ["PATH=/opt/dsh/bin:/usr/bin"]
    elif fault == "runtime_change":
        publication["smoke"]["runtime_binary_sha256"] = "0" * 64
    elif fault == "source_change":
        (inputs["output"] / "source/uni_agent/agents/dsh/runner.py").write_text("changed")
    else:
        publication["smoke"]["status"] = "not_run"
    with pytest.raises(ValueError):
        finalize_binding(**publication)
    assert not publication["output"].exists()
