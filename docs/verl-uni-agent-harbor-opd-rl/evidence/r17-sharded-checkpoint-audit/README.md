# R17 C1 → C2 native two-rank checkpoint audit

The actual audit passed after adding explicit support for the native DTensor checkpoint format. The first failed report is preserved: the original checker recognized ShardedTensor but rejected the actual DTensor subclass. This was an audit format limitation, not evidence of invalid weights.

`r17-c1-c2-checkpoint-summary.json` contains the result, all twelve checkpoint file identities, source hashes and per-rank optimizer details. The full original 4,894,561-byte report is preserved losslessly in `r17-c1-c2-checkpoint-audit-v2.json.gz` (67,691 bytes); decompressing it produces SHA256 `9bc05301a4ca1c3e039ef101246104e09cb9f4822177e4f7617df77275a17760`.

- Both ranks: native DTensor, logical CUDA mesh `[0,1]` / `fsdp`, placement `Shard(0)`. Exact original-dtype comparison used ordinary CPU local tensors; CUDA remained uninitialized.
- 760 base tensors: all finite and exactly unchanged. 716 adapter tensors: all finite, 493 changed. Complete nonoverlapping shard coverage and rank ownership were validated.
- Each rank: optimizer step 1 → 2, 716 active states, 60 empty states. Nonzero moment tensors increased from 496 to 992; 992 moment tensors changed. The original strict optimizer checker was unchanged.
- Owned audit processes exited; no GPU process or frozen training source was modified.

`dtensor-fixture-status.json` and `dtensor-fixture-green.log` preserve 17 cloud CPU tests, including native two-rank save/load, base/NaN rejection and unsupported Partial/Replicate/Shard(1) rejection. Combined parent/child coverage is 89.88%. Type inspection logs identify the actual model and optimizer layouts. Readiness evidence records two stable stat snapshots and available CPU memory.

This proves the selected checkpoint pair contains a real parameter update with strict optimizer advancement. Receipt/batch correspondence, nonzero training gradient, observability, checkpoint restoration and model capability are separate claims; the world2 acceptance operator combines the first three with this report.
