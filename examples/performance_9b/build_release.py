"""Build traceable, structurally screened pools; never imply execution verification."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from examples.performance_9b.normalize import normalize_record
from examples.performance_9b.quality import classify_teacher, inspect_record


def prompt_digest(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().lower().encode()).hexdigest()


def iter_rows(path):
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        for batch in pq.ParquetFile(path).iter_batches(batch_size=128):
            yield from batch.to_pylist()
    else:
        with path.open() as stream:
            for line in stream:
                try:
                    yield json.loads(line)
                except ValueError:
                    yield {"_invalid_json": True}


def select_groups(groups, quotas, seed=20260924):
    """Return no selection at all when any quota cannot be met."""
    buckets = defaultdict(list)
    for key, info in groups.items():
        if info["split"] == "train" and info["domain"] in quotas:
            if info["domain"] != "general" or info["teachers"] <= {"fable", "gpt56"}:
                buckets[info["domain"]].append(key)
    deficits = {d: n - len(buckets[d]) for d, n in quotas.items() if len(buckets[d]) < n}
    if deficits:
        return set(), deficits
    selected = set()
    for domain, count in quotas.items():
        ordered = sorted(buckets[domain], key=lambda k: hashlib.sha256(f"{seed}:{k}".encode()).hexdigest())
        selected.update(ordered[:count])
    return selected, {}


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TaskGroups:
    """Join source task identities and exact cross-source prompts transitively."""

    def __init__(self):
        self.parents = {}
        self.source_prompts = {}

    def find(self, prompt):
        self.parents.setdefault(prompt, prompt)
        root = prompt
        while self.parents[root] != root:
            root = self.parents[root]
        while self.parents[prompt] != prompt:
            parent = self.parents[prompt]
            self.parents[prompt] = root
            prompt = parent
        return root

    def add(self, source_task, prompt):
        previous = self.source_prompts.setdefault(source_task, prompt)
        left, right = self.find(previous), self.find(prompt)
        # Canonical identity is independent of row/source iteration order.
        self.parents[max(left, right)] = min(left, right)


def finalize_groups(output, blocked, stats, identities):
    """Resolve complete task components before splitting or propagating exclusions."""
    blocked = {identities.find(group) for group in blocked}
    mappings = {}
    for name in ("screened", "three_teacher"):
        path = output / f"{name}.jsonl"
        temporary = output / f"{name}.tmp"
        groups = {}
        with path.open() as src, temporary.open("w") as dst:
            for line in src:
                record = json.loads(line)
                group = identities.find(record["release_task_group"])
                record["release_task_group"] = group
                record["split"] = "dev" if int(group[:8], 16) % 20 == 0 else "train"
                if group in blocked:
                    if name == "screened":
                        item = stats[record["source_repo"]]
                        item["counts"]["screened"] -= 1
                        item["counts"]["excluded"] = item["counts"].get("excluded", 0) + 1
                        item["reasons"]["blocked_task_group"] = item["reasons"].get("blocked_task_group", 0) + 1
                        item["screened_domains"][record["domain"]] -= 1
                        item["screened_teachers"][record["teacher_family"]] -= 1
                    continue
                dst.write(json.dumps(record, ensure_ascii=False) + "\n")
                info = groups.setdefault(
                    group, {"domain": record["domain"], "split": record["split"], "teachers": set()}
                )
                info["teachers"].add(record["teacher_family"])
                if info["domain"] != record["domain"]:
                    info["domain"] = "unknown"
        temporary.replace(path)
        mappings[name] = groups
    path = output / "decisions.jsonl"
    temporary = output / "decisions.tmp"
    with path.open() as src, temporary.open("w") as dst:
        for line in src:
            row = json.loads(line)
            if row.get("task_group") is not None:
                row["task_group"] = identities.find(row["task_group"])
            if row["status"] == "screened" and row.get("task_group") in blocked:
                row.update(status="excluded", reasons=["blocked_task_group"])
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)
    return mappings


def build(config, output):
    from examples.performance_9b.policy import ability_domain, policy_flags

    output.mkdir(parents=True, exist_ok=False)
    known_tests = set(config.get("benchmark_prompt_hashes", []))
    identities = TaskGroups()
    groups, three_groups, seen, stats, receipts, blocked = {}, {}, set(), {}, [], set()
    pools = {name: (output / f"{name}.jsonl").open("w") for name in ("screened", "three_teacher", "decisions")}
    try:
        for source in config["sources"]:
            path = Path(source["path"])
            digest = file_hash(path)
            if source.get("sha256") and digest != source["sha256"]:
                raise ValueError(f"source hash mismatch: {source['repo']}")
            counts, reasons, domains, teachers = Counter(), Counter(), Counter(), Counter()
            for index, raw in enumerate(iter_rows(path)):
                counts["input_rows"] += 1
                decision = {"source_repo": source["repo"], "revision": source["revision"], "row": index}
                try:
                    record = normalize_record(
                        raw, source["repo"], source["revision"], index, source.get("teacher_hint")
                    )
                    flags = sorted(set(inspect_record(record) + policy_flags(raw, record, source["repo"])))
                    flags += source.get("review_flags", [])
                    first = next(m.get("content", "") for m in record["messages"] if m["role"] == "user")
                    if not isinstance(first, str):
                        flags.append("nontext_prompt_review")
                    elif prompt_digest(first) in known_tests:
                        flags.append("known_benchmark_test_prompt")
                    if index in source.get("manual_quarantine_rows", []):
                        flags.append("manual_quality_review")
                    family = classify_teacher(record["teacher_claimed"])
                    record["teacher_family"] = family
                    record["domain"] = ability_domain(raw, source["repo"])
                    record["source_domain"] = raw.get("domain")
                    record["provenance"] = {
                        k: raw[k]
                        for k in ("source", "source_repository", "source_license", "source_split", "kind", "category")
                        if k in raw
                    }
                    record["source_file_sha256"] = digest
                    record["quality_status"] = "structurally_screened_not_execution_verified"
                    # Register all normalized rows, including excluded siblings.
                    # Final components and splits are resolved after every source is read.
                    identities.add(record["task_group"], record["prompt_hash"])
                    group = record["prompt_hash"]
                    decision["task_group"] = group
                    record["release_task_group"] = group
                    record["split"] = "dev" if int(group[:8], 16) % 20 == 0 else "train"
                    if flags:
                        status = "quarantine"
                        if any(
                            f in flags
                            for f in (
                                "excluded_gemini31",
                                "heldout_source",
                                "benchmark_source",
                                "known_benchmark_test_prompt",
                            )
                        ):
                            status = "excluded"
                            blocked.add(group)
                    elif record["content_hash"] in seen:
                        status, flags = "duplicate", ["exact_content_duplicate"]
                    else:
                        status = "screened"
                        seen.add(record["content_hash"])
                        line = json.dumps(record, ensure_ascii=False) + "\n"
                        pools["screened"].write(line)
                        info = groups.setdefault(
                            group, {"domain": record["domain"], "split": record["split"], "teachers": set()}
                        )
                        info["teachers"].add(family)
                        if info["domain"] != record["domain"]:
                            info["domain"] = "unknown"
                        if family in {"qwen38", "fable", "gpt56"}:
                            pools["three_teacher"].write(line)
                            sub = three_groups.setdefault(
                                group, {"domain": record["domain"], "split": record["split"], "teachers": set()}
                            )
                            sub["teachers"].add(family)
                            if sub["domain"] != record["domain"]:
                                sub["domain"] = "unknown"
                        domains[record["domain"]] += 1
                        teachers[family] += 1
                    decision.update({"status": status, "reasons": sorted(set(flags)), "record_id": record["id"]})
                except (ValueError, TypeError, KeyError, StopIteration) as exc:
                    status, flags = "quarantine", [f"normalization_error:{str(exc)[:160]}"]
                    decision.update({"status": status, "reasons": flags})
                counts[status] += 1
                reasons.update(flags)
                pools["decisions"].write(json.dumps(decision, ensure_ascii=False) + "\n")
            assert counts["input_rows"] == sum(counts[k] for k in ("screened", "quarantine", "excluded", "duplicate"))
            stats[source["repo"]] = {
                "counts": dict(counts),
                "reasons": dict(reasons),
                "screened_domains": dict(domains),
                "screened_teachers": dict(teachers),
            }
            receipts.append({**source, "sha256": digest, "bytes": path.stat().st_size})
    finally:
        for stream in pools.values():
            stream.close()
    mappings = finalize_groups(output, blocked, stats, identities)
    groups, three_groups = mappings["screened"], mappings["three_teacher"]
    sampling = {}
    for name, group_map in (("screened", groups), ("three_teacher", three_groups)):
        selection, deficits = select_groups(group_map, config["quotas"])
        sampling[name] = {
            "unique_prompt_groups": len(group_map),
            "group_domains": dict(Counter(g["domain"] for g in group_map.values())),
            "quota_deficits": deficits,
            "selected_groups": len(selection),
        }
        if selection:
            with (output / f"{name}-20k.jsonl").open("w") as dst, (output / f"{name}.jsonl").open() as src:
                for line in src:
                    if json.loads(line)["release_task_group"] in selection:
                        dst.write(line)
    manifest = {
        "schema_version": 1,
        "status": "screened_candidates_not_training_ready",
        "sources": receipts,
        "statistics": stats,
        "sampling": sampling,
        "quotas": config["quotas"],
        "limitations": [
            "Source task IDs and exact prompts define components; semantic overlap not fully audited",
            "Publisher/row teacher claims are retained, not independently authenticated",
            "Correctness, tokenizer masks, template and supervised-token budgets still require validation",
            "Cyrillic language heuristic quarantines for review; not a full Russian language classifier",
        ],
        "files": {p.name: {"bytes": p.stat().st_size, "sha256": file_hash(p)} for p in output.glob("*.jsonl")},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (output / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(json.loads(args.config.read_text()), args.output)
    print(json.dumps(result["sampling"], ensure_ascii=False, indent=2))
