import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from examples.dsh.capability_tasks.log_tool.prepare_sft_curriculum import prepare


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def source(tmp_path, mutate=None):
    root = tmp_path / "source"
    root.mkdir()
    splits = {}
    for split, count in [("train", 4), ("dev", 2)]:
        rows = []
        for case in range(1, count + 1):
            case_id = f"log-tool-{split}-{case:02d}"
            for i in range(14):
                target = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{i}",
                            "type": "function",
                            "function": {"name": "cordis_define" if i == 2 else "other", "arguments": {}},
                        }
                    ],
                }
                rows.append(
                    dict(
                        schema="dsh.t2-sft-decision.v1",
                        sample_id=f"{case_id}:{i}",
                        case_id=case_id,
                        split=split,
                        session_id=f"session-{case_id}",
                        request_index=i,
                        request_json='{"messages":[],"tools":[]}',
                        target_json=json.dumps(target),
                        enable_thinking=False,
                        provenance_json="{}",
                    )
                )
        splits[split] = rows
    if mutate:
        mutate(splits)
    artifacts = {}
    for split, rows in splits.items():
        path = root / f"{split}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), path)
        artifacts[path.name] = dict(sha256=digest(path.read_bytes()), rows=len(rows))
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            dict(
                schema="dsh.t2-sft-dataset.v1",
                policy_origin="scripted",
                source_manifest_sha256="sha256:" + "a" * 64,
                artifacts=artifacts,
            )
        )
    )
    return manifest, digest(manifest.read_bytes()), splits


def test_selects_unchanged_rows_and_copies_dev_deterministically(tmp_path):
    manifest, sha, splits = source(tmp_path)
    first = tmp_path / "first"
    report = prepare(manifest, sha, first)
    expected = [row for row in splits["train"] if row["request_index"] == 2]
    assert pq.read_table(first / "train.parquet").to_pylist() == expected
    assert (first / "dev.parquet").read_bytes() == (manifest.parent / "dev.parquet").read_bytes()
    assert report["purpose"] == "registration-curriculum-not-new-data"
    assert report["source_sample_ids"] == [row["sample_id"] for row in expected]
    second = tmp_path / "second"
    prepare(manifest, sha, second)
    assert (first / "train.parquet").read_bytes() == (second / "train.parquet").read_bytes()
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        prepare(manifest, sha, first)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s["train"].pop(2),
        lambda s: s["train"].append(s["train"][2].copy()),
        lambda s: s["train"][2].update(split="dev"),
        lambda s: s["dev"][0].update(schema="unknown"),
        lambda s: s["train"][2].update(target_json='{"role":"assistant","tool_calls":[]}'),
    ],
)
def test_invalid_sources_rejected_before_output(tmp_path, mutation):
    manifest, sha, _ = source(tmp_path, mutation)
    with pytest.raises(ValueError):
        prepare(manifest, sha, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("target", ["manifest", "train", "dev"])
def test_hash_tamper(tmp_path, target):
    manifest, sha, _ = source(tmp_path)
    path = manifest if target == "manifest" else manifest.parent / f"{target}.parquet"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="[Hh]ash"):
        prepare(manifest, sha, tmp_path / "out")


def test_two_registration_rows_from_one_case_rejected(tmp_path):
    def mutate(splits):
        splits["train"][3]["target_json"] = splits["train"][2]["target_json"]

    manifest, sha, _ = source(tmp_path, mutate)
    with pytest.raises(ValueError, match="Duplicate"):
        prepare(manifest, sha, tmp_path / "out")


def test_nonunique_definition_call_rejected(tmp_path):
    def mutate(splits):
        row = splits["train"][2]
        target = json.loads(row["target_json"])
        target["tool_calls"].append(target["tool_calls"][0].copy())
        row["target_json"] = json.dumps(target)

    manifest, sha, _ = source(tmp_path, mutate)
    with pytest.raises(ValueError, match="nonunique"):
        prepare(manifest, sha, tmp_path / "out")


def test_mkdir_ignoring_permissions_leaves_no_artifacts(tmp_path, monkeypatch):
    from pathlib import Path

    manifest, sha, _ = source(tmp_path)
    original = Path.mkdir

    def mkdir(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.chmod(0o777)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="private permissions"):
        prepare(manifest, sha, output)
    assert list(output.iterdir()) == []
