import json
from pathlib import Path

import pytest

from examples.dsh.verifier import _sha256_bytes as sha
from examples.harbor.prepare_evolution_task import RUNTIME_SHA, prepare
from tests.uni_agent.examples.test_prepare_redact_curriculum import inputs as source_inputs

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inputs(tmp_path):
    source = source_inputs.__wrapped__(tmp_path)
    import pyarrow as pa
    import pyarrow.parquet as pq

    manifest_path = source["source_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["task"]["environment_digest"] = RUNTIME_SHA
    for split in ("train", "holdout"):
        path = source["source_dir"] / (split + ".parquet")
        rows = pq.read_table(path).to_pylist()
        for row in rows:
            row["extra_info"]["tools_kwargs"]["task"]["metadata"]["environment_digest"] = RUNTIME_SHA
        pq.write_table(pa.Table.from_pylist(rows), path)
        manifest["files"][path.name]["sha256"] = sha(path.read_bytes())
    manifest_path.write_text(json.dumps(manifest))
    source["source_manifest_sha256"] = sha(manifest_path.read_bytes())
    return dict(
        root=ROOT,
        source_dir=source["source_dir"],
        source_manifest_sha256=source["source_manifest_sha256"],
        output=tmp_path / "task-package",
        agent_image_digest=sha(b"new-image"),
    )


def test_single_public_task_contract_and_path_only_instruction(inputs):
    result = prepare(**inputs)
    task = inputs["output"] / "task"
    marker = json.loads((task / "evolution.json").read_bytes())
    assert set(marker) == {"kind", "fixture_sha256", "metadata_sha256", "source_sha256s"}
    assert marker["kind"] == "evolution-v2-lifecycle-v1"
    assert result["scenario_id"] == "redact-train-01"
    assert result["hidden_inputs_verified"] is False
    assert result["evolution_binding"]["task_ref"] == result["task_ref"]
    assert result["evolution_binding"]["metadata_sha256"] == marker["metadata_sha256"]
    assert "COPY fixture.json /app/fixture.json" in (task / "environment/Dockerfile").read_text()
    assert "network_mode: none" in (task / "tests/docker-compose.yaml").read_text()
    assert "pip install" not in (task / "tests/Dockerfile").read_text()
    assert "/app/fixture.json" in (task / "instruction.md").read_text()
    hashes = {
        p.relative_to(task).as_posix(): sha(p.read_bytes()).removeprefix("sha256:")
        for p in task.rglob("*")
        if p.is_file()
    }
    assert result["task_ref"]["sha256"] == sha(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(ValueError):
        prepare(**inputs)


@pytest.mark.parametrize("bad", ["manifest", "parquet", "digest"])
def test_rejects_invalid_sources_before_output(inputs, bad):
    if bad == "manifest":
        inputs["source_manifest_sha256"] = sha(b"wrong")
    if bad == "parquet":
        (inputs["source_dir"] / "holdout.parquet").write_bytes(b"changed")
    if bad == "digest":
        inputs["agent_image_digest"] = "latest"
    with pytest.raises(ValueError):
        prepare(**inputs)
    assert not inputs["output"].exists()


def test_immutable_payload_and_explicit_deployment_mapping(inputs):
    from examples.harbor.prepare_evolution_task import PARENT_IMAGE, RUNTIME_SHA, VERIFIER_SOURCES
    from uni_agent.tasks.harbor_dsh.evolution_scoring import EvolutionBinding, load_evolution_binding
    from uni_agent.tasks.harbor_dsh.protocol import TaskRef

    result = prepare(**inputs)
    task = inputs["output"] / "task"
    original = result["original_row"]["prompt"][0]["content"]
    fixture = str(ROOT / "examples/dsh/fixtures/evolution-v2/redact-train-01.json")
    assert (task / "instruction.md").read_text() == original.replace(fixture, "/app/fixture.json")
    assert set(result["deployment_metadata_changes"]) == {"fixture_path", "patches_sha256"}
    assert json.loads((task / "tests/metadata.json").read_bytes())["environment_digest"] == RUNTIME_SHA
    assert (task / "tests/fixture.json").read_bytes() == (task / "environment/fixture.json").read_bytes()
    assert inputs["output"].stat().st_mode & 0o777 == 0o700
    for path in task.rglob("*"):
        if path.is_file():
            assert path.stat().st_mode & 0o777 == 0o600
    for source in VERIFIER_SOURCES:
        assert (task / "tests/src" / source).read_bytes() == (ROOT / source).read_bytes()
    for dockerfile in ["environment/Dockerfile", "tests/Dockerfile"]:
        assert PARENT_IMAGE in (task / dockerfile).read_text()
    binding = EvolutionBinding.model_validate(result["evolution_binding"])
    loaded = load_evolution_binding(binding, TaskRef.model_validate(result["task_ref"]), repository_root=ROOT)
    assert loaded.metadata_sha256 == binding.metadata_sha256


@pytest.mark.parametrize(
    "source_name",
    [
        "examples/dsh/evolution.patch.yml",
        "examples/dsh/fixtures/evolution-v2/redact-train-01.json",
        "examples/dsh/evolution_verifier.py",
    ],
)
def test_actual_source_byte_mismatch_rejected(inputs, monkeypatch, source_name):
    from examples.harbor import prepare_evolution_task as module

    original = module._read

    def read(root, path):
        return b"wrong bytes" if str(path) == source_name else original(root, path)

    monkeypatch.setattr(module, "_read", read)
    with pytest.raises(ValueError):
        prepare(**inputs)
    assert not inputs["output"].exists()


def test_packaged_import_closure_is_self_contained(inputs):
    import os
    import subprocess
    import sys

    prepare(**inputs)
    source = inputs["output"] / "task/tests/src"
    env = {**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", "import examples.harbor.evolution_verifier"],
        cwd=inputs["output"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
