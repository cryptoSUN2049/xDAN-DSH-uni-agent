import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from examples.harbor.prepare_evolution_task import prepare
from tests.uni_agent.examples.test_prepare_evolution_harbor_task import inputs as original_inputs
from tests.uni_agent.examples.test_prepare_evolution_harbor_task import sha
from uni_agent.tasks.harbor_dsh.evolution_scoring_v2 import (
    SOURCE_HASHES,
    VERIFIER_BUNDLE_SHA256,
    EvolutionV2Binding,
    load_evolution_v2_binding,
)
from uni_agent.tasks.harbor_dsh.protocol import TaskRef

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inputs(tmp_path):
    args = original_inputs.__wrapped__(tmp_path)
    path = args["source_dir"] / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest.update(
        schema="dsh.redact-curriculum.v2",
        counts={"train": 4, "holdout": 2},
        task_version="2",
        verifier_sources=SOURCE_HASHES,
    )
    manifest["task"].update(verifier_version="2", verifier_code_digest=VERIFIER_BUNDLE_SHA256)
    for split in ("train", "holdout"):
        parquet = args["source_dir"] / f"{split}.parquet"
        rows = [
            r
            for r in pq.read_table(parquet).to_pylist()
            if r["extra_info"]["tools_kwargs"]["task"]["metadata"]["operation"] == "redact_email"
        ]
        for row in rows:
            row["extra_info"]["tools_kwargs"]["task"]["metadata"].update(
                task_version="2", verifier_version="2", verifier_code_digest=VERIFIER_BUNDLE_SHA256
            )
        pq.write_table(pa.Table.from_pylist(rows), parquet)
        manifest["files"][parquet.name] = {"sha256": sha(parquet.read_bytes()), "records": len(rows)}
    path.write_text(json.dumps(manifest))
    args.update(source_manifest_sha256=sha(path.read_bytes()), admission_version="v2")
    return args


def test_v2_package_binds_original_bundle_and_path_only_prompt(inputs):
    report = prepare(**inputs)
    task = inputs["output"] / "task"
    marker = json.loads((task / "evolution.json").read_bytes())
    assert marker["kind"] == "evolution-v2-lifecycle-admission-v2"
    assert marker["verifier_bundle_sha256"] == VERIFIER_BUNDLE_SHA256
    assert len(marker["source_sha256s"]) == 3
    assert report["task_ref"]["version"] == "v2"
    assert "evolution_binding" not in report
    binding = EvolutionV2Binding.model_validate(report["evolution_v2_binding"])
    load_evolution_v2_binding(binding, TaskRef.model_validate(report["task_ref"]), repository_root=ROOT)
    assert set(report["deployment_metadata_changes"]) == {"fixture_path", "patches_sha256"}
    assert "examples.harbor.evolution_verifier_v2" in (task / "tests/test.sh").read_text()
    for name in SOURCE_HASHES:
        assert (task / "tests/src/examples/dsh" / name).read_bytes() == (ROOT / "examples/dsh" / name).read_bytes()


@pytest.mark.parametrize("bad", ["schema", "bundle", "source"])
def test_v2_rejects_wrong_source_identity_before_output(inputs, bad, monkeypatch):
    from examples.harbor import prepare_evolution_task as module

    manifest_path = inputs["source_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if bad == "schema":
        manifest["schema"] = "dsh.evolution-dataset-manifest.v1"
    elif bad == "bundle":
        manifest["task"]["verifier_code_digest"] = sha(b"wrong")
    else:
        original = module._read
        monkeypatch.setattr(
            module,
            "_read",
            lambda root, path: b"changed"
            if str(path) == "examples/dsh/evolution_verifier_v2.py"
            else original(root, path),
        )
    manifest_path.write_text(json.dumps(manifest))
    inputs["source_manifest_sha256"] = sha(manifest_path.read_bytes())
    with pytest.raises(ValueError):
        prepare(**inputs)
    assert not inputs["output"].exists()


def test_accepts_actual_native_v2_preparer_manifest(tmp_path, monkeypatch):
    from examples.dsh.prepare_redact_curriculum import prepare as select
    from examples.dsh.prepare_redact_curriculum_v2 import prepare as version
    from examples.harbor import prepare_evolution_task as module
    from tests.uni_agent.examples.test_prepare_redact_curriculum import inputs as native_inputs

    source = native_inputs.__wrapped__(tmp_path)
    select(**source)
    v2 = tmp_path / "native-v2"
    version(
        repository_root=ROOT,
        source_dir=source["output_dir"],
        source_manifest_sha256=sha((source["output_dir"] / "manifest.json").read_bytes()),
        runtime_executable=source["runtime_executable"],
        output_dir=v2,
    )
    monkeypatch.setattr(module, "RUNTIME_SHA", sha(source["runtime_executable"].read_bytes()))
    result = prepare(
        root=ROOT,
        source_dir=v2,
        source_manifest_sha256=sha((v2 / "manifest.json").read_bytes()),
        output=tmp_path / "actual-package",
        agent_image_digest=sha(b"image"),
        admission_version="v2",
    )
    assert result["task_ref"]["version"] == "v2"


def test_v2_packaged_import_closure(inputs):
    import os
    import subprocess
    import sys

    prepare(**inputs)
    result = subprocess.run(
        [sys.executable, "-c", "import examples.harbor.evolution_verifier_v2"],
        cwd=inputs["output"],
        env={**os.environ, "PYTHONPATH": str(inputs["output"] / "task/tests/src"), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
