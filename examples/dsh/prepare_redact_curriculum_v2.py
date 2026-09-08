"""Publish an identity-versioned 4/2 course; preserve original prompts and rewards."""

import argparse
import copy
import io
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from examples.dsh.evolution_verifier_v2 import PARENT_SHA256, bundle_digest, source_hashes
from examples.dsh.prepare_redact_curriculum import PATCH, PATCH_SHA, _require, _sha


def prepare(*, repository_root, source_dir, source_manifest_sha256, runtime_executable, output_dir):
    root = repository_root.resolve()
    _require(root == Path(__file__).resolve().parents[2], "repository must match running source")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(output_dir)
    _require(not output_dir.resolve().is_relative_to(root), "output must be outside repository")
    raw_manifest = (source_dir / "manifest.json").read_bytes()
    _require(_sha(raw_manifest) == source_manifest_sha256, "Source manifest SHA mismatch")
    original = json.loads(raw_manifest)
    _require(original["schema"] == "dsh.redact-curriculum.v1", "Expected original 4/2 course")
    task = original["task"]
    _require(
        task["verifier_id"] == "dsh-harness-evolution-verifier"
        and task["verifier_version"] == "1"
        and task["verifier_code_digest"] == "sha256:" + PARENT_SHA256["evolution_verifier.py"],
        "Wrong parent verifier identity",
    )
    _require(task["environment_digest"] == _sha(runtime_executable.read_bytes()), "Runtime SHA mismatch")
    _require(
        task["patches"] == [PATCH]
        and task["profile"] == "sdk-minimal"
        and _sha((root / PATCH).read_bytes()) == PATCH_SHA,
        "Patch identity mismatch",
    )
    code_digest = bundle_digest()
    rows = {}
    seen = set()
    for split, count in [("train", 4), ("holdout", 2)]:
        name = split + ".parquet"
        raw = (source_dir / name).read_bytes()
        _require(_sha(raw) == original["files"][name]["sha256"], "Parquet SHA mismatch")
        table = pq.read_table(io.BytesIO(raw))
        _require(len(table) == count == original["files"][name]["records"], "Unexpected course size")
        items = table.to_pylist()
        for i, row in enumerate(items, 1):
            metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            _require(
                metadata["scenario_id"] == f"redact-{split}-{i:02d}"
                and metadata["split"] == split
                and metadata["operation"] == "redact_email"
                and metadata["task_version"] == "1",
                "Course identity/split mismatch",
            )
            for key in ["environment_digest", "verifier_id", "verifier_version", "verifier_code_digest", "profile"]:
                _require(metadata[key] == task[key], "Metadata identity mismatch: " + key)
            path = root / metadata["fixture_path"]
            _require(
                not Path(metadata["fixture_path"]).is_absolute()
                and path.resolve().is_relative_to(root)
                and not any(p.is_symlink() for p in [path, *path.parents] if p != root),
                "Invalid fixture path",
            )
            fixture_raw = path.read_bytes()
            _require(
                _sha(fixture_raw) == metadata["fixture_digest"]
                and original["fixtures"][metadata["scenario_id"]]
                == {"path": metadata["fixture_path"], "sha256": _sha(fixture_raw)},
                "Fixture SHA mismatch",
            )
            text = json.loads(fixture_raw)["input"]
            _require(text not in seen, "Duplicate course input")
            seen.add(text)
            metadata.update(task_version="2", verifier_version="2", verifier_code_digest=code_digest)
        rows[split] = pa.Table.from_pylist(items, schema=table.schema)
    config = yaml.safe_load((root / "examples/dsh/evolution_task_config_v2_fast.yaml").read_text())
    config[0]["verifier_command"] = ["python", "-m", "examples.dsh.evolution_verifier_v2"]
    config[0]["verifier_code_digest"] = code_digest
    config[0]["verifier_id"] = task["verifier_id"]
    config[0]["verifier_version"] = "2"
    config_raw = yaml.safe_dump(config, sort_keys=False).encode()
    result = copy.deepcopy(original)
    result.update(
        schema="dsh.redact-curriculum.v2",
        source_manifest_sha256=source_manifest_sha256,
        source_dir=str(source_dir.resolve()),
        source_files=original["files"],
        verifier_sources=source_hashes(),
        task_version="2",
        purpose="execute-given-tool; unchanged reward; completed-policy-failure admission v2",
        files={},
    )
    result["task"].update(verifier_version="2", verifier_code_digest=code_digest)
    result["preparer_sha256"] = _sha(Path(__file__).read_bytes())
    output_dir.mkdir(mode=0o700, parents=False)
    stat = output_dir.stat()
    _require(
        stat.st_uid == os.getuid() and stat.st_mode & 0o777 == 0o700, "Output must support private owned permissions"
    )
    blobs = {"task-config.yaml": config_raw, "original-manifest.json": raw_manifest}
    for split, table in rows.items():
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        blobs[split + ".parquet"] = sink.getvalue().to_pybytes()
    for name, raw in blobs.items():
        with os.fdopen(os.open(output_dir / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(raw)
        result["files"][name] = {"sha256": _sha(raw)}
        if name.endswith(".parquet"):
            result["files"][name]["records"] = len(rows[name[:-8]])
    with os.fdopen(os.open(output_dir / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ["repository-root", "source-dir", "runtime-executable", "output-dir"]:
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    print(json.dumps(prepare(**vars(parser.parse_args()))))


if __name__ == "__main__":
    main()
