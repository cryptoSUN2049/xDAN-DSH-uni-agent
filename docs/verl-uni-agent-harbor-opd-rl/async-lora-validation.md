# Native asynchronous LoRA update → rollout → reload validation

Audit target: Uni-Agent worktree paired with VERL `a9f2985`; CPU dependency checks do not substitute for the pinned GPU environment. Goal: show that an optimizer update changes the policy actually used by subsequent Student rollout.

## Confirmed blocker and minimal recipe correction

The original recipe enabled LoRA rank 16 but inherited `actor_rollout_ref.model.lora.merge=False`. All three recipe modes use the NCCL checkpoint engine.

In `verl/workers/engine_workers.py:update_weights`, the non-naive branch calls `actor.engine.get_per_tensor_param()` with its default `base_sync_done=False`, discards the returned PEFT config, and sends named tensors. FSDP `get_per_tensor_param` in unmerged LoRA mode calls `collect_lora_params`; with that flag false, the implementation explicitly filters `lora_` keys from the unmerged base state. `CheckpointEngineWorker.update_weights` passes no PEFT config to the rollout receiver. Thus this route cannot install the newly optimized adapters through vLLM's separate `add_lora` path.

**Correction implemented:** shared recipe sets `actor_rollout_ref.model.lora.merge=true`. The FSDP engine then exports `_merged_lora_per_tensor_param()` and returns no PEFT config, matching the existing named-tensor receiver. The merge context remains open while weights are materialized, and restores unmerged training weights afterward. LoRA remains the trainable parameterization; **every synchronization transmits merged full weights**. This is not incremental adapter synchronization and has full-weight bandwidth/materialization costs.

`colocate_async` is also affected when configured with NCCL: its end-of-step hook uses the same checkpoint manager. Therefore the correction belongs in shared `base.yaml`, not only `rl.yaml` / `hybrid.yaml`. No upstream code was changed. Three native Hydra composition regression tests failed before the change and now require merge=true together with LoRA rank/alpha for each mode.

## What the native path actually does

- `trainer_separate_async.py:on_init_end` synchronizes loaded weights to standalone and hybrid rollout replicas before training.
- The separate trainer requires `data.train_batch_size == parameter_sync_step * actor.ppo_mini_batch_size`. Current recipe satisfies `2 == 2 * 1`.
- On publication, the standalone checkpoint manager sends the actor's committed weights. vLLM `update_weights` awaits its receiver, clears KV cache, and only then updates its reported global step.
- `on_init_end` runs after checkpoint load, so a resumed actor should be published before new rollout. Checkpoint files live under `global_step_<n>/actor`; resume points to the **global-step directory**, not a bare adapter file.
- FSDP checkpoint manager saves/restores actor weights, optimizer and extra state, and records LoRA training metadata. The current recipe explicitly saves all three components and initially disables resume.
- Version tags alone are insufficient proof of changed weights: before the correction, a base-only synchronization could still increment the reported step. Verify numerical policy change as well as tags.

## GPU and model boundaries

| Experiment | Minimum role allocation | What it proves |
|---|---|---|
| `--mode rl` | 1 actor GPU + 1 standalone rollout GPU | separate_async LoRA update/publication/reload without Teacher |
| `--mode opd` | 1 colocated actor/rollout GPU + 1 Teacher GPU | OPD, but actor and rollout alternate ownership |
| `--mode hybrid` | 1 actor GPU + 1 standalone rollout GPU + 1 Teacher GPU | actual separate_async task reward + OPD |

Two physical GPUs cannot run the current three-role hybrid recipe by changing advertised Ray GPU counts. Start with a **locally available, fixed-revision small Student** already supported by the installed vLLM/Transformers pair (for example the project's existing Qwen3-4B snapshot if it is present). Validate model path, tokenizer/tool parser, base-file hashes and LoRA targets first. Do not infer 9B/27B memory fitness from role counts: long-context activations, merged-weight buffers, KV cache and optimizer state still require measurement. A 27B Teacher is unnecessary for the first publication test.

GPU acceptance must record the exact dependency lane: the Uni-Agent test lane uses vLLM 0.23.0/Ray 2.54.1, while the paired VERL uv.lock uses vLLM 0.24/Torch 2.11/Transformers 5.9 for its FSDP+vLLM environment. Record Python, CUDA/driver/NCCL, all actual versions, paired commits and checkpoint engine; do not claim the two lanes are one lock. Current local CPU evidence uses Torch 2.14.0.

## Minimal launch and resume commands

These commands are templates for an operator-prepared, registered run and **were not executed on GPUs during this audit**. `launch.json`, train/heldout task files, worker/controller and credentials must already be valid. Model and tool-parser values must match that preparation.

```bash
export STUDENT_MODEL_PATH=/workspace/models/fixed-student-snapshot
export TOOL_PARSER=hermes
export HARBOR_LAUNCH_JSON=/workspace/private/run/launch.json
export PYTHONPATH="$PWD:$PWD/verl"
python -m examples.harbor_opd_rl.launch --mode rl --launch "$HARBOR_LAUNCH_JSON" --print-config
```

For a short run saving every published step, retain the launcher's prepared overrides and add explicit test overrides before invoking the native entrypoint:

```bash
python - <<'PY'
import json, os, subprocess, sys
from pathlib import Path
from examples.harbor_opd_rl.launch import build_overrides, compose_config
launch = json.loads(Path(os.environ['HARBOR_LAUNCH_JSON']).read_bytes())
overrides = build_overrides('rl', launch, os.environ)
overrides += ['trainer.total_training_steps=4', 'trainer.save_freq=1', 'trainer.test_freq=1']
compose_config(overrides)
subprocess.run([sys.executable, '-m', 'verl.trainer.main_ppo', '--config-name=ppo_trainer', *overrides], check=True)
PY
```

For independent restart, repeat the same launcher composition in a **new trainer process / owned run scope**, append `trainer.resume_mode=resume_path` and `trainer.resume_from_path=/workspace/private/run/rl-training/checkpoints/global_step_<n>` with the observed checkpoint number, and choose a later `total_training_steps`. Register new runtime Gateway endpoints through the normal controller path; never reuse a receipt for a different port/run spec. The short wrapper above is necessary because the current launcher CLI has no arbitrary Hydra override flag. Do not append unsupported CLI options to `launch.py`.

## Required assertions, not just loss curves

1. Before update, store base model revision and Student LoRA tensor checksums, fixed probe token IDs, action masks, and baseline token logprobs from the actual rollout service.
2. Construct at least one complete four-rollout Harbor group with nonconstant verifier rewards. Repeating the same frozen task is acceptable for engineering transport checks, but identical all-success/all-failure rewards yield zero GRPO advantage and cannot prove an RL update.
3. Confirm finite nonzero trainable gradients and changed LoRA tensors after an optimizer step; verify frozen base tensors remain unchanged in the trainer. A changed checkpoint container hash alone is insufficient.
4. After a completed publication, collect a **new** Gateway session whose complete generation-version evidence corresponds to the published version. Old in-flight trajectories are allowed in separate_async; do not mistake them for failure of publication or claim that the immediately next queued sample is fresh.
5. Query the same fixed prefix / candidate-token scores on the actual serving policy before and after publication. Require a numerical change above stated precision tolerance, then compare post-publication scores with a fresh process loaded from that checkpoint's merged policy. Greedy output need not change after one small update.
6. Ensure KV cache invalidation/publication completed and every surviving Gateway generation has actual version evidence. ReplayBuffer's prompt-scheduling staleness threshold is not a bound on every token's real version span.
7. Restart independently from the saved checkpoint, verify LoRA rank/alpha, restored model checksums and optimizer step, and repeat the same policy probe before another update. Use pinned base weights plus checkpointed LoRA; do not accidentally reload only the base model or treat sharded training files as an HF adapter directory.
8. Record the resulting task receipt, TQ keys, checkpoint hash, publication version, probe scores and reload result together. Existing CPU tests establish loss/tensor contracts but do not yet automate this complete live evidence collection.

## Remaining incremental-sync work

A true adapter-only non-naive path would need a versioned PEFT metadata transport, correct initial base synchronization, receiver adapter installation and rollback semantics, and cache/version handling after confirmed installation. It also needs tests showing repeated adapters are replaced rather than accumulated. That feature is outside this minimum correction; the current merged full-weight path is chosen for correctness.

## Single-GPU native FSDP merged-export component probe

Planned executable: `deployment/checks/fsdp_lora_merged_export.py`. It initializes a single-process NCCL group and the real pinned `FSDPEngineWithLMHead` with a fixed local model snapshot, ordinary LoRA and SDPA/no-padding disabled. No Ray trainer or rollout server is needed. It performs a short real language-model gradient update using the engine-owned optimizer, verifies that only adapter tensors change, streams the engine's actual `get_per_tensor_param` merged export, and compares one adapted linear layer to independently computed base + PEFT delta. Hashes before/after export must show the trainer weights restored bit-for-bit; adapter parameters must also remain intact. A JSON result records model artifact identity, dependency/commit versions, gradient/update evidence and export restoration assertions.

This is a **single-GPU export component check**, not NCCL actor-to-rollout transport, Harbor RL/OPD improvement, two-GPU serving publication, or checkpoint reload. It deliberately tests numerical correctness with a short supervised diagnostic update, not a claim of task learning. GPU execution belongs to the GPU-owning agent/operator; this implementation session only checks syntax and CLI help.

Operator command from the worktree root, with exactly one assigned device visible:

```bash
CUDA_VISIBLE_DEVICES=<assigned-device> PYTHONPATH="$PWD:$PWD/verl" \
python deployment/checks/fsdp_lora_merged_export.py \
  --model-path /workspace/models/fixed-student-4b-snapshot \
  --output /workspace/private/run/fsdp-merged-export.json
```

The result must contain `passed: true`, nonzero adapter update count and merged delta, exact base-plus-delta equality, and exact trainer-state restoration. It records native source hashes as well as the VERL commit so a local overlay cannot be mistaken for pristine upstream. Any assertion failure exits nonzero and saves failure evidence. Existing evidence is never overwritten. The script has only passed local Ruff checks and CPU CLI parsing; GPU execution and its numerical assertions remain pending.
