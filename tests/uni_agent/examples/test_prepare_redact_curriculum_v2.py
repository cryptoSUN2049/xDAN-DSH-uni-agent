import pyarrow.parquet as pq
import pytest

from examples.dsh.prepare_redact_curriculum import prepare as prepare_v1
from examples.dsh.prepare_redact_curriculum_v2 import prepare
from tests.uni_agent.examples.test_prepare_redact_curriculum import inputs as source_inputs
from tests.uni_agent.examples.test_prepare_redact_curriculum import sha


@pytest.fixture
def inputs(tmp_path):
    return source_inputs.__wrapped__(tmp_path)


def test_new_release_preserves_prompts_and_changes_only_identity(inputs, tmp_path):
    prepare_v1(**inputs)
    original = inputs["output_dir"]
    output = tmp_path / "v2"
    report = prepare(
        repository_root=inputs["repository_root"],
        source_dir=original,
        source_manifest_sha256=sha((original / "manifest.json").read_bytes()),
        runtime_executable=inputs["runtime_executable"],
        output_dir=output,
    )
    for split in ("train", "holdout"):
        before = pq.read_table(original / f"{split}.parquet").to_pylist()
        after = pq.read_table(output / f"{split}.parquet").to_pylist()
        for old, new in zip(before, after, strict=True):
            assert old["prompt"] == new["prompt"]
            m = new["extra_info"]["tools_kwargs"]["task"]["metadata"]
            assert m["task_version"] == m["verifier_version"] == "2"
            m.update(
                {
                    k: old["extra_info"]["tools_kwargs"]["task"]["metadata"][k]
                    for k in ["task_version", "verifier_version", "verifier_code_digest"]
                }
            )
            assert old == new
    assert report["public_holdout"] and not report["hidden_inputs_verified"]
    assert len(report["verifier_sources"]) == 3
    assert "evolution_verifier_v2" in (output / "task-config.yaml").read_text()
    with pytest.raises(FileExistsError):
        prepare(
            repository_root=inputs["repository_root"],
            source_dir=original,
            source_manifest_sha256=sha((original / "manifest.json").read_bytes()),
            runtime_executable=inputs["runtime_executable"],
            output_dir=output,
        )


def test_source_tamper_rejected(inputs, tmp_path):
    prepare_v1(**inputs)
    source = inputs["output_dir"]
    digest = sha((source / "manifest.json").read_bytes())
    (source / "train.parquet").write_bytes(b"bad")
    with pytest.raises(ValueError, match="SHA"):
        prepare(
            repository_root=inputs["repository_root"],
            source_dir=source,
            source_manifest_sha256=digest,
            runtime_executable=inputs["runtime_executable"],
            output_dir=tmp_path / "v2",
        )
