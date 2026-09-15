# Uni-Agent native VERL V1 Harbor LoRA RL + OPD

Experimental recipe for this branch's paired VERL checkout. CPU configuration
composition is tested; real GPU training, LoRA weight synchronization, checkpoint
reload and throughput are **not yet certified**. This recipe currently requires
the existing Harbor Docker controller. Modal is not implemented by this recipe.

## Design and topology

The agent path stays `AgentFrameworkRolloutAdapter → GatewayAgentFramework →
run_task → HarborDshTask → Harbor worker/Trial → DshHarborAgent`. Harbor owns the
environment and independent verifier. Registered receipts admit the final Gateway
token trajectories; the framework scores every admitted chain with the native
VERL Teacher manager before a complete group is published to TransferQueue.

| Mode | Native trainer | GPU roles | Objective |
| --- | --- | --- | --- |
| `rl` | `separate_async` | 1 actor + 1 standalone rollout; no Teacher | Harbor verifier RL |
| `opd` | `colocate_async` | 1 shared actor/rollout + 1 Teacher | Teacher OPD policy gradient |
| `hybrid` | `separate_async` | 1 actor + 1 standalone rollout + 1 Teacher | Harbor RL + Teacher OPD |

These are role-count minimums, **not model-capacity guarantees**. A 9B Student
and 27B Teacher may need larger cards, lower context/concurrency, or more GPUs.
No particular Teacher repository, local snapshot, tokenizer compatibility or
GPU memory capacity is assumed. A100 40GB and 80GB need different capacity checks.

`opd` fits two GPU roles by time-sharing Student training and rollout; it does
not run all three compute roles concurrently. `hybrid` is the separate asynchronous
baseline for three or more GPUs. GPU IDs are assigned by Ray resource pools, not
hardcoded by the launcher. The controller and Harbor containers consume CPU and
must not be accidentally counted as additional trainer GPU roles.

`base.yaml` contains common native settings, each mode YAML selects topology and
Teacher usage, and `launch.py` composes them against `verl/trainer/config/ppo_trainer`.
The launcher introduces no new agent loop, trainer, reward function or loss.

## Loss and asynchronous contracts

- FSDP LoRA rank 16/alpha 32 updates the Student; the Teacher remains frozen.
- OPD uses native `loss_mode=k1` and `use_policy_gradient=true`: VERL converts
  the negative sampled-token distillation loss into policy-gradient advantage.
  Teacher prompt scoring supplies Teacher logprobs for the Student's actual sampled tokens;
  a text-only completion endpoint cannot substitute for this contract.
- `hybrid` enables `use_task_rewards=true` and coefficient 1.0. `opd` disables
  task reward in the loss, but **still requires a valid verifier receipt**.
- Strict groups, completed episodes, verifier rewards, trajectory dumps, and
  `validate_registered_trajectories` remain mandatory. All surviving chains are
  retained. A Teacher scoring failure must reject its strict group.
- Teacher context is 8193 tokens for a full 8192-token Student trajectory plus
  the scoring request's one generated token, as required by the native dataclass.
- Native `separate_async` requires a non-naive checkpoint backend; this recipe
  uses `nccl`. It sets `train_batch_size=2`, `ppo_mini_batch_size=1`, and
  `parameter_sync_step=2`, satisfying the pinned trainer's equality constraint.
- Version-span threshold is 2 with drop policy. This is a conservative starting
  bound, not measured optimal throughput. Track group rejection, version lag,
  Teacher queue time, verifier latency and GPU utilization before tuning it.
- Reward-model and reference-model KL are disabled; there is no extra model GPU
  pool. Harbor's verifier remains authoritative for the RL task reward.

## Inputs and usage

First prepare a **private** `dsh.harbor-m2-launch.v1` launch JSON with the existing
`examples/harbor/prepare_m2_training.py` workflow and approved controller policy.
It supplies dataset paths, task config, served model ID, route registration and
receipt-audit configuration. The controller/worker/tunnel must already be available.
The launcher does not deploy them or read authentication tokens into its output.

From the repository root, inspect the composition without allocating resources:

```bash
export STUDENT_MODEL_PATH=/absolute/path/to/pinned/student
export TEACHER_MODEL_PATH=/absolute/path/to/pinned/teacher
export TOOL_PARSER=hermes # Example only: select the parser for the actual model.
PYTHONPATH=.:verl python -m examples.harbor_opd_rl.launch \
  --mode hybrid --launch /private/harbor-run/launch.json --print-config
```

`STUDENT_MODEL_PATH` and `TOOL_PARSER` are always required. `TEACHER_MODEL_PATH`
is required only for `opd`/`hybrid`; in `rl` it is ignored and no Teacher is enabled.
Optional `TRAIN_FILE`, `TEST_FILE`, and `TASK_CONFIG` override prepared paths.
Changing a task must preserve the operator's frozen task/policy/receipt contract;
changing its path does not bypass admission. Use an independent holdout dataset
before making generalization claims; the old M2 preparation may represent only a
same-task engineering check.

After CPU review and GPU/resource readiness, remove `--print-config` to invoke
`python -m verl.trainer.main_ppo` with exactly the composed overrides. It runs in
the foreground; cancelling the launcher is not a proof that Ray/Harbor resources
have been cleaned up. Follow the existing controller cancellation/cleanup workflow.
Outputs are below the prepared `RUN_ROOT/<mode>-training/`. Use a fresh prepared
run root for a fresh experiment; checkpoint resume is disabled by default.

The prepared controller currently advertises a loopback control endpoint, so keep
this initial recipe on one GPU host. A multi-node deployment needs verified shared
paths and controller reachability from every runner before scaling nodes.

## Verification and acceptance

```bash
PYTHONPATH=.:verl python -m pytest -q \
  tests/uni_agent/examples/test_harbor_opd_rl_recipe.py
```

CPU tests compose all modes against the actual pinned VERL Hydra schema and verify
resource roles, async batch/sync invariants, native objectives, explicit model
inputs, strict receipt admission and the side-effect-free print path.

GPU acceptance remains: complete Harbor group; every admitted action token paired
with Teacher scoring; finite nonzero LoRA gradient/update; native NCCL rollout
weight refresh; fresh rollout using the new version; independent checkpoint reload;
held-out verifier comparison; and confirmed Harbor cleanup on success and failure.
A composed config is not evidence that these runtime gates have passed.

The Teacher bridge bounds each scoring request with
`custom.agent_framework.teacher_timeout_seconds` (default 300 seconds). A timeout
rejects the strict group instead of leaving it waiting indefinitely in TQ.
