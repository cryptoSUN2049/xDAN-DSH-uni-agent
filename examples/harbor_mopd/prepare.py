"""Join audited Harbor task identities to explicit MOPD teacher domains.

The manifest is an authoritative input, not a domain classifier. Each task entry
requires instance_id, task_id, source, family, revision, split, fingerprint and
teacher_domain. Fingerprints are produced by ``fingerprint_task``. CLI preparation
verifies task contents on disk and preserves all original Harbor parquet fields.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SPLITS = ("train", "validation")
IDENTITY_FIELDS = ("instance_id", "task_id", "source", "family", "revision", "split", "fingerprint", "teacher_domain")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_task(path: Path | str) -> str:
    """Hash relative file names, permissions and contents; never follow symlinks."""
    root = Path(path).expanduser()
    if root.is_symlink():
        raise ValueError(f"task root is a symlink: {root}")
    if not root.is_dir() or not (root / "task.toml").is_file():
        raise ValueError(f"Harbor task directory must contain task.toml: {root}")
    entries = []
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"task fingerprint rejects symlink: {item}")
        if item.is_file():
            entries.append([item.relative_to(root).as_posix(), item.stat().st_mode & 0o777, file_sha256(item)])
        elif not item.is_dir():
            raise ValueError(f"task fingerprint rejects special file: {item}")
    return _digest(entries)


def _metadata(row: dict) -> dict:
    try:
        task = row["extra_info"]["tools_kwargs"]["task"]
        if task["name"] != "harbor":
            raise ValueError("MOPD preparation requires Harbor task dispatch")
        metadata = task["metadata"]
        if not isinstance(metadata["instance_id"], str) or not metadata["instance_id"].strip():
            raise ValueError("Harbor instance_id must be a nonempty string")
        if not isinstance(row["data_source"], str) or not row["data_source"].strip():
            raise ValueError("Harbor data_source must be a nonempty string")
        return metadata
    except (KeyError, TypeError) as exc:
        raise ValueError("row is missing Harbor task metadata or data_source") from exc


def prepare_rows(
    rows_by_split: dict[str, list[dict]],
    manifest: dict,
    *,
    allowed_domains: set[str],
    task_fingerprints: dict[str, str],
) -> tuple[dict[str, list[dict]], dict]:
    """Pure validated join. Fingerprints must come from trusted task contents.

    Canonical (source, task_id) identities cannot cross splits even at different
    revisions; identical task-content fingerprints cannot cross splits either.
    Optional explicit leakage_group binds task variants across renamed identities;
    family is provenance and does not ban a shared repository across splits.
    The manifest must match all input rows exactly, including their split.
    """
    if not allowed_domains or any(not isinstance(d, str) or not d.strip() for d in allowed_domains):
        raise ValueError("allowed_domains must contain nonempty domain names")
    if set(rows_by_split) != set(SPLITS) or any(not rows_by_split[s] for s in SPLITS):
        raise ValueError("both train and validation splits must be nonempty")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("tasks"), list):
        raise ValueError("manifest requires schema_version=1 and tasks list")
    entries = {}
    identity_splits = {}
    fingerprint_splits = {}
    leakage_splits = {}
    for entry in manifest["tasks"]:
        if not isinstance(entry, dict):
            raise ValueError("manifest task entry must be an object")
        for field in IDENTITY_FIELDS:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"manifest task requires nonempty {field}")
        instance_id, split = entry["instance_id"], entry["split"]
        if instance_id in entries:
            raise ValueError(f"duplicate manifest instance_id: {instance_id}")
        if split not in SPLITS:
            raise ValueError(f"unknown manifest split: {split}")
        if entry["teacher_domain"] not in allowed_domains:
            raise ValueError(f"unknown teacher_domain: {entry['teacher_domain']}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["fingerprint"]):
            raise ValueError(f"fingerprint must be lowercase SHA256: {instance_id}")
        identity = (entry["source"], entry["task_id"])
        if identity in identity_splits:
            if identity_splits[identity] != split:
                raise ValueError(f"train/validation identity overlap: {identity}")
            raise ValueError(f"duplicate canonical task identity: {identity}")
        digest = entry["fingerprint"]
        if digest in fingerprint_splits and fingerprint_splits[digest] != split:
            raise ValueError(f"train/validation fingerprint overlap: {instance_id}")
        identity_splits[identity] = split
        fingerprint_splits[digest] = split
        if "leakage_group" in entry:
            group = entry["leakage_group"]
            if not isinstance(group, str) or not group.strip():
                raise ValueError(f"leakage_group must be a nonempty string: {instance_id}")
            if group in leakage_splits and leakage_splits[group] != split:
                raise ValueError(f"train/validation leakage_group overlap: {group}")
            leakage_splits[group] = split
        entries[instance_id] = entry

    prepared, seen = {}, set()
    for split in SPLITS:
        prepared[split] = []
        for index, row in enumerate(rows_by_split[split]):
            instance_id = _metadata(row)["instance_id"]
            if instance_id in seen:
                raise ValueError(f"duplicate input instance_id: {instance_id}")
            seen.add(instance_id)
            entry = entries.get(instance_id)
            if entry is None:
                raise ValueError(f"missing manifest task: {instance_id}")
            if entry["split"] != split:
                raise ValueError(f"manifest split mismatch: {instance_id}")
            if task_fingerprints.get(instance_id) != entry["fingerprint"]:
                raise ValueError(f"task fingerprint mismatch: {instance_id}")
            if "teacher_domain" in row and row["teacher_domain"] != entry["teacher_domain"]:
                raise ValueError(f"conflicting teacher_domain: {instance_id}")
            task_identity = {field: entry[field] for field in IDENTITY_FIELDS}
            task_identity["ordered_index"] = index
            if "leakage_group" in entry:
                task_identity["leakage_group"] = entry["leakage_group"]
            if "mopd_task" in row and row["mopd_task"] != task_identity:
                raise ValueError(f"conflicting mopd_task identity: {instance_id}")
            result = copy.deepcopy(row)
            result.update(teacher_domain=entry["teacher_domain"], mopd_task=task_identity)
            prepared[split].append(result)
    if seen != set(entries):
        raise ValueError(f"manifest contains unused task entries: {sorted(set(entries) - seen)}")
    receipt = {
        "schema": "harbor-mopd-data-receipt",
        "schema_version": 1,
        "manifest_sha256": _digest(manifest),
        "allowed_domains": sorted(allowed_domains),
        "fingerprint_algorithm": "sha256-canonical-json-relative-files-mode-content-v1",
        "splits": {
            split: {
                "rows": len(prepared[split]),
                "domain_counts": dict(sorted(Counter(row["teacher_domain"] for row in prepared[split]).items())),
                "rows_sha256": _digest(prepared[split]),
                "instance_ids": [row["mopd_task"]["instance_id"] for row in prepared[split]],
            }
            for split in SPLITS
        },
    }
    return prepared, receipt


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-parquet", required=True, type=Path)
    parser.add_argument("--validation-parquet", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--domains", required=True, nargs="+")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    output = args.output_dir.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")

    import pyarrow as pa
    import pyarrow.parquet as pq

    paths = {
        "train": args.train_parquet.expanduser().resolve(),
        "validation": args.validation_parquet.expanduser().resolve(),
    }
    rows = {split: pq.read_table(path).to_pylist() for split, path in paths.items()}
    manifest = json.loads(args.manifest.read_text())
    fingerprints = {}
    for split in SPLITS:
        for row in rows[split]:
            metadata = _metadata(row)
            if not isinstance(metadata.get("task_path"), str) or not metadata["task_path"].strip():
                raise ValueError("Harbor metadata requires task_path for fingerprint verification")
            fingerprints[metadata["instance_id"]] = fingerprint_task(metadata["task_path"])
    prepared, receipt = prepare_rows(rows, manifest, allowed_domains=set(args.domains), task_fingerprints=fingerprints)
    receipt["inputs"] = {split: {"path": str(path), "sha256": file_sha256(path)} for split, path in paths.items()}
    receipt["manifest_file_sha256"] = file_sha256(args.manifest)
    output.mkdir(parents=True, exist_ok=False)
    receipt["files"] = {}
    for split in SPLITS:
        path = output / f"{split}.parquet"
        pq.write_table(pa.Table.from_pylist(prepared[split]), path)
        receipt["files"][split] = {"path": str(path), "sha256": file_sha256(path)}
    # Written last: partial preparation never has a success receipt.
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"Prepared {sum(len(values) for values in prepared.values())} tasks; receipt: {output / 'receipt.json'}")


if __name__ == "__main__":
    main()
