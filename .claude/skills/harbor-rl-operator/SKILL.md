---
name: harbor-rl-operator
description: 从一台新 GPU 机器到一次完整 Harbor + Modal + VERL（GRPO / DAPO / OPD）训练的全流程操作手册，给 Claude Code / Codex 直接执行。触发：配服务器、新 pod、部署训练环境、启动训练、跑 pipeline、换模型、换数据集、加 Teacher、恢复凭据、pod 重建、端口变了。
---

# Harbor RL 操作员

目标：**只用仓库里的脚本**把一台新机器变成可训练状态并跑完一次带验收的训练；每一步都留证据、可重跑；不做脚本外的手工操作，需要人的地方明确停下来问。

人工版见 `docs/performance-9b/operator-runbook.md`；分析训练结果用 `rl-training-analyst` skill。

## 0. 需要人给的输入（缺一项先问）

| 输入 | 形式 | 备注 |
|---|---|---|
| GPU 机器 SSH | `root@<ip> -p <port> -i ~/.ssh/id_ed25519` | RunPod pod 重建后端口会变；host key 用 `StrictHostKeyChecking=accept-new` |
| 持久卷 | 挂在 `/workspace`，含 `verl-uni-agent-harbor-opd-rl/{envs,data,runs,cache,src}` | 新卷需按 §2 重建 lane |
| 凭据（本机） | `~/.modal.toml`、`~/.cache/huggingface/token`、`WANDB_API_KEY` 环境变量、`GH_TOKEN` 环境变量 | 只通过 scp / 命令环境传到远端 `/root`，不进仓库 |
| Modal 额度 | 一天 ≥ 300 沙箱的 spend limit | 触顶表现为 `ResourceExhaustedError` |
| 决策 | 模型（Student/Teacher）、数据切片、步数、是否 DAPO / Teacher | 见 §4 参数表 |

## 1. 一次冷启动的顺序（每步一条命令）

```bash
cd <repo>                                  # 分支 verl-uni-agent-harbor-opd-rl，HEAD 已 push
export WANDB_API_KEY=<key> GH_TOKEN=<token>
PORT=<新端口>

# 1) 探测 + 凭据 + 源码 + 模型缓存 + lane 重证（约 5–15 分钟）
MODELS_TO_FETCH="Qwen/Qwen3.8-27B Qwen/Qwen3.5-9B" \
bash deployment/bootstrap/gpu-pod-restore.sh $PORT --cache-local
#    内部：host key → /root 凭据 → sync-source.sh（git 模式，精确 SHA + verl 子模块）→ 模型拷本地 NVMe
#    → 后台下载 MODELS_TO_FETCH → stages/00_env.sh 激活证明。任何一步失败即停。

# 2) 起 pipeline（远端 nohup，驱动脚本自跑；见 §4 选参数）
ssh -p $PORT -i ~/.ssh/id_ed25519 root@<ip> 'cd /workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent && \
  PIPE_ROOT=/workspace/verl-uni-agent-harbor-opd-rl/runs/<run-name> <PARAMS> \
  nohup bash examples/harbor_opd_rl/run_tb21_pipeline.sh > /workspace/verl-uni-agent-harbor-opd-rl/runs/<run-name>/driver.log 2>&1 < /dev/null &'

# 3) 监控（5 分钟一次，只看阶段结果 / checkpoint / 异常；不要逐条 rollout 刷）
#    看 $PIPE_ROOT/pipeline-summary.jsonl、$PIPE_ROOT/<stage>/PASSED、train/checkpoints/*/global_step_N、
#    train.log 里的 spend limit / rollout failure / trial_timeout / OutOfMemory

# 4) 结束后
#    $PIPE_ROOT/acceptance/acceptance.json（PASS / MECHANICS_ONLY / FAIL）+ report-tables.md
#    把 acceptance.json / verdict.json / delta.json / report-tables.md 拷回 docs/performance-9b/<run-name>/，commit + push
#    ssh 远端 `modal container list` 确认无残留沙箱
```

## 2. lane 不存在或损坏时（新卷 / 空壳 venv）
```bash
ssh ... 'LANE=ua-verl-py312-vllm023 UV_VENV=/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1 \
  bash /workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/deployment/bootstrap/uv-lane-bootstrap.sh'
```
从 `deployment/versions/uv-lanes/ua-verl-py312-vllm023.freeze.txt` 重建（含 harbor 0.16.1、modal 1.5.5），脚本自带 CUDA + import 激活证明。venv 只能在 `/workspace`。手册：`docs/performance-9b/uv-runbook.md`。

## 3. 阶段与判定（驱动 `run_tb21_pipeline.sh`）
env → data → oracle → rollout → train → delta → resume → summary → acceptance。每阶段一个脚本（`examples/harbor_opd_rl/stages/`），有 `PASSED` 标记即跳过；失败用 `FROM_STAGE=<stage>` 重跑；GPU 阶段起跑前检查 GPU 空闲与无遗留 trainer。训练完成的判据是 `global_step_N/actor/*.pt` + step 指标，不是退出码。

## 4. 参数表（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATASET` / `STAGE1_SLICE` / `STAGE1_SOURCES` | tb21 / 20 / 两来源 | `stage1` = `gump2049/xDAN-Harbor-Stage1-Tasks`；`STAGE1_SLICE=0` 全部 train；validation 自动成 held-out |
| `MODEL_PATH` | `/workspace/models/Qwen3-4B-1cfa9a7` | 新 pod 用 `/tmp/models/...` 本地副本更快 |
| `TRAIN_STEPS` / `RESUME_EXTRA_STEPS` | 3 / 1 | 小数据集 epoch 自动反推 |
| `ROLLOUT_N` / `CONCURRENCY` / `TRAIN_BATCH_SIZE` | 4 / 4 / 2 | 提 GPU 利用率先加并发；沙箱数 = steps × batch × n |
| `TRAINER_MODE` | colocate_async | `sync` 只做 A/B；`separate_async` 需第 2 张卡且无 Teacher |
| `HARBOR_REWARD_MODE` | pass_ratio | 二值 reward 下弱模型全 0 |
| `DAPO` | 0 | 组内有方差后再开 |
| `TEACHER` / `TEACHER_MODEL_PATH` / `TEACHER_GPU_MEM` | 0 / = MODEL_PATH / 0.25 | 需要独立整卡；2 卡：GPU1 Teacher，`TEACHER_GPU_MEM=0.8` |
| `VAL_BEFORE_TRAIN` / `TEST_FREQ` / `VAL_MAX_SAMPLES` | False / -1 / 1 | 要 held-out 对比就 `True / =TRAIN_STEPS / 5` |
| `FAIL_ON_ROLLOUT_ERROR` | 0 | 1 = 严格 smoke |
| task config `max_turns` / `max_total_tokens` / `trial_timeout_sec` | 50 / 32768 / 2400 | 改 `tb21_terminus2_smoke.yaml`，`max-model-len ≥ max_total_tokens + 4096` |

## 5. 停止与清理（只动自己的进程）
```bash
ps -eo pid,cmd | grep -E "^ *[0-9]+ bash examples/harbor_opd_rl/run_tb21_pipeline.sh"        # 驱动
ps -eo pid,cmd | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo"                     # trainer
kill -TERM <pids>; sleep 10; kill -KILL <剩余>; ray stop --force; modal container list; modal container stop -y <id>
mv $PIPE_ROOT/train $PIPE_ROOT/train-attemptN-<原因>    # 现场永不覆盖
```
禁止 `pgrep -f <脚本名>`（会匹配自己的 ssh shell），禁止停别的项目进程。

## 6. 已知故障 → 动作（详见 lessons.md）
| 症状 | 动作 |
|---|---|
| `ResourceExhaustedError … spend limit` | 外部阻塞：停 run，请人提额，`FROM_STAGE=train` 续 |
| `ImageBuildError` + `requested access … denied` | task.toml 的 `docker_image` 别名不可拉取；data 阶段已自动剥；新来源加进 `STAGE1_STRIP_IMAGE_PREFIXES` |
| 一条 trial 30 分钟无进展、进程只连 Modal 443 | `trial_timeout_sec` 会杀；确认 `FAIL_ON_ROLLOUT_ERROR=0` |
| SSH `kex_exchange_identification` / banner timeout | sshd 限流或 pod 重建；等待或向人要新端口，然后 §1 步骤 1 |
| train "checkpoint missing" 但 `global_step_N/actor` 存在 | 旧脚本；`FROM_STAGE=train` 会复用已完成的 run |
| 阶段失败但 driver.log 没有该阶段任何行 | pipefail 静默退出；`bash -x stages/<x>.sh` 定位 |
| grad_norm 全 0 | 组内 reward 无方差：换题 / 加 n / pass_ratio |

## 7. 交付纪律
- 每个节点 `git commit` + `git push`（先 `ruff check .` 与 `ruff format --check .`，不接管道）。
- 证据进 `docs/performance-9b/<run-name>/`；关键事实写 `tasks/memory.md`；踩坑写 `tasks/lessons.md`；切 session 前更新 `tasks/handoff.md`。
- 分析与对比表：`.claude/skills/rl-training-analyst/scripts/report.py --run <wandb> --run-root <dir>`。
