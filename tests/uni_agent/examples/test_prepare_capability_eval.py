import hashlib
import json
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"fixed-runtime")
    runtime.chmod(0o700)

    def probe(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"path": str(runtime), "sdk": "0.1.3a2", "runtime": "0.1.3a2"}), ""
        )

    monkeypatch.setattr(subprocess, "run", probe)
    return dict(
        repository_root=ROOT,
        output_dir=tmp_path / "eval",
        eval_id="capability-001",
        runtime_executable=runtime,
        environment_digest="sha256:" + hashlib.sha256(runtime.read_bytes()).hexdigest(),
        runner_python=Path("/usr/bin/python3"),
    )


def test_prepares_eval_only_without_recipe_or_answers(inputs):
    from examples.dsh.prepare_capability_eval import prepare

    manifest = prepare(**inputs)
    root = inputs["output_dir"]
    rows = pq.read_table(root / "eval.parquet").to_pylist()
    assert len(rows) == 1
    prompt = rows[0]["prompt"][0]["content"]
    assert "Tool" in prompt
    assert not any(text in prompt for text in ["cordis_", "listTools", "platform=", "return {", "fixture"])
    assert manifest["status"] == "prepared"
    assert manifest["scope"] == "runtime-grounded Tool capability query; not open-ended autonomous discovery"
    env = manifest["environment"]
    assert env["VAL_ONLY"] == "True"
    assert env["TRAIN_FILE"] == env["TEST_FILE"]
    config = yaml.safe_load((root / "task.yaml").read_text())[0]
    assert config["environment_digest"] == inputs["environment_digest"]
    assert config["verifier_code_digest"] == manifest["verifier_bundle"]["sha256"]
    assert root.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir() if path.is_file())


def test_runtime_digest_mismatch_refused(inputs):
    from examples.dsh.prepare_capability_eval import prepare

    inputs["environment_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="runtime"):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()


def test_refuses_output_reuse(inputs):
    from examples.dsh.prepare_capability_eval import prepare

    prepare(**inputs)
    with pytest.raises(ValueError, match="new private"):
        prepare(**inputs)


def test_refuses_runtime_resolution_mismatch(inputs, monkeypatch):
    from examples.dsh.prepare_capability_eval import prepare

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 0, json.dumps(dict(path="/different/runtime", sdk="0.1.3a2", runtime="0.1.3a2")), ""
        ),
    )
    with pytest.raises(ValueError, match="different runtime"):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()


def test_private_mode_must_be_enforced(inputs, monkeypatch):
    from examples.dsh.prepare_capability_eval import prepare

    mkdir = Path.mkdir

    def ignored_mode(path, *args, **kwargs):
        mkdir(path, *args, **kwargs)
        if path == inputs["output_dir"]:
            path.chmod(0o777)

    monkeypatch.setattr(Path, "mkdir", ignored_mode)
    with pytest.raises(ValueError, match="private owner"):
        prepare(**inputs)
    assert list(inputs["output_dir"].iterdir()) == []
