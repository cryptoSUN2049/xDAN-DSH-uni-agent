import hashlib
import json
from pathlib import Path

import pytest

from examples.performance_9b import collect_recovery as module

REVISION = "a" * 40
ARMAND = "armand0e/claude-fable-5-claude-code"
TEICH = "TeichAI/Fable-5-Cursor-Traces"


def inventory(repo, paths):
    return [{"repo": repo, "revision": REVISION, "files": paths}]


def file_entry(path, data=b"x"):
    return {"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def test_select_only_requested_original_formats():
    premium_paths = [
        "README.md",
        "openai_chat/train.parquet",
        "openai_chat/validation.parquet",
        "openai_chat/test.parquet",
        "openai_chat/train.jsonl",
        "agent_traces/train.parquet",
        "dataset_infos.json",
    ]
    items = inventory(module.PREMIUM, [file_entry(p) for p in premium_paths])
    for repo in (ARMAND, TEICH):
        items += inventory(repo, [file_entry(p) for p in ("README.md", "traces/a.jsonl", "image.png")])
    selected = module.select_files(items)
    assert len(selected) == 8
    assert {x["path"] for x in selected if x["repo"] == module.PREMIUM} == set(premium_paths[:4])
    assert sum(x["bytes"] for x in selected) == 8


@pytest.mark.parametrize("path", ["../train.jsonl", "/train.jsonl", "a/../../x", "a\\train.jsonl", "a//b", "./x"])
def test_reject_unsafe_paths_even_if_not_selected(path):
    with pytest.raises(ValueError):
        module.select_files(inventory(ARMAND, [file_entry(path)]))


@pytest.mark.parametrize("size", [None, -1, True, module.LIMIT_BYTES + 1])
def test_reject_unknown_or_out_of_budget_sizes(size):
    with pytest.raises(ValueError):
        module.select_files(inventory(TEICH, [{"path": "train.jsonl", "bytes": size}]))


def test_download_pinned_files_and_keep_splits_separate(tmp_path, monkeypatch):
    paths = [f"openai_chat/{split}.parquet" for split in ("train", "validation", "test")]
    files = [file_entry(path) for path in paths]
    observed_requests = []

    def download(**kwargs):
        observed_requests.append(kwargs)
        assert kwargs["revision"] == REVISION and kwargs["repo_type"] == "dataset"
        current = json.loads((tmp_path / "manifest.json").read_text())["current_file"]
        assert current["path"] == kwargs["filename"] and current["phase"] == "downloading"
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        return str(target)

    def rows(path):
        current = json.loads((tmp_path / "manifest.json").read_text())["current_file"]
        assert current["phase"] == "auditing"
        for _ in range({"train": 3, "validation": 2, "test": 1}[path.stem]):
            yield {"model": path.stem, "content": "PRIVATE CONVERSATION MUST NOT APPEAR"}

    monkeypatch.setattr(module, "iter_rows", rows)
    result = module.collect(inventory(module.PREMIUM, files), tmp_path, download)
    assert result["status"] == "succeeded" and result["current_file"] is None
    assert len(observed_requests) == 3
    for item in result["files"]:
        assert item["lfs_sha_verified"] is True
        audit = json.loads((tmp_path / item["audit_path"]).read_text())
        assert audit["rows"] == {"train": 3, "validation": 2, "test": 1}[item["split"]]
        assert audit["model_field_counts"] == {"row.model": {item["split"]: audit["rows"]}}
        assert "PRIVATE CONVERSATION" not in json.dumps(audit)
    # A matching fixed inventory can resume into the same repository directories.
    assert module.collect(inventory(module.PREMIUM, files), tmp_path, download)["status"] == "succeeded"


def test_jsonl_audit_only_records_structure_and_explicit_model_claims(tmp_path):
    raw = {
        "model": "original-model",
        "source": "source-A",
        "type": "assistant",
        "metadata": {"teacher_model": "other-claim"},
        "message": {"role": "assistant", "model": "third-claim", "content": "PRIVATE BODY", "tool_calls": [{}]},
    }
    data = (
        json.dumps(raw) + "\n" + json.dumps({"messages": [{"role": "user", "content": "PRIVATE PROMPT"}]}) + "\n"
    ).encode()
    items = inventory(ARMAND, [file_entry("session.jsonl", data)])

    def download(**kwargs):
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    result = module.collect(items, tmp_path, download)
    audit = json.loads((tmp_path / result["files"][0]["audit_path"]).read_text())
    assert audit["split"] == "not_declared"
    assert audit["rows"] == 2
    assert audit["model_field_counts"] == {
        "row.model": {"original-model": 1},
        "metadata.teacher_model": {"other-claim": 1},
        "message.model": {"third-claim": 1},
    }
    assert audit["structure"]["objects_with_nonempty_tool_calls"] == 1
    assert "PRIVATE BODY" not in json.dumps(audit) and "PRIVATE PROMPT" not in json.dumps(audit)
    assert "NOT independent tasks" in audit["row_unit"]


@pytest.mark.parametrize("failure", ["hash", "size", "path"])
def test_failed_validation_records_failure_and_actual_hash(tmp_path, failure):
    entry = file_entry("train.jsonl", b"{}\n")
    if failure == "hash":
        entry["sha256"] = "0" * 64
    elif failure == "size":
        entry["bytes"] = 100

    def download(**kwargs):
        target = Path(kwargs["local_dir"]) / ("unexpected.jsonl" if failure == "path" else kwargs["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"{}\n")
        return str(target)

    with pytest.raises(ValueError):
        module.collect(inventory(TEICH, [entry]), tmp_path, download)
    saved = json.loads((tmp_path / "manifest.json").read_text())
    assert saved["status"] == saved["files"][0]["status"] == "failed"
    if failure != "path":
        assert saved["files"][0]["actual_sha256"] == hashlib.sha256(b"{}\n").hexdigest()
    assert not list(tmp_path.glob("audits/**/*.json"))


def test_conflicting_inventory_leaves_existing_run_untouched(tmp_path):
    original = inventory(TEICH, [file_entry("train.jsonl")])
    (tmp_path / "inventory.json").write_text(json.dumps(original))
    (tmp_path / "manifest.json").write_text('{"status":"succeeded","important":"preserve"}\n')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    changed = inventory(TEICH, [file_entry("other.jsonl")])

    def forbidden_download(**_kwargs):
        pytest.fail("Conflicting inventory must not download")

    with pytest.raises(ValueError, match="different inventory"):
        module.collect(changed, tmp_path, forbidden_download)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
