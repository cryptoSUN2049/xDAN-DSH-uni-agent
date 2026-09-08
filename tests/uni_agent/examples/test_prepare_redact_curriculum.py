import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from examples.dsh.prepare_evolution_dataset import build_evolution_rows
from examples.dsh.prepare_redact_curriculum import prepare

ROOT = Path(__file__).resolve().parents[3]


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"fixed-test-runtime")
    verifier = sha((ROOT / "examples/dsh/evolution_verifier.py").read_bytes())
    task = dict(
        environment_digest=sha(runtime.read_bytes()),
        verifier_id="dsh-harness-evolution-verifier",
        verifier_version="1",
        verifier_code_digest=verifier,
        profile="sdk-minimal",
        patches=["examples/dsh/evolution.patch.yml"],
    )
    rows = build_evolution_rows(ROOT / "examples/dsh/evolution_scenarios_v2.jsonl", fixture_root=ROOT, **task)
    files, fixtures = {}, {}
    for split, group in rows.items():
        path = source / (split + ".parquet")
        pq.write_table(pa.Table.from_pylist(group), path)
        files[path.name] = dict(records=len(group), sha256=sha(path.read_bytes()))
        for row in group:
            m = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            fixtures[m["scenario_id"]] = dict(path=m["fixture_path"], sha256=m["fixture_digest"])
    task["task_name"] = "dsh_architecture"
    manifest = dict(
        schema="dsh.evolution-dataset-manifest.v1",
        files=files,
        fixtures=fixtures,
        task=task,
        counts={"train": 16, "holdout": 8},
    )
    (source / "manifest.json").write_text(json.dumps(manifest))
    return dict(
        repository_root=ROOT,
        source_dir=source,
        source_manifest_sha256=sha((source / "manifest.json").read_bytes()),
        runtime_executable=runtime,
        output_dir=tmp_path / "selected",
    )


def test_selects_original_redact_rows_and_public_holdout(inputs):
    result = prepare(**inputs)
    for split, count in [("train", 4), ("holdout", 2)]:
        original = pq.read_table(inputs["source_dir"] / (split + ".parquet")).to_pylist()
        chosen = pq.read_table(inputs["output_dir"] / (split + ".parquet")).to_pylist()
        assert chosen == [
            r for r in original if r["extra_info"]["tools_kwargs"]["task"]["metadata"]["operation"] == "redact_email"
        ]
        assert len(chosen) == count
    assert result["hidden_inputs_verified"] is False
    with pytest.raises(FileExistsError):
        prepare(**inputs)


@pytest.mark.parametrize("bad", ["manifest", "parquet", "runtime", "fixture"])
def test_bad_source_rejected_before_output(inputs, bad):
    if bad == "manifest":
        inputs["source_manifest_sha256"] = "sha256:" + "0" * 64
    if bad == "parquet":
        (inputs["source_dir"] / "train.parquet").write_bytes(b"tampered")
    if bad == "runtime":
        inputs["runtime_executable"].write_bytes(b"changed")
    if bad == "fixture":
        path = inputs["source_dir"] / "manifest.json"
        m = json.loads(path.read_text())
        m["fixtures"]["redact-train-01"]["sha256"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(m))
        inputs["source_manifest_sha256"] = sha(path.read_bytes())
    with pytest.raises(ValueError):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()


@pytest.mark.parametrize("bad", ["metadata", "prompt", "count", "fixture_path"])
def test_bound_but_inconsistent_rows_rejected(inputs, bad):
    path = inputs["source_dir"] / "train.parquet"
    rows = pq.read_table(path).to_pylist()
    row = next(r for r in rows if r["extra_info"]["tools_kwargs"]["task"]["metadata"]["operation"] == "redact_email")
    metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
    if bad == "metadata":
        metadata["environment_digest"] = "sha256:" + "0" * 64
    elif bad == "prompt":
        row["prompt"] = [{"role": "user", "content": "a different fixture"}]
    elif bad == "fixture_path":
        metadata["fixture_path"] = "../escape.json"
    else:
        rows.remove(row)
    pq.write_table(pa.Table.from_pylist(rows), path)
    manifest_path = inputs["source_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["train.parquet"]["sha256"] = sha(path.read_bytes())
    manifest_path.write_text(json.dumps(manifest))
    inputs["source_manifest_sha256"] = sha(manifest_path.read_bytes())
    with pytest.raises(ValueError):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()


def test_output_is_private_and_provenance_rechecks(inputs):
    result = prepare(**inputs)
    output = inputs["output_dir"]
    assert output.stat().st_mode & 0o777 == 0o700
    for filename, info in result["files"].items():
        assert sha((output / filename).read_bytes()) == info["sha256"]
        assert (output / filename).stat().st_mode & 0o777 == 0o600
    assert (output / "manifest.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((output / "manifest.json").read_text()) == result
