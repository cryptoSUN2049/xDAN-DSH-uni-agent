# Terminal-Bench 2.1 × Harbor × VERL: single-GPU training pipeline

Trains Qwen3 (LoRA, GRPO / optional DAPO) on Terminal-Bench 2.1 tasks executed by
Harbor's built-in `terminus-2` agent in Modal sandboxes, with rollouts captured
token-by-token through the Uni-Agent Gateway. Follows the upstream
[Harbor integration](../../docs/source/quickstart/harbor-integration.md) and
[RL training](../../docs/source/quickstart/rl-training.md) quickstarts; the
training entry keeps the env-var override style of
`examples/quickstart/training/train_qwen3p5_dense.sh`.

No public ingress is needed: terminus-2 and the Harbor CLI run on the GPU host and
call the session-scoped Gateway locally; only shell commands enter the sandbox.

## Files

| File | Role |
|---|---|
| `run_tb21_pipeline.sh` | One-command driver: orders the stages, skips `PASSED` ones, `FROM_STAGE=` / `SKIP_STAGES=` |
| `stages/common.sh` | Shared env (lane, model, data, knobs), evidence helpers, process hygiene |
| `stages/00_env.sh` | Lane imports + CUDA backward + Harbor CLI + Modal/wandb credentials |
| `stages/10_data.sh` | Harbor Hub → parquet (`uni_agent.tasks.harbor.preprocess`); `TASK_FILTER=easy` builds the 4-task subset |
| `stages/20_oracle.sh` | Reference solutions in Modal, verifier must score 1.0 (no GPU) |
| `stages/30_rollout.sh` | vLLM + Gateway + terminus-2, requires scored sessions and `trajectory.npz` |
| `stages/40_train.sh` | `TRAIN_STEPS` GRPO/LoRA steps via `train_tb21_lora_smoke.sh`; passes on checkpoint + metrics |
| `stages/50_delta.sh` | CPU diff of first vs last checkpoint (`deployment/checks/checkpoint_delta.py`) |
| `stages/60_resume.sh` | Fresh trainer reloads the last checkpoint and trains `RESUME_EXTRA_STEPS` more |
| `stages/70_summary.sh` | `verdict.json`: `full_pipeline_mechanically_closed`, `learning_signal_observed` |
| `train_tb21_lora_smoke.sh` | Training entry (env-var overrides, `PRINT_COMMAND=1` gate, `DAPO=1`, `RESUME_FROM_PATH`, wandb) |
| `tb21_terminus2_smoke.yaml` | Harbor task config: terminus-2 kwargs, `max_total_tokens` episode budget, Modal resources |
| `{base,rl,opd,hybrid}.yaml`, `launch.py` | Native RL/OPD/hybrid recipes for the Teacher route (next milestone) |

## Run

```bash
# on the GPU host, inside the repo checkout
PIPE_ROOT=/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r1 \
TRAIN_STEPS=3 RESUME_EXTRA_STEPS=1 ROLLOUT_N=4 CONCURRENCY=4 \
TASK_FILTER=easy HARBOR_REWARD_MODE=pass_ratio DAPO=0 \
bash examples/harbor_opd_rl/run_tb21_pipeline.sh
```

Evidence lands under `$PIPE_ROOT/<stage>/` plus `pipeline-summary.jsonl`; rerun
after a failure with `FROM_STAGE=<stage>`. Any stage can be run alone with the
same variables, e.g. `PIPE_ROOT=... bash examples/harbor_opd_rl/stages/40_train.sh`.

Credentials are read from the host, never from the repo: `/root/.modal.toml`
(Modal) and `~/.netrc` (`wandb login`). Training logs to wandb project
`xDAN-Verl-Uni-agent-Harbor-rl-opd` unless `WANDB_ENABLED=0`.

## Knobs that matter

- `agent.model.max_total_tokens` (task config) is the episode budget and becomes
  `rollout.response_length`; the inference runner adds a fixed 4096 prompt, so
  `--max-model-len` must be at least budget + 4096.
- `--served-model-name hosted_vllm/<name>`: litellm strips the prefix and sends
  `<name>` to the injected `HOSTED_VLLM_BASE_URL`; the Gateway does not validate it.
- `HARBOR_REWARD_MODE=pass_ratio` turns a failed binary verifier reward into
  passed/total tests from `verifier/ctrf.json`; `binary` keeps Harbor's reward.
- `DAPO=1` enables `algorithm.filter_groups` (dynamic sampling) and
  `clip_ratio_high=0.28`; it needs reward variance, otherwise every group is
  refilled until `DAPO_MAX_GEN_BATCHES` and the step aborts.
- Completion of a training stage is judged by `global_step_N` plus the step
  metrics line, not the exit code: the trainer can hang in wandb teardown.
