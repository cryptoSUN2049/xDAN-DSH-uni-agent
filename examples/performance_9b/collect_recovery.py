"""Download pinned recovery sources and audit metadata, never produce training data."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

LIMIT_BYTES = 2 * 1024**3
PREMIUM = "saidutta69/fable-5-premium"
TRACE_REPOS = {"armand0e/claude-fable-5-claude-code", "TeichAI/Fable-5-Cursor-Traces"}
MODEL_FIELDS = {"model", "model_id", "model_name", "teacher_model"}


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Invalid relative source path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Source path escapes or is not canonical")
    return path


def select_files(inventory):
    selected, seen, total = [], set(), 0
    if not isinstance(inventory, list):
        raise ValueError("Inventory must be a list")
    for source in inventory:
        repo, revision = source["repo"], source["revision"]
        if repo not in TRACE_REPOS | {PREMIUM}:
            raise ValueError("Unapproved repository")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Require an immutable commit revision")
        for item in source["files"]:
            path = validate_path(item["path"])
            wanted = str(path) == "README.md"
            if repo == PREMIUM:
                wanted |= str(path) in {f"openai_chat/{split}.parquet" for split in ("train", "validation", "test")}
            else:
                wanted |= path.suffix == ".jsonl"
            if not wanted:
                continue
            size, sha = item.get("bytes"), item.get("sha256")
            if type(size) is not int or size < 0:
                raise ValueError("Selected file size must be known and nonnegative")
            if sha is not None and (not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)):
                raise ValueError("Invalid source SHA256")
            key = (repo, revision, str(path))
            if key in seen:
                raise ValueError("Duplicate inventory file")
            seen.add(key)
            total += size
            if total > LIMIT_BYTES:
                raise ValueError("Selected files exceed 2 GiB")
            selected.append({"repo": repo, "revision": revision, "path": str(path), "bytes": size, "sha256": sha})
    if not selected:
        raise ValueError("No eligible files")
    return selected


def split_of(path):
    stem = PurePosixPath(path).stem.lower()
    if stem in {"train", "validation", "test"}:
        return stem
    return "not_declared"


def iter_rows(path):
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(path).iter_batches(batch_size=64):
            yield from batch.to_pylist()
    else:
        with path.open() as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)


def label(value):
    if not isinstance(value, (str, int, float, bool)):
        return f"<{type(value).__name__}>"
    text = str(value)
    # Do not expose path-like/private identifiers accidentally stored in labels.
    if len(text) > 160 or "\n" in text or "@" in text or text.startswith(("/", "~")):
        return "<redacted_label_sha256:" + hashlib.sha256(text.encode()).hexdigest() + ">"
    return text


def audit_rows(rows):
    schemas, models, sources, events, roles = (defaultdict(Counter) for _ in range(5))
    structure = Counter()
    count = 0

    def visit(value, scope="row"):
        if isinstance(value, list):
            for entry in value:
                visit(entry, scope)
            return
        if not isinstance(value, dict):
            return
        schemas[scope].update(value.keys())
        for key in MODEL_FIELDS:
            if value.get(key) is not None:
                models[f"{scope}.{key}"][label(value[key])] += 1
        if value.get("source") is not None:
            sources[scope][label(value["source"])] += 1
        for key in ("type", "event_type", "eventtype"):
            if value.get(key) is not None:
                events[f"{scope}.{key}"][label(value[key])] += 1
        if value.get("role") is not None:
            roles[scope][label(value["role"])] += 1
        if "tool_calls" in value:
            structure["objects_with_tool_calls_field"] += 1
            if value["tool_calls"]:
                structure["objects_with_nonempty_tool_calls"] += 1
        if "tool_call_id" in value:
            structure["objects_with_tool_call_id"] += 1
        # No conversation content, tool arguments, outputs, or reasoning is inspected/exported.
        for key, next_scope in (
            ("metadata", "metadata"),
            ("message", "message"),
            ("messages", "message"),
            ("messages_json", "message"),
            ("event", "event"),
            ("events", "event"),
            ("data", "data"),
        ):
            child = value.get(key)
            if isinstance(child, str) and key in {"metadata", "messages_json"}:
                try:
                    child = json.loads(child)
                except ValueError:
                    structure[f"invalid_{key}_json"] += 1
                    continue
            if isinstance(child, (list, dict)):
                visit(child, next_scope)

    for row in rows:
        count += 1
        if not isinstance(row, dict):
            structure["nonobject_rows"] += 1
        visit(row)
    return {
        "rows": count,
        "row_unit": "serialized rows/events, NOT independent tasks",
        "schema_key_counts": dict(schemas),
        "model_field_counts": dict(models),
        "source_counts": dict(sources),
        "event_type_counts": dict(events),
        "role_counts": dict(roles),
        "structure": dict(structure),
        "teacher_attestation": "unverified; missing model fields remain unknown; no teacher inference",
    }


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def collect(inventory, output, downloader=None):
    output = Path(output)
    snapshot = output / "inventory.json"
    if snapshot.exists() and json.loads(snapshot.read_text()) != inventory:
        raise ValueError("Output belongs to a different inventory")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"status": "running", "purpose": "original-source recovery audit, NOT training data", "files": []}
    current = None
    try:
        files = select_files(inventory)
        save_json(snapshot, inventory)
        manifest["selected_bytes"] = sum(item["bytes"] for item in files)
        if downloader is None:
            from huggingface_hub import hf_hub_download

            downloader = hf_hub_download
        for item in files:
            current = {**item, "split": split_of(item["path"]), "status": "running"}
            manifest["files"].append(current)
            manifest["current_file"] = {"repo": item["repo"], "path": item["path"], "phase": "downloading"}
            save_json(output / "manifest.json", manifest)
            repo_dir = output / "raw" / item["repo"] / item["revision"]
            expected = repo_dir / item["path"]
            if not expected.resolve().is_relative_to(output.resolve()):
                raise ValueError("Local destination escapes output")
            downloaded = Path(
                downloader(
                    repo_id=item["repo"],
                    filename=item["path"],
                    repo_type="dataset",
                    revision=item["revision"],
                    local_dir=str(repo_dir),
                )
            )
            if downloaded.resolve() != expected.resolve():
                raise ValueError("Downloader returned unexpected destination")
            current["actual_bytes"] = downloaded.stat().st_size
            current["actual_sha256"] = digest_file(downloaded)
            if current["actual_bytes"] != item["bytes"]:
                raise ValueError("Downloaded size mismatch")
            if item["sha256"] is not None and current["actual_sha256"] != item["sha256"]:
                raise ValueError("Downloaded SHA256 mismatch")
            current["lfs_sha_verified"] = item["sha256"] is not None
            manifest["current_file"]["phase"] = "auditing"
            save_json(output / "manifest.json", manifest)
            if downloaded.suffix in {".jsonl", ".parquet"}:
                audit = audit_rows(iter_rows(downloaded))
            else:
                audit = {"kind": "README", "content_not_exported": True}
            audit.update(repo=item["repo"], revision=item["revision"], path=item["path"], split=current["split"])
            audit_path = Path("audits") / item["repo"] / item["revision"] / (item["path"] + ".audit.json")
            save_json(output / audit_path, audit)
            current.update(status="succeeded", audit_path=str(audit_path))
            save_json(output / "manifest.json", manifest)
        manifest["status"] = "succeeded"
        manifest["current_file"] = None
    except Exception as exc:
        manifest.update(status="failed", error_type=type(exc).__name__)
        # Parser/download errors may contain private text or credentials: no exception body export.
        if current is not None:
            current.update(status="failed", error_type=type(exc).__name__)
        save_json(output / "manifest.json", manifest)
        raise
    save_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = collect(json.loads(args.inventory.read_text()), args.output_dir)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    print(json.dumps({"status": result["status"], "files": len(result["files"])}))


if __name__ == "__main__":
    main()
