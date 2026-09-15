# Incremental LoRA synchronization design

Status: proposal only; no product implementation. Baseline is the paired VERL `a9f2985`. Keep current merged full-weight synchronization until this alternative passes publication and failure tests.

## Goal and meaning of incremental

Train LoRA in the existing Uni-Agent → Gateway → TQ → VERL flow, transfer the frozen base once, then transfer a complete **adapter checkpoint only** per publication. This is incremental relative to full model weights; it is not a numerical delta between adapter checkpoints. Sending complete adapters avoids accumulated rounding drift and makes retries/idempotency simpler. Teacher scoring and Harbor/Modal task execution are unchanged.

## Verified source constraints

- `verl/workers/engine_workers.py:update_weights`: non-naive export currently discards `peft_config` and defaults `base_sync_done=False`.
- `verl/workers/engine/fsdp/transformer_impl.py:get_per_tensor_param`: `merge=False, base_sync_done=True` exports adapters, whereas false exports the base. `utils/fsdp_utils.py:collect_lora_params` explicitly filters LoRA keys in the latter branch.
- `verl/checkpoint_engine/base.py:CheckpointEngineWorker.update_weights` forwards weights, global step and wire format but no PEFT/base-ready envelope.
- `CheckpointEngineRegistry` plus `checkpoint_engine.custom_backend_module` permit registered transport extensions. They do **not** currently control the trainer's export flags, discarded PEFT metadata, or fixed checkpoint-worker call signature. A transport plugin alone therefore cannot fix this gap cleanly.
- The manager pauses/aborts requests, releases KV cache, builds collective transport, awaits sender and receivers, finalizes, then restores cache and resumes requests. It has no complete transaction rollback protocol for partially installed adapters.
- `vllm_rollout/utils.py:update_weights_from_ipc` already accepts PEFT config, clones adapter tensors across reused buffers, collects every bucket, and installs only on `is_last`. However, it removes the previous adapter **before receipt**. A failed transfer can leave no adapter installed.
- Adapter identity is currently constant (`VLLM_LORA_INT_ID=123`). The asynchronous server selects that ID only if installed; otherwise adapter mode can issue a request with no adapter. Resume after an incomplete publication must therefore fail closed.
- `vllm_rollout.py:update_weights` clears KV cache and updates global step after the worker receiver completes, but different replicas may finish at different times. Keep the global admission barrier until all target ranks acknowledge.

## Architecture and ownership

```mermaid
sequenceDiagram
    participant U as Uni-Agent recipe
    participant T as VERL trainer/export
    participant C as Checkpoint coordinator
    participant R as vLLM rollout ranks
    U->>T: enable explicit adapter-sync contract
    C->>R: close admission; abort/preserve partial requests
    T->>C: immutable publication envelope
    C->>R: verify base/revision and envelope
    T->>R: NCCL adapter tensors
    R->>C: staged tensor manifest acknowledgement
    C->>R: install while admission remains closed
    R->>C: installation acknowledgement
    C->>R: clear caches; commit publication version
    C->>R: resume only after all ranks committed
```

Uni-Agent should own opt-in recipe selection, immutable artifact identities, publication evidence and end-to-end tests. Weight export and collective installation belong to VERL because its engine owns sharded parameters and rollout workers. The minimum clean implementation requires a **small pinned VERL overlay/upstream change**, not bypassing the trainer from a Uni-Agent rollout adapter.

Do not mutate the submodule implicitly from an import hook. Record a separate overlay commit and paired dependency SHA; submit generic envelope/export changes upstream where feasible. A later registered transport may implement adapter-specific bulk transfer once export and receiver hooks exist.

## Proposed contract

A bounded, canonical control-plane envelope should carry:

- schema/version, publication ID and trainer global step;
- payload kind (`base` or `adapter`), previous committed publication ID;
- fixed base model/revision/weight identity and tokenizer identity;
- PEFT config: rank, alpha, target modules, adapter type and dtype;
- ordered tensor manifest (names, shapes, dtypes, byte lengths; optional content hashes for diagnostic mode);
- expected target replica/rank topology and total payload bytes;
- complete adapter identity, never credentials or dataset-provided settings.

Control metadata must be visible to sender and every receiver before NCCL transfer. Do not mix arbitrary object serialization into tensor buckets. All ranks must agree on the same manifest and invocation order before entering collectives, otherwise one rejected receiver can strand peers inside NCCL.

### Initial base

1. Every receiver reports whether it loaded the exact frozen base artifact. Treat `load_format=dummy`, changed checkpoint base identity, or process restart without verified base identity as uninitialized.
2. If needed, export **unmerged base** once (`base_sync_done=False`) and verify installation on all ranks.
3. Export and install the initial adapter as a separate adapter publication. Resume from training checkpoint must publish its restored adapter before any rollout.
4. Maintain base readiness per receiver process / replica identity, not one trainer-global boolean. Newly added/restarted replicas require base and current adapter synchronization.

Never apply adapters on top of previously merged weights. Switching between the existing merged recipe and adapter recipe requires reloading the frozen unmerged base explicitly.

### Steady-state publication

Export `merge=False, base_sync_done=True` with the complete PEFT configuration. Reuse the existing bucket transport and receiver's cloned whole-adapter collection. Verify all expected tensors are present before installation; reject duplicates, missing tensors, incompatible rank or a different base identity.

Minimum safe receiver behavior can retain the constant adapter ID if admission stays closed throughout replacement and any failed install stops the run. This is simpler than pretending atomic rollback exists. A more robust second step stages versioned adapter IDs, commits an active-ID pointer only after all ranks succeed, then retires old adapters. Versioned IDs also require changing the server's current constant-ID lookup and capacity management; they are not a one-line parameter change.

Cache invalidation and `set_global_steps` occur only after successful installation. The coordinator resumes request admission only after every target rank/replica acknowledged the same committed publication. Partial rollouts may span old/new versions as today; Gateway must retain actual min/max version evidence. Do not relabel old generated tokens as new.

### Failure handling

- Preflight/config rejection: stop before collective launch; preserve old serving state.
- Transfer timeout, corrupt manifest, one-rank failure: keep all target replicas paused; fail the publication, bound/cancel outstanding RPCs, finalize or tear down the communication group, and mark the job failed.
- Installation failure after removing an old adapter: never resume base-only inference. First version requires restart/reload of known-good base+adapter to recover; do not claim automatic rollback.
- Retry identical committed publication: return an idempotent receipt only when base/adapter identity and target topology match. Same step with different tensor identity is a conflict.
- Receiver restart mid-publication: its old acknowledgement is invalid; rediscover process identity and bootstrap again.

A bounded timeout on Python RPC is not proof that an in-flight CUDA collective terminated. Recovery tests must check owned process-group and GPU worker state before declaring cleanup complete.

## Minimal file changes if approved

| Area | Change |
|---|---|
| VERL worker config | Explicit adapter-sync mode and bounded envelope schema |
| `engine_workers.py` | Export base/adapter with correct flags; preserve PEFT metadata |
| `checkpoint_engine/base.py` | Publication envelope, all-rank preflight/commit barrier, bounded failure lifecycle |
| vLLM receiver/server | Stage complete adapters, no uncommitted fallback to base, publication-aware install/cache/version |
| Uni-Agent recipe | Opt in only to validated paired overlay; preserve current merged fallback |
| Tests/evidence | CPU contracts, two-GPU publication/reload, multi-rank failure injection |

Do not expand Harbor executor, Gateway message format, Teacher API, or TQ loss fields for this work.

## Acceptance tests

CPU tests must exercise actual export calls (base versus adapter flags), schema validation, complete bucket assembly/cloning, idempotency and coordinator acknowledgement ordering. Reject missing rank acknowledgements and ensure no resume/cache-version advancement occurs on failed transfer/install. Include a regression for the current remove-old-before-receive failure window.

Two-GPU minimum: one actor and one standalone rollout, fixed small supported Student, native separate_async RL. Verify LoRA parameter change, adapter-only transfer after bootstrap, unchanged frozen base identity, and changed fixed-prefix rollout logprobs matching independently loaded base+adapter. Record transferred bytes: steady payload should scale with adapter tensors, not model parameter count. Repeat at least two adapter publications to catch replacement/accumulation defects, then restart and publish the checkpointed adapter before generation.

Multi-rank extension: at least two rollout TP ranks plus actor resources; inject one receiver failure and prove all replicas remain paused until explicit recovery. Two GPUs with TP=1 do not establish correctness of this case.

OPD is orthogonal: after publication correctness passes, add the existing frozen Teacher role and run the same checks with the native hybrid loss. Current three-role separate_async hybrid requires at least three role-assigned GPUs; memory capacity remains model/context dependent.

Performance claims require measured full-weight baseline versus adapter-only bytes, synchronization wall time and rollout throughput at the same model/context/workload. Keep merged full-weight sync as the default until correctness, restart and failure behavior pass.
