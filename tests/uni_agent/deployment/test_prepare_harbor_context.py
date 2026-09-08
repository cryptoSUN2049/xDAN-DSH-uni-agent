import hashlib
import subprocess

import pytest

from deployment.bootstrap.prepare_harbor_context import SOURCE_MAP, prepare_context


def sha(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    files = {}
    for target, source in SOURCE_MAP.items():
        content = ("fixture " + source + "\n").encode()
        p = repo / source
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        files[target] = sha(content)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    cache = tmp_path / "cache"
    cache.mkdir()
    wheels = {
        "deepseek_harness_sdk-0.1.3a2-py3-none-any.whl": b"sdk",
        "deepseek_harness_runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64.whl": b"runtime",
    }
    for name, content in wheels.items():
        (cache / name).write_bytes(content)
        files["wheelhouse/" + name] = sha(content)
    sums = "".join(f"{sha(content)}  {name}\n" for name, content in sorted(wheels.items())).encode()
    files["wheelhouse/SHA256SUMS"] = sha(sums)
    files["source-revision"] = sha((commit + "\n").encode())
    manifest = {
        "schema": "dsh.harbor-execution-image-inputs.v1",
        "platform": "linux/amd64",
        "integration_revision": commit,
        "dsh_revision": "b" * 40,
        "python_distribution_version": "0.1.3a2",
        "files": files,
    }
    return {
        "repo": repo,
        "source_commit": commit,
        "manifest": manifest,
        "artifact_dir": cache,
        "output": tmp_path / "context",
    }


def test_context_exactly_matches_manifest_and_ignores_dirty_files(inputs):
    source = next(iter(SOURCE_MAP.values()))
    (inputs["repo"] / source).write_text("dirty working tree must not be copied")
    (inputs["artifact_dir"] / "unrelated-secret.txt").write_text("not copied")
    result = prepare_context(**inputs)
    actual = {
        p.relative_to(inputs["output"]).as_posix(): sha(p.read_bytes())
        for p in inputs["output"].rglob("*")
        if p.is_file()
    }
    assert actual == inputs["manifest"]["files"]
    assert result["source_commit"] == inputs["source_commit"]
    assert result["verified"] is True


@pytest.mark.parametrize(
    "fault", ["bad_wheel", "wrong_commit", "unsafe_path", "symlink_wheel", "existing_output", "wrong_sum_manifest"]
)
def test_bad_inputs_never_produce_verified_context(inputs, fault):
    wheel = next(inputs["artifact_dir"].glob("*.whl"))
    if fault == "bad_wheel":
        wheel.write_bytes(b"changed")
    elif fault == "wrong_commit":
        inputs["source_commit"] = "a" * 40
    elif fault == "unsafe_path":
        inputs["manifest"]["files"]["../../outside"] = "a" * 64
    elif fault == "symlink_wheel":
        alternate = wheel.with_suffix(".other")
        wheel.rename(alternate)
        wheel.symlink_to(alternate)
    elif fault == "existing_output":
        inputs["output"].mkdir()
    else:
        inputs["manifest"]["files"]["wheelhouse/SHA256SUMS"] = "a" * 64
    with pytest.raises((ValueError, FileExistsError)):
        prepare_context(**inputs)
    if fault != "existing_output":
        assert not inputs["output"].exists()
