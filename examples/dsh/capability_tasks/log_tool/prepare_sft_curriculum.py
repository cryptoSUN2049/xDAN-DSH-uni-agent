"""Select four original registration decisions; preserve the public dev set."""

import argparse
import io
import os
import re
from pathlib import Path

import pyarrow.parquet as pq

from examples.dsh.capability_tasks.log_tool.prepare_sft_dataset import canonical, checked_bytes, digest, parse, require

FIELDS = {
    "schema",
    "sample_id",
    "case_id",
    "split",
    "session_id",
    "request_index",
    "request_json",
    "target_json",
    "enable_thinking",
    "provenance_json",
}


def checked_rows(table, split, seen_ids, sessions):
    require(set(table.column_names) == FIELDS, "Unexpected decision columns")
    expected_cases = {f"log-tool-{split}-{i:02d}" for i in range(1, 5 if split == "train" else 3)}
    seen_cases = set()
    selected = []
    selected_cases = set()
    for index, row in enumerate(table.to_pylist()):
        case, session = row["case_id"], row["session_id"]
        require(row["schema"] == "dsh.t2-sft-decision.v1" and row["split"] == split, "Decision schema/split mismatch")
        require(case in expected_cases, "Unknown public case source")
        require(isinstance(session, str) and session, "Missing source session")
        require(sessions.setdefault(case, session) == session, "Multiple sessions for one case")
        require(len(set(sessions.values())) == len(sessions), "Session reused across cases")
        step = row["request_index"]
        require(
            type(step) is int and step >= 0 and row["sample_id"] == f"{case}:{step}", "Invalid source sample identity"
        )
        require(row["sample_id"] not in seen_ids, "Duplicate source sample")
        seen_ids.add(row["sample_id"])
        seen_cases.add(case)
        require(row["enable_thinking"] is False, "Unexpected thinking mode")
        for field in ("request_json", "target_json", "provenance_json"):
            require(isinstance(row[field], str), "Decision JSON must remain original text")
            require(isinstance(parse(row[field]), dict), "Decision JSON must be an object")
        target = parse(row["target_json"])
        require(target.get("role") == "assistant", "Target must be assistant")
        calls = target.get("tool_calls", [])
        require(isinstance(calls, list), "Target tool_calls must be structured array")
        for call in calls:
            require(
                isinstance(call, dict) and call.get("type") == "function" and isinstance(call.get("function"), dict),
                "Invalid structured tool call",
            )
        definitions = [call for call in calls if call["function"].get("name") == "cordis_define"]
        if split == "train" and definitions:
            require(len(calls) == 1 and case not in selected_cases, "Duplicate or nonunique registration decision")
            require(
                isinstance(definitions[0]["function"].get("arguments"), dict), "Definition arguments must be structured"
            )
            selected_cases.add(case)
            selected.append(index)
    require(seen_cases == expected_cases, "Missing public case source")
    if split == "train":
        require(selected_cases == expected_cases and len(selected) == 4, "Missing registration decision source")
    else:
        require(table.num_rows == 28, "Expected unchanged 28-row public dev set")
    return selected


def prepare(manifest_path: Path, manifest_sha256: str, output: Path):
    raw_manifest = checked_bytes(manifest_path, manifest_sha256)
    manifest = parse(raw_manifest)
    require(
        manifest.get("schema") == "dsh.t2-sft-dataset.v1" and manifest.get("policy_origin") == "scripted",
        "Invalid original dataset manifest",
    )
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", manifest.get("source_manifest_sha256", "")),
        "Missing original source manifest hash",
    )
    artifacts = manifest.get("artifacts", {})
    require(set(artifacts) == {"train.parquet", "dev.parquet"}, "Expected original train/dev artifacts")
    blobs, tables = {}, {}
    seen_ids, sessions = set(), {}
    indices = None
    for split in ("train", "dev"):
        name = f"{split}.parquet"
        info = artifacts[name]
        blobs[split] = checked_bytes(manifest_path.parent / name, info.get("sha256"))
        tables[split] = pq.read_table(io.BytesIO(blobs[split]))
        require(type(info.get("rows")) is int and info["rows"] == tables[split].num_rows, "Artifact row count mismatch")
        selected = checked_rows(tables[split], split, seen_ids, sessions)
        if split == "train":
            indices = selected
    require(tables["train"].schema == tables["dev"].schema, "Train/dev Arrow schema mismatch")
    train = tables["train"].take(indices)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    stat = output.stat()
    require(
        stat.st_uid == os.getuid() and stat.st_mode & 0o777 == 0o700,
        "Output requires owned private permissions; use a local filesystem",
    )
    pq.write_table(train, output / "train.parquet")
    (output / "dev.parquet").write_bytes(blobs["dev"])
    (output / "original-manifest.json").write_bytes(raw_manifest)
    result = dict(
        schema="dsh.t2-sft-curriculum.v1",
        purpose="registration-curriculum-not-new-data",
        policy_origin="scripted",
        public_dev=True,
        hidden_inputs_verified=False,
        original_manifest_sha256=manifest_sha256,
        original_manifest=manifest,
        source_sample_ids=train.column("sample_id").to_pylist(),
        source_case_ids=train.column("case_id").to_pylist(),
        selection=dict(target_tool="cordis_define", unique_tool_call=True, original_order=True),
        artifacts={
            name: dict(sha256=digest((output / name).read_bytes()), rows=count)
            for name, count in [("train.parquet", 4), ("dev.parquet", 28)]
        },
        original_manifest_copy=dict(path="original-manifest.json", sha256=manifest_sha256),
        preparer_sha256=digest(Path(__file__).read_bytes()),
    )
    (output / "manifest.json").write_text(canonical(result) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(prepare(args.manifest, args.manifest_sha256, args.output_dir)))


if __name__ == "__main__":
    main()
