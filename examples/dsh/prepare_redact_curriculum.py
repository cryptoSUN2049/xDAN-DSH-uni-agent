"""Select immutable public email-redaction execution exercises; never run a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from examples.dsh.prepare_evolution_dataset import _patches_digest

PATCH = "examples/dsh/evolution.patch.yml"
PATCH_SHA = "sha256:edace17a8096ec41e572c10fc7ad96f0d9a62c0a6ff9c8271694b4c1b1024aeb"


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def prepare(
    *, repository_root: Path, source_dir: Path, source_manifest_sha256: str, runtime_executable: Path, output_dir: Path
) -> dict:
    """Validate all source bytes before publishing an unchanged 4/2 selection."""
    root = repository_root.resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    _require(not output_dir.resolve().is_relative_to(root), "output must be outside repository")
    raw = (source_dir / "manifest.json").read_bytes()
    _require(_sha(raw) == source_manifest_sha256, "source manifest SHA mismatch")
    manifest = json.loads(raw)
    _require(manifest["schema"] == "dsh.evolution-dataset-manifest.v1", "unsupported source schema")
    _require(manifest["counts"] == {"train": 16, "holdout": 8}, "expected full 16/8 source")
    task = manifest["task"]
    _require(
        task["task_name"] == "dsh_architecture" and task["profile"] == "sdk-minimal" and task["patches"] == [PATCH],
        "unsupported runtime configuration",
    )
    _require(
        task["verifier_id"] == "dsh-harness-evolution-verifier" and task["verifier_version"] == "1",
        "unsupported verifier",
    )
    _require(_sha(runtime_executable.read_bytes()) == task["environment_digest"], "runtime SHA mismatch")
    _require(
        _sha((root / "examples/dsh/evolution_verifier.py").read_bytes()) == task["verifier_code_digest"],
        "verifier SHA mismatch",
    )
    _require(_sha((root / PATCH).read_bytes()) == PATCH_SHA, "patch bytes mismatch")
    tables, selected, fixtures = {}, {}, {}
    seen_inputs, seen_ids = set(), set()
    for split, total, count in [("train", 16, 4), ("holdout", 8, 2)]:
        filename = split + ".parquet"
        raw = (source_dir / filename).read_bytes()
        source_info = manifest["files"][filename]
        _require(_sha(raw) == source_info["sha256"], "source parquet SHA mismatch")
        table = pq.read_table(pa.BufferReader(raw))
        _require(len(table) == total == source_info["records"], "source parquet count mismatch")
        indices, ids = [], []
        for index, row in enumerate(table.to_pylist()):
            config = row["extra_info"]["tools_kwargs"]["task"]
            metadata = config["metadata"]
            if metadata["operation"] != "redact_email":
                continue
            scenario = metadata["scenario_id"]
            _require(
                config["name"] == "dsh_architecture" and metadata["split"] == split, "selected task or split mismatch"
            )
            for key in ["environment_digest", "verifier_id", "verifier_version", "verifier_code_digest", "profile"]:
                _require(metadata[key] == task[key], "selected metadata mismatch: " + key)
            _require(metadata["patches_sha256"] == _patches_digest([PATCH]), "patch paths mismatch")
            relative = Path(metadata["fixture_path"])
            _require(not relative.is_absolute() and ".." not in relative.parts, "invalid fixture path")
            path = root / relative
            _require(
                path.resolve().is_relative_to(root)
                and not any(p.is_symlink() for p in [path, *path.parents] if p != root),
                "fixture must be a repository regular file without symlinks",
            )
            fixture_raw = path.read_bytes()
            fixture_info = manifest["fixtures"][scenario]
            _require(
                fixture_info == {"path": str(relative), "sha256": _sha(fixture_raw)}
                and metadata["fixture_digest"] == _sha(fixture_raw),
                "fixture SHA/path mismatch",
            )
            _require(str(path) in json.dumps(row["prompt"], ensure_ascii=False), "prompt fixture path mismatch")
            fixture = json.loads(fixture_raw)
            _require(
                fixture.get("operation") == "redact_email" and isinstance(fixture.get("input"), str),
                "expected single-string email fixture",
            )
            identity = (metadata["task_id"], metadata["task_version"])
            _require(
                identity not in seen_ids and fixture["input"] not in seen_inputs,
                "duplicate task or overlapping public inputs",
            )
            seen_ids.add(identity)
            seen_inputs.add(fixture["input"])
            indices.append(index)
            ids.append(scenario)
            fixtures[scenario] = fixture_info
        _require(
            ids == [f"redact-{split}-{i:02d}" for i in range(1, count + 1)], "expected ordered redact 4/2 scenarios"
        )
        tables[split] = table.take(indices)
        selected[split] = {"source_indices": indices, "scenario_ids": ids, "records": count}
    result = {
        "schema": "dsh.redact-curriculum.v1",
        "source_manifest_sha256": source_manifest_sha256,
        "source_dir": str(source_dir.resolve()),
        "source_files": manifest["files"],
        "task": task,
        "patch_file_sha256": PATCH_SHA,
        "fixtures": fixtures,
        "selection": selected,
        "purpose": "execute-given-tool; single-string email redaction; unchanged seven-component reward",
        "public_holdout": True,
        "hidden_inputs_verified": False,
        "files": {},
    }
    output_dir.mkdir(mode=0o700, parents=False)
    for split, table in tables.items():
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        raw = sink.getvalue().to_pybytes()
        filename = split + ".parquet"
        with os.fdopen(os.open(output_dir / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(raw)
        result["files"][filename] = {"sha256": _sha(raw), "records": len(table)}
    with os.fdopen(os.open(output_dir / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ["repository-root", "source-dir", "runtime-executable", "output-dir"]:
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({"selection": result["selection"], "files": result["files"]}))


if __name__ == "__main__":
    main()
