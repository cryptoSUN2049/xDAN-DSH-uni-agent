from __future__ import annotations

import copy
import json

import pytest

from examples.harbor_mopd.prepare import fingerprint_task, main, prepare_rows


def fixture_data():
    rows = {}
    tasks = []
    fingerprints = {}
    for index, (split, domain) in enumerate((("train", "swe"), ("train", "terminal"), ("validation", "swe"))):
        instance_id = f"tasks-{split}/task-{index}"
        fingerprint = f"{index + 1:064x}"
        rows.setdefault(split, []).append(
            {
                "data_source": f"tasks-{split}",
                "prompt": [{"role": "user", "content": f"Do task {index}"}],
                "reward_model": {"style": "rule"},
                "extra_info": {
                    "tools_kwargs": {
                        "task": {
                            "name": "harbor",
                            "metadata": {"instance_id": instance_id, "task_path": f"/tasks/{index}"},
                        }
                    }
                },
            }
        )
        tasks.append(
            {
                "instance_id": instance_id,
                "task_id": f"task-{index}",
                "source": "benchmark",
                "family": "example/repo",
                "revision": "a" * 40,
                "split": split,
                "fingerprint": fingerprint,
                "teacher_domain": domain,
            }
        )
        fingerprints[instance_id] = fingerprint
    return rows, {"schema_version": 1, "tasks": tasks}, fingerprints


def prepare(rows, manifest, fingerprints):
    return prepare_rows(rows, manifest, allowed_domains={"swe", "terminal"}, task_fingerprints=fingerprints)


def test_preserves_harbor_and_source_and_assigns_explicit_domain_without_mutation():
    rows, manifest, fingerprints = fixture_data()
    before = copy.deepcopy(rows)
    result, receipt = prepare(rows, manifest, fingerprints)
    assert rows == before
    assert [r["teacher_domain"] for r in result["train"]] == ["swe", "terminal"]
    for split, prepared in result.items():
        for index, row in enumerate(prepared):
            assert {k: row[k] for k in rows[split][index]} == rows[split][index]
            assert row["mopd_task"]["ordered_index"] == index
    assert receipt["splits"]["train"]["domain_counts"] == {"swe": 1, "terminal": 1}
    assert receipt["splits"]["validation"]["rows"] == 1


@pytest.mark.parametrize(
    "field", ["instance_id", "task_id", "source", "family", "revision", "fingerprint", "teacher_domain"]
)
def test_missing_identity_field_fails(field):
    rows, manifest, fingerprints = fixture_data()
    del manifest["tasks"][0][field]
    with pytest.raises(ValueError, match=field):
        prepare(rows, manifest, fingerprints)


@pytest.mark.parametrize("domain", ["", "unknown", None])
def test_missing_or_unknown_teacher_domain_fails(domain):
    rows, manifest, fingerprints = fixture_data()
    manifest["tasks"][0]["teacher_domain"] = domain
    with pytest.raises(ValueError, match="teacher_domain"):
        prepare(rows, manifest, fingerprints)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "wrong_split", "stale_fingerprint"])
def test_join_is_exact_and_fingerprint_checked(mutation):
    rows, manifest, fingerprints = fixture_data()
    if mutation == "missing":
        manifest["tasks"].pop()
    elif mutation == "extra":
        extra = dict(manifest["tasks"][0], instance_id="extra", task_id="extra", fingerprint="f" * 64)
        manifest["tasks"].append(extra)
    elif mutation == "duplicate":
        manifest["tasks"].append(manifest["tasks"][0].copy())
    elif mutation == "wrong_split":
        manifest["tasks"][0]["split"] = "validation"
    else:
        fingerprints[manifest["tasks"][0]["instance_id"]] = "f" * 64
    with pytest.raises(ValueError):
        prepare(rows, manifest, fingerprints)


@pytest.mark.parametrize("overlap", ["identity", "fingerprint"])
def test_train_validation_overlap_cannot_hide_behind_different_instance_ids(overlap):
    rows, manifest, fingerprints = fixture_data()
    first, last = manifest["tasks"][0], manifest["tasks"][-1]
    if overlap == "identity":
        last["task_id"] = first["task_id"]
        last["revision"] = "b" * 40
    else:
        last["fingerprint"] = first["fingerprint"]
        fingerprints[last["instance_id"]] = first["fingerprint"]
    with pytest.raises(ValueError, match="overlap"):
        prepare(rows, manifest, fingerprints)


def test_rejects_non_harbor_rows_and_existing_conflicting_routes():
    rows, manifest, fingerprints = fixture_data()
    rows["train"][0]["extra_info"]["tools_kwargs"]["task"]["name"] = "other"
    with pytest.raises(ValueError, match="Harbor"):
        prepare(rows, manifest, fingerprints)
    rows, manifest, fingerprints = fixture_data()
    rows["train"][0]["teacher_domain"] = "terminal"
    with pytest.raises(ValueError, match="conflicting"):
        prepare(rows, manifest, fingerprints)


def test_fingerprint_is_relocatable_covers_content_and_rejects_symlinks(tmp_path):
    for name in ("one", "two"):
        task = tmp_path / name
        task.mkdir()
        (task / "task.toml").write_text("version = 1")
        (task / "instruction.md").write_text("solve")
    one, two = tmp_path / "one", tmp_path / "two"
    assert fingerprint_task(one) == fingerprint_task(two)
    (two / "instruction.md").write_text("changed")
    assert fingerprint_task(one) != fingerprint_task(two)
    (two / "link").symlink_to(one / "instruction.md")
    with pytest.raises(ValueError, match="symlink"):
        fingerprint_task(two)


def test_cli_writes_parquet_and_verifiable_receipt(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    rows, manifest, _ = fixture_data()
    for index, task in enumerate(manifest["tasks"]):
        root = tmp_path / f"task-{index}"
        root.mkdir()
        (root / "task.toml").write_text(f"version = {index}")
        task["fingerprint"] = fingerprint_task(root)
        for row in rows[task["split"]]:
            metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            if metadata["instance_id"] == task["instance_id"]:
                metadata["task_path"] = str(root)
    for split, values in rows.items():
        pq.write_table(pa.Table.from_pylist(values), tmp_path / f"{split}.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / "output"
    argv = [
        "--train-parquet",
        str(tmp_path / "train.parquet"),
        "--validation-parquet",
        str(tmp_path / "validation.parquet"),
        "--manifest",
        str(manifest_path),
        "--domains",
        "swe",
        "terminal",
        "--output-dir",
        str(output),
    ]
    main(argv)
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["splits"]["train"]["rows"] == 2
    assert receipt["files"]["train"]["sha256"]
    result = pq.read_table(output / "train.parquet").to_pylist()
    assert result[0]["data_source"] == "tasks-train"
    assert result[0]["teacher_domain"] == "swe"
    with pytest.raises(FileExistsError):
        main(argv)


def test_explicit_leakage_groups_block_task_variants_but_not_shared_repositories():
    rows, manifest, fingerprints = fixture_data()
    manifest["tasks"][0]["leakage_group"] = "underlying-problem-42"
    manifest["tasks"][1]["leakage_group"] = "underlying-problem-42"
    result, receipt = prepare(rows, manifest, fingerprints)
    assert result["train"][0]["mopd_task"]["leakage_group"] == "underlying-problem-42"
    assert receipt["schema"] == "harbor-mopd-data-receipt"
    manifest["tasks"][-1]["leakage_group"] = "underlying-problem-42"
    with pytest.raises(ValueError, match="leakage_group overlap"):
        prepare(rows, manifest, fingerprints)


@pytest.mark.parametrize("case", ["empty_train", "empty_domain", "duplicate_row", "bad_sha", "empty_leakage_group"])
def test_invalid_preflight_inputs_fail_closed(case):
    rows, manifest, fingerprints = fixture_data()
    domains = {"swe", "terminal"}
    if case == "empty_train":
        rows["train"] = []
    elif case == "empty_domain":
        domains = set()
    elif case == "duplicate_row":
        rows["train"].append(copy.deepcopy(rows["train"][0]))
    elif case == "bad_sha":
        manifest["tasks"][0]["fingerprint"] = "not-a-sha"
    else:
        manifest["tasks"][0]["leakage_group"] = ""
    with pytest.raises(ValueError):
        prepare_rows(rows, manifest, allowed_domains=domains, task_fingerprints=fingerprints)


def test_repreparation_is_idempotent_but_rejects_stale_identity():
    rows, manifest, fingerprints = fixture_data()
    first, receipt = prepare(rows, manifest, fingerprints)
    second, second_receipt = prepare(first, manifest, fingerprints)
    assert first == second
    assert receipt == second_receipt
    first["train"][0]["mopd_task"]["revision"] = "stale"
    with pytest.raises(ValueError, match="conflicting mopd_task"):
        prepare(first, manifest, fingerprints)
