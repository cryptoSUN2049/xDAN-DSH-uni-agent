"""Source locking, real schema preservation, and split isolation contracts."""

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from examples.mimo_multidomain_rl import prepare as module


def row(name, domain, kind=None, language="en"):
    extra = (
        {"src_id": name, "lang": language}
        if domain == "music"
        else {
            "index": 12,
            "instance_id": name,
            "dataset_type": kind or domain,
            "instance_json": json.dumps({"instance_id": name, "dataset_type": kind or domain}),
        }
    )
    return {
        "prompt": [{"role": "user", "content": "actual prompt " + name}],
        "data_source": domain,
        "extra_info": extra,
    }


def test_general_requires_both_published_branches_and_distinct_heldout():
    rows = [
        row("terminal1", "general", "terminal_bench"),
        row("s3k1", "general", "general_agent"),
        row("s3k2", "general", "general_agent"),
    ]
    selected = module.select_rows(rows, "general", 12)
    assert [module.instance(r)["dataset_type"] for _, r, split in selected if split == "train"] == [
        "terminal_bench",
        "general_agent",
    ]
    assert len({i for i, _, _ in selected}) == 3
    assert [split for _, _, split in selected] == ["train", "train", "heldout"]
    assert module.select_rows(rows, "general", 12) == selected


def test_general_missing_branch_is_not_relabeled():
    with pytest.raises(ValueError, match="missing required branch"):
        module.select_rows([row(str(i), "general", "general_agent") for i in range(3)], "general", 1)


def test_inner_and_outer_dataset_type_must_match():
    record = row("a", "general", "terminal_bench")
    record["extra_info"]["dataset_type"] = "generic"
    with pytest.raises(ValueError, match="disagree"):
        module.instance(record)


def test_music_preserves_published_schema_and_covers_languages():
    rows = [row("a", "music"), row("b", "music"), row("c", "music", language="zh")]
    selected = module.select_rows(rows, "music", 42)
    assert {record["extra_info"]["lang"] for _, record, split in selected if split == "train"} == {"en", "zh"}
    assert all("agent_name" not in record and "instance_json" not in record["extra_info"] for _, record, _ in selected)


@pytest.mark.parametrize("domain", ["cyber", "general", "music"])
def test_duplicate_task_id_cannot_leak_across_splits(domain):
    with pytest.raises(ValueError, match="duplicate"):
        module.select_rows([row("same", domain)] * 3, domain, 1)


@pytest.mark.parametrize("path", ["../hidden", "/root/hidden", "envs/a/../../escape"])
def test_assets_cannot_escape_output(path):
    with pytest.raises(ValueError, match="unsafe"):
        module.safe_asset_path(path)


def test_source_tamper_rejected_without_overwrite(tmp_path):
    path = tmp_path / "code.parquet"
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="mismatch"):
        module.verified_source(path, {"path": "code.parquet", "bytes": 3, "sha256": module.sha256(b"abc")}, "unused")
    assert path.read_bytes() == b"tampered"


def test_whole_preparation_preserves_schema_and_row_identity(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    files = {}
    originals = {}
    for domain in module.DOMAINS:
        names = (
            ["format-code-task-001661", "format-code-task-002549", "heldout"]
            if domain == "code"
            else ["first", "second", "third"]
        )
        kinds = ["terminal_bench", "general_agent", "general_agent"] if domain == "general" else [None] * 3
        records = [row(name, domain, kind) for name, kind in zip(names, kinds, strict=True)]
        if domain == "general":
            item = json.loads(records[0]["extra_info"]["instance_json"])
            item["tests_files"] = json.dumps({"test.sh": "exit 0", "fixtures/test.json": "{}"})
            records[0]["extra_info"]["instance_json"] = json.dumps(item)
        table = pa.Table.from_pylist(records)
        path = cache / f"{domain}.parquet"
        pq.write_table(table, path)
        raw = path.read_bytes()
        files[domain] = {"path": path.name, "rows": 3, "bytes": len(raw), "sha256": module.sha256(raw)}
        originals[domain] = table
    lock = {"dataset": {"repository": "test/dataset", "revision": "fixed", "files": files}, "selection": {"seed": 42}}
    output = tmp_path / "prepared"
    manifest = module.prepare(output, cache, lock)
    assert manifest["domain_counts"] == dict.fromkeys(module.DOMAINS, 3)
    assert len(manifest["tasks"]) == 15
    for task in manifest["tasks"]:
        original = originals[task["domain"]].to_pylist()[task["source_row"]]
        assert task["original_row"] == original
        assert task["row_sha256"] == module.sha256(module.canonical(original))
        assert task["image_digest"] is None
    for domain in module.DOMAINS:
        for split, count in [("train", 2), ("heldout", 1)]:
            table = pq.read_table(output / domain / f"{split}.parquet")
            assert table.num_rows == count
            assert table.schema == originals[domain].schema
    frozen = (output / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="frozen"):
        module.prepare(output, cache, lock)
    assert (output / "manifest.json").read_bytes() == frozen


def test_missing_locked_code_task_is_fatal():
    with pytest.raises(ValueError, match="locked Code"):
        module.select_rows([row(str(i), "code") for i in range(3)], "code", 1)


def test_nonfinite_provenance_is_rejected():
    with pytest.raises(ValueError):
        module.canonical({"reward": float("nan")})


def test_downloaded_source_is_hashed_before_cache_write(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "fetch", lambda _url: b"abc")
    path = tmp_path / "nested" / "data"
    spec = {"path": "data", "bytes": 3, "sha256": module.sha256(b"abc")}
    assert module.verified_source(path, spec, "https://public.example/data") == b"abc"
    assert path.read_bytes() == b"abc"


@pytest.mark.parametrize("score", [0.0, 1.0, float("nan"), float("inf")])
def test_music_preflight_rejects_unusable_worker_score(tmp_path, monkeypatch, score):
    import ray

    baseline = tmp_path / "scorer" / "baseline.json"
    baseline.parent.mkdir()
    baseline.write_bytes(b"fixed baseline")
    binary = tmp_path / "abc2midi"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    lock = {
        "music_scorer": {
            "path": "scorer",
            "baseline": "baseline.json",
            "baseline_sha256": module.sha256(baseline.read_bytes()),
        }
    }
    shutdowns = []

    class Remote:
        def remote(self, _source, _binary):
            return {"fenced": score, "bare": score}

    monkeypatch.setattr(ray, "is_initialized", lambda: False)
    monkeypatch.setattr(ray, "init", lambda **kwargs: None)
    monkeypatch.setattr(ray, "remote", lambda **kwargs: lambda _function: Remote())
    monkeypatch.setattr(ray, "get", lambda results: results)
    monkeypatch.setattr(ray, "shutdown", lambda: shutdowns.append(True))
    with pytest.raises(ValueError, match="strictly between"):
        module.music_preflight(tmp_path, binary, lock)
    assert shutdowns == [True]


def test_music_preflight_never_reuses_existing_cluster(tmp_path, monkeypatch):
    import ray

    monkeypatch.setattr(ray, "is_initialized", lambda: True)
    with pytest.raises(ValueError, match="independent owned"):
        module.music_preflight(tmp_path, tmp_path / "abc2midi", {})


def test_music_preflight_rejects_modified_baseline(tmp_path, monkeypatch):
    import ray

    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(b"modified")
    monkeypatch.setattr(ray, "is_initialized", lambda: False)
    lock = {"music_scorer": {"path": ".", "baseline": "baseline.json", "baseline_sha256": module.sha256(b"original")}}
    with pytest.raises(ValueError, match="baseline hash"):
        module.music_preflight(tmp_path, tmp_path / "abc2midi", lock)


def test_instance_json_must_encode_object():
    record = row("a", "cyber")
    record["extra_info"]["instance_json"] = "[]"
    with pytest.raises(ValueError, match="encode an object"):
        module.instance(record)


def test_source_identity_must_be_nonempty():
    record = row("", "music")
    with pytest.raises(ValueError, match="missing source identity"):
        module.task_id(record, "music")


def test_small_source_cannot_reuse_train_task_for_heldout():
    with pytest.raises(ValueError, match="three distinct"):
        module.select_rows([row("a", "cyber"), row("b", "cyber")], "cyber", 1)
