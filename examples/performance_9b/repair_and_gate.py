"""Backfill provenance and apply the conservative apus-sft-v1 admission gate.

The input contract is an intermediate structural export. This command never edits
the immutable source archive. It joins source-row metadata by the fixed repo,
revision and row number, writes an annotated audit stream, and then emits only
diagnostic candidates. This audit cannot grant training admission.
"""

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

ALLOWED_TEACHERS = {"qwen38", "fable", "gpt56"}
ALLOWED_DOMAINS = {"code", "reasoning", "office", "data", "translation", "writing", "general"}


def json_load(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def iter_rows(path):
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(path).iter_batches(batch_size=256):
            yield from batch.to_pylist()
        return
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def teacher_family(value):
    if not isinstance(value, str):
        return "unknown"
    text = value.lower()
    matches = []
    for family, patterns in {
        "qwen38": (r"qwen[-_ ]?3\.8",),
        "fable": (r"fable(?:[-_ ]?5(?:\.\d+)?)?",),
        "gpt56": (r"gpt[-_ ]?5\.6",),
        "gemini31": (r"gemini[-_ ]?3\.1",),
    }.items():
        if any(re.search(pattern, text) for pattern in patterns):
            matches.append(family)
    return matches[0] if len(matches) == 1 else "unknown"


def readme_meta(path):
    readme = path.parent / "README.md"
    if not readme.exists():
        readme = path.parent.parent / "README.md"
    result = {"license": None, "language": None}
    if not readme.exists():
        return result
    lines = readme.read_text(errors="replace").splitlines()
    for index, line in enumerate(lines[:80]):
        if re.match(r"^license:\s*", line):
            result["license"] = line.split(":", 1)[1].strip() or None
        if re.match(r"^language:\s*", line):
            for item in lines[index + 1 : index + 6]:
                match = re.match(r"^\s*-\s*([a-zA-Z-]+)\s*$", item)
                if match:
                    result["language"] = match.group(1).lower()
                    break
    return result


def source_meta(config):
    by_key = {}
    source_counts = collections.Counter()
    for source in config["sources"]:
        path = Path(source["path"])
        if sha256(path) != source["sha256"]:
            raise ValueError(f"source hash mismatch: {source['repo']}")
        readme = readme_meta(path)
        catalog_license = source.get("license") or readme["license"]
        catalog_language = source.get("language") or readme["language"]
        for row, raw in enumerate(iter_rows(path)):
            source_counts[source["repo"]] += 1
            model = raw.get("teacher_model") or raw.get("model")
            claims = [model] if isinstance(model, str) and model else []
            raw_messages = raw.get("messages")
            if isinstance(raw_messages, str):
                try:
                    raw_messages = json.loads(raw_messages)
                except json.JSONDecodeError:
                    raw_messages = None
            explicit_reasoning = raw.get("reasoning") or raw.get("reasoning_content")
            thinking_markup = False
            if isinstance(raw_messages, list):
                thinking_markup = any(
                    isinstance(message, dict)
                    and isinstance(message.get("content"), str)
                    and "<think>" in message["content"]
                    for message in raw_messages
                )
                explicit_reasoning = explicit_reasoning or any(
                    isinstance(message, dict) and message.get("reasoning_content") for message in raw_messages
                )
            source_split = raw.get("source_split") or raw.get("split")
            if source_split is None:
                source_split = "train" if "/train" in str(path) else None
            language = raw.get("language") or raw.get("lang")
            # P01's `lang` is a programming language; use the explicit README
            # language instead of mislabeling `python`, `asm`, etc. as human text.
            if source["repo"] == "greghavens/gpt-5.6-sol-coding-and-debugging-traces":
                language = catalog_language or "en"
            elif (
                not isinstance(language, str)
                or len(language) > 5
                or language.lower() not in {"en", "zh", "ja", "ko", "ru"}
            ):
                language = catalog_language
            by_key[(source["repo"], source["revision"], row)] = {
                "source_file": str(Path(*path.parts[path.parts.index("sources") + 2 :])),
                "source_split": source_split,
                "source_record_id": raw.get("id") or raw.get("session_id") or raw.get("source_row_hash"),
                "source_task_id": raw.get("source_trajectory_id") or raw.get("task_id") or raw.get("session_id"),
                "source_license": catalog_license,
                "language": language.lower() if isinstance(language, str) else None,
                "teacher_model": model,
                "teacher_claims": claims,
                "teacher_attested": isinstance(model, str) and bool(model),
                "reasoning_present": bool(explicit_reasoning) or thinking_markup,
                "thinking_markup": thinking_markup,
            }
    return by_key, source_counts


def tool_errors(messages, target_ids):
    pending = set()
    origins = {}
    errors = []
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                call_id = call.get("id")
                if not call_id:
                    errors.append("missing_tool_call_id")
                else:
                    pending.add(call_id)
                    origins[call_id] = message.get("message_id")
        elif message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if not call_id or call_id not in pending:
                errors.append("orphan_tool_result")
            else:
                pending.remove(call_id)
    if any(origins.get(call_id) not in target_ids for call_id in pending):
        errors.append("missing_tool_result")
    return sorted(set(errors))


def script_conflict(messages):
    text = "\n".join(str(message.get(key) or "") for message in messages for key in ("content", "reasoning_content"))
    size = max(len(text), 1)
    ratios = {
        "cyrillic": sum("\u0400" <= char <= "\u052f" for char in text) / size,
        "cjk": sum("\u4e00" <= char <= "\u9fff" for char in text) / size,
        "arabic": sum("\u0600" <= char <= "\u06ff" for char in text) / size,
    }
    name, ratio = max(ratios.items(), key=lambda item: item[1])
    return name if ratio >= 0.02 else None


def annotate(record, meta):
    flags = set(record.get("quality_flags", [])) - {
        "reasoning_policy_unresolved",
        "teacher_identity_unresolved",
        "language_unresolved",
        "source_split_unresolved",
        "source_license_unresolved",
    }
    observations = []
    if meta is None:
        flags.add("source_row_not_found")
        meta = {}
    for key in (
        "source_file",
        "source_split",
        "source_record_id",
        "source_task_id",
        "source_license",
        "language",
    ):
        if meta.get(key) is not None:
            record[key] = meta[key]
    if record.get("teacher_model") is None and meta.get("teacher_model"):
        record["teacher_model"] = meta["teacher_model"]
    claims = []
    try:
        evidence = json.loads(record.get("teacher_evidence_json") or "{}")
        claims.extend(item.get("value") for item in evidence.get("claims", []) if item.get("value"))
    except (TypeError, json.JSONDecodeError):
        flags.add("teacher_evidence_json_invalid")
    claims.extend(meta.get("teacher_claims", []))
    families = {teacher_family(value) for value in claims if value}
    family = teacher_family(record.get("teacher_model"))
    if len(families) > 1 or (family != "unknown" and families and family not in families):
        flags.add("teacher_identity_conflict")
    if family not in ALLOWED_TEACHERS:
        flags.add("teacher_not_allowed")
    else:
        record["teacher_family"] = family
    if not meta.get("teacher_attested"):
        flags.add("teacher_identity_unresolved")
    else:
        record["teacher_evidence_json"] = json.dumps(
            {
                "status": "row_claim",
                "original": json.loads(record.get("teacher_evidence_json") or "{}"),
                "source_row_model": meta.get("teacher_model"),
                "fixed_revision": record.get("source_revision"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    if record.get("language") in (None, "unknown"):
        flags.add("language_unresolved")
    elif record["language"] == "ru":
        flags.add("excluded_russian")
    if record.get("source_license") is None:
        flags.add("source_license_unresolved")
    if record.get("source_split") not in {"train", "training"}:
        flags.add("source_split_not_train")
    conflict = script_conflict(record.get("messages", []))
    if conflict:
        flags.add(f"language_content_conflict:{conflict}")
    if meta.get("thinking_markup"):
        observations.append("thinking_markup_present")
        flags.add("thinking_markup_mask_review")
    elif record["supervision"].get("reasoning_policy") == "unresolved":
        record["supervision"]["reasoning_policy"] = "unresolved"
        flags.add("reasoning_policy_unresolved")
        observations.append("no_explicit_reasoning")
    try:
        messages = record["messages"]
        targets = set(record["supervision"]["message_ids"])
        valid_ids = {message["message_id"] for message in messages if message.get("role") == "assistant"}
        if not targets or not targets.issubset(valid_ids):
            flags.add("invalid_supervision_targets")
        flags.update(tool_errors(messages, targets))
        json.loads(record["tools_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        flags.add("contract_structure_invalid")
    flags.update(
        {
            "language_detection_pending",
            "semantic_quality_pending",
            "contamination_audit_pending",
            "tokenizer_mask_pending",
            "teacher_provenance_review_pending",
        }
    )
    record["quality_flags"] = sorted(flags)
    record["provenance_json"] = json.dumps(
        {
            **json.loads(record.get("provenance_json") or "{}"),
            "quality_gate": "repair-and-gate-v1",
            "source_row_join": "repo+fixed_revision+source_row",
            "observations": sorted(set(observations)),
            "source_language_claim": meta.get("language"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    record["quality_status"] = "unreviewed"
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads(args.config.read_text())
    metadata, source_counts = source_meta(config)
    annotated = output / "annotated.jsonl"
    counts = collections.Counter()
    group_splits = collections.defaultdict(set)
    content_seen = set()
    with args.contract.open() as src, annotated.open("w") as dst:
        for line in src:
            raw_record = json.loads(line)
            record = annotate(
                raw_record,
                metadata.get((raw_record["source_repo"], raw_record["source_revision"], raw_record["source_row"])),
            )
            group_splits[record["task_group_id"]].add(record["split"])
            duplicate = record["content_sha256"] in content_seen
            content_seen.add(record["content_sha256"])
            if duplicate:
                record["quality_flags"].append("exact_content_duplicate")
            dst.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts["input"] += 1
    ready = output / "provisional_candidates.jsonl"
    quarantine = output / "quarantine.jsonl"
    reasons = collections.Counter()
    domains = collections.Counter()
    teachers = collections.Counter()
    with annotated.open() as src, ready.open("w") as good, quarantine.open("w") as bad:
        for line in src:
            record = json.loads(line)
            flags = set(record.get("quality_flags", []))
            if len(group_splits[record["task_group_id"]]) > 1:
                flags.add("task_group_cross_split")
            if record["split"] != "train":
                flags.add("not_training_split")
            hard_flags = {
                "source_row_not_found",
                "teacher_evidence_json_invalid",
                "teacher_identity_conflict",
                "teacher_not_allowed",
                "teacher_identity_unresolved",
                "language_unresolved",
                "excluded_russian",
                "source_license_unresolved",
                "source_split_not_train",
                "not_training_split",
                "reasoning_policy_unresolved",
                "invalid_supervision_targets",
                "contract_structure_invalid",
                "missing_tool_call_id",
                "orphan_tool_result",
                "missing_tool_result",
                "exact_content_duplicate",
                "task_group_cross_split",
            }
            hard_hit = flags & hard_flags or any(flag.startswith("language_content_conflict:") for flag in flags)
            if hard_hit:
                record["quality_status"] = "quarantined"
                record["quality_flags"] = sorted(flags)
                bad.write(json.dumps(record, ensure_ascii=False) + "\n")
                counts["quarantine"] += 1
                reasons.update(flags)
            else:
                record["quality_status"] = "structurally_screened"
                good.write(json.dumps(record, ensure_ascii=False) + "\n")
                counts["provisional_candidates"] += 1
                domains[record["domain"]] += 1
                teachers[record["teacher_family"]] += 1
    manifest = {
        "schema_version": "apus-sft-v1",
        "status": "diagnostic_audit_only",
        "training_ready": False,
        "approved_rows": 0,
        "counts": dict(counts),
        "source_row_metadata": sum(source_counts.values()),
        "source_counts": dict(source_counts),
        "candidate_domains": dict(domains),
        "candidate_teachers": dict(teachers),
        "quarantine_reasons": dict(reasons),
        "task_groups": len(group_splits),
        "task_groups_cross_split": sum(len(splits) > 1 for splits in group_splits.values()),
        "training_policy": {
            "allowed_teachers": sorted(ALLOWED_TEACHERS),
            "language": "Russian excluded; other languages require row-level assessment",
            "source_split": "train only",
            "unknown_or_conflicting_teacher": "quarantine",
            "exact_duplicate": "quarantine",
            "unresolved_reasoning": "unresolved remains blocked; markup preservation needs tokenizer/mask verification",
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
