import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from examples.dsh.ops.prepare_native_rebuild import prepare, sha
from examples.dsh.prepare_redact_curriculum import prepare as select
from examples.dsh.prepare_redact_curriculum_v2 import prepare as version
from tests.uni_agent.examples.test_prepare_redact_curriculum import inputs as original_inputs

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    from examples.dsh.ops import prepare_native_rebuild as module

    source = original_inputs.__wrapped__(tmp_path)
    select(**source)
    data = tmp_path / "baseline-data"
    version(
        repository_root=ROOT,
        source_dir=source["output_dir"],
        source_manifest_sha256=sha((source["output_dir"] / "manifest.json").read_bytes()),
        runtime_executable=source["runtime_executable"],
        output_dir=data,
    )
    manifest = json.loads((data / "manifest.json").read_bytes())
    old = "/previous/checkout"
    for split in ("train", "holdout"):
        path = data / f"{split}.parquet"
        rows = pq.read_table(path).to_pylist()
        for row in rows:
            row["prompt"][0]["content"] = row["prompt"][0]["content"].replace(str(ROOT), old)
        pq.write_table(pa.Table.from_pylist(rows), path)
        manifest["files"][path.name]["sha256"] = sha(path.read_bytes())
    (data / "manifest.json").write_text(json.dumps(manifest))
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/python").symlink_to(sys.executable)
    runtime = venv / "runtime"
    runtime.write_bytes(source["runtime_executable"].read_bytes())
    monkeypatch.setattr(module, "RUNTIME_SHA256", sha(runtime.read_bytes()))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "curriculum_manifest_sha256": sha((data / "manifest.json").read_bytes()),
                "source_commit": "b" * 40,
                "command": ["bash", "examples/dsh/ops/launch_qwen3_4b_online_rl.sh", "--foreground"],
                "environment": dict(
                    DATA_ROOT=str(data),
                    TRAIN_FILE=str(data / "train.parquet"),
                    TEST_FILE=str(data / "holdout.parquet"),
                    TASK_CONFIG=str(data / "task-config.yaml"),
                    PYTHONPATH=old + ":" + old + "/verl",
                    MODEL_PATH="/workspace/models/Qwen3-4B-1cfa9a7",
                    MODEL_ID="Qwen/Qwen3-4B",
                    MODEL_LICENSE_APPROVED="1",
                    TOTAL_TRAINING_STEPS="2",
                    TRAIN_BATCH_SIZE="2",
                    ROLLOUT_N="4",
                    VAL_ROLLOUT_N="1",
                    TRAIN_MAX_SAMPLES="4",
                    VAL_MAX_SAMPLES="2",
                    MAX_PROMPT_LENGTH="8192",
                    MAX_RESPONSE_LENGTH="1024",
                    LORA_RANK="16",
                    LORA_ALPHA="16",
                    VAL_ONLY="False",
                    RESUME_MODE="disable",
                ),
            }
        )
    )
    return dict(
        repository_root=ROOT,
        expected_revision=module.revision(ROOT),
        venv=venv,
        runtime_executable=runtime,
        baseline_manifest=baseline,
        baseline_manifest_sha256=sha(baseline.read_bytes()),
        output_dir=tmp_path / "prepared",
        run_parent=tmp_path / "runs",
        checkpoint_parent=tmp_path / "checkpoints",
        run_name="native-n0-test",
    )


def test_prepare_rebuilds_course_and_isolates_train_reload(inputs):
    result = prepare(**inputs)
    assert result["status"] == "prepared-not-run"
    assert result["equivalence"]["rows_compared"] == 6
    assert result["equivalence"]["only_prompt_root_mapping"] is True
    assert result["equivalence"]["changed_prompt_messages"] == 6
    assert result["equivalence"]["absolute_path_replacements"] == 12
    assert result["equivalence"]["metadata_equal_without_exclusions"] is True
    assert len(result["equivalence"]["path_diffs"]) == 6
    train = json.loads((inputs["output_dir"] / "train-launch-manifest.json").read_bytes())
    reload = json.loads((inputs["output_dir"] / "reload-launch-manifest.json").read_bytes())
    assert train["environment"]["DSH_VENV"] == str(inputs["venv"])
    assert train["environment"]["PYTHONPATH"] == str(ROOT) + ":" + str(ROOT / "verl")
    assert train["environment"]["RUN_ROOT"] != reload["environment"]["RUN_ROOT"]
    assert reload["environment"]["TRAIN_MAX_SAMPLES"] == "4"
    assert reload["environment"]["TRAIN_BATCH_SIZE"] == "2"
    assert reload["environment"]["VAL_ONLY"] == "True"
    assert not Path(train["environment"]["RUN_ROOT"]).exists()
    assert not Path(train["environment"]["CKPTS_DIR"]).exists()
    with pytest.raises(FileExistsError):
        prepare(**inputs)


@pytest.mark.parametrize("bad", ["manifest", "parquet", "business", "runtime", "revision", "name"])
def test_rejects_invalid_baseline_or_target(inputs, bad):
    baseline = json.loads(inputs["baseline_manifest"].read_bytes())
    if bad == "manifest":
        inputs["baseline_manifest_sha256"] = sha(b"bad")
    elif bad == "runtime":
        inputs["runtime_executable"].write_bytes(b"bad")
    elif bad == "revision":
        inputs["expected_revision"] = "0" * 40
    elif bad == "name":
        inputs["run_name"] = "../old"
    elif bad in ("parquet", "business"):
        file = Path(baseline["environment"]["TRAIN_FILE"])
        if bad == "parquet":
            file.write_bytes(b"bad")
        else:
            rows = pq.read_table(file).to_pylist()
            rows[0]["extra_info"]["tools_kwargs"]["task"]["metadata"]["variant"] = "altered"
            pq.write_table(pa.Table.from_pylist(rows), file)
            mpath = file.parent / "manifest.json"
            m = json.loads(mpath.read_bytes())
            m["files"][file.name]["sha256"] = sha(file.read_bytes())
            mpath.write_text(json.dumps(m))
            baseline["curriculum_manifest_sha256"] = sha(mpath.read_bytes())
            inputs["baseline_manifest"].write_text(json.dumps(baseline))
            inputs["baseline_manifest_sha256"] = sha(inputs["baseline_manifest"].read_bytes())
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare(**inputs)
    assert not (inputs["output_dir"] / "plan.json").exists()


@pytest.mark.parametrize("overlap", ["same_run", "prepare_parent", "same_checkpoint"])
def test_rejects_overlapping_output_roots(inputs, overlap):
    if overlap == "same_run":
        inputs["output_dir"] = inputs["run_parent"] / inputs["run_name"]
    elif overlap == "prepare_parent":
        inputs["run_parent"] = inputs["output_dir"]
    else:
        inputs["checkpoint_parent"] = inputs["run_parent"]
    with pytest.raises(ValueError, match="overlap"):
        prepare(**inputs)
    assert not inputs["output_dir"].exists()


def test_baseline_parquet_consumed_from_hashed_snapshot(inputs, monkeypatch):
    from examples.dsh.ops import prepare_native_rebuild as module

    original = module.read
    baseline = json.loads(inputs["baseline_manifest"].read_bytes())
    path = Path(baseline["environment"]["TRAIN_FILE"])

    def replace_after_read(candidate, *args):
        raw = original(candidate, *args)
        if candidate == path:
            candidate.write_bytes(b"changed-after-read")
        return raw

    monkeypatch.setattr(module, "read", replace_after_read)
    assert prepare(**inputs)["equivalence"]["rows_compared"] == 6
