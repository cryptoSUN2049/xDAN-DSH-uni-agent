import collections
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path("/workspace/apus-data-cleaning")
V1 = ROOT / "recovery/collection-v1/raw/saidutta69/fable-5-premium/da2c4f99761490b6e2d38b52843a1a57356dbd0b/openai_chat"
V2 = ROOT / "apus-source-archive-v1/sources/U03/openai_chat/train.parquet"


def rows(path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=64):
        yield from batch.to_pylist()


def content_hash(row):
    value = row["messages"]
    if isinstance(value, str):
        value = json.loads(value)
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


lookup = collections.defaultdict(list)
for split in ["train", "validation", "test"]:
    for i, row in enumerate(rows(V1 / (split + ".parquet"))):
        key = row.get("source_row_hash")
        if key:
            lookup[key].append(
                {
                    "split": split,
                    "row": i,
                    "model": row.get("model"),
                    "content_sha256": content_hash(row),
                }
            )
counts = collections.Counter()
models = collections.Counter()
splits = collections.Counter()
matched_fable = collections.Counter()
evidence = []
for i, row in enumerate(rows(V2)):
    if row.get("source") != "base_v1":
        continue
    counts["v2_base_rows"] += 1
    candidates = lookup.get(row.get("source_row_hash"), [])
    exact = [r for r in candidates if r["content_sha256"] == content_hash(row)]
    if not candidates:
        counts["source_hash_unmatched"] += 1
    elif not exact:
        counts["source_hash_matched_content_changed"] += 1
    else:
        counts["exact_content_and_source_hash_match"] += 1
        identities = {(r["split"], r["model"]) for r in exact}
        if len(identities) == 1:
            split, model = next(iter(identities))
            splits[split] += 1
            models[str(model)] += 1
            if model == "claude-fable-5":
                matched_fable[split] += 1
            evidence.append(
                {
                    "v2_train_row": i,
                    "v1_matches": exact,
                    "v2_model": row.get("model"),
                    "provenance_status": "exact_content_and_source_key_match_not_teacher_authentication",
                }
            )
        else:
            counts["ambiguous_lineage"] += 1
assert (
    counts["v2_base_rows"]
    == counts["source_hash_unmatched"]
    + counts["source_hash_matched_content_changed"]
    + counts["exact_content_and_source_hash_match"]
)
report = {
    "counts": dict(counts),
    "v1_original_splits": dict(splits),
    "v1_model_claims": dict(models),
    "fable_original_splits": dict(matched_fable),
    "evidence": evidence,
    "training_admission": False,
}
(ROOT / "recovery/premium-lineage-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "evidence"}, ensure_ascii=False, indent=2))
