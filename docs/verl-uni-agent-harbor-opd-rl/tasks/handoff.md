# Handoff：verl-uni-agent-harbor-opd-rl

更新：2026-09-17 11:25 UTC。历史逐轮记录在 `handoff-history.md`，持久决策在 `memory.md`，踩坑在 `lessons.md`（28 条），任务清单在 `todo.md`，对外汇报在 `progress-report-2026-09-17.md`。

## 1. TL;DR

- **目标**：用 VERL 生态把"真实软件工程任务上的 agent 能力"训进模型，评测口径 Terminal-Bench 2.1。三步路线（用户 2026-09-16 定）：① terminus-2 + Modal 纯 RL 通路 → ② DAPO + OPD（Teacher）联合更新 → ③ DSH harness 进沙箱。
- **已验收**：pipe-r1（TB 2.1 easy，机制 PASS）、pipe-r2（stage1 Terminal-Lego 20 题纯 RL，PASS，`docs/…/pipe-r2/`）。pipe-r3（4B 自评 Teacher）train + delta PASS。4B TB 2.1 正式基线 n=1：0/66 有效通过。
- **正在跑（全部脱离会话，本机离线不影响）**：
  - 双卡 11965：pipe-r3 resume → 验收；之后 `runs/pipe-r4/chain.sh` 自动起 **pipe-r4 = Qwen3.5-9B Student + Qwen3.8-27B Teacher**（路线 ② 真 Teacher）。
  - 单卡 12063：**pipe-r5 = 4B 纯 RL + DAPO=1，20 步**（Terminal-Lego 20/5，独立 `data-r5`）。
- **Modal** 已换新工作区 profile `l98348740`（旧的触发账期上限）。所有链前置 `deployment/bootstrap/modal-quota-wait.sh`，额度断了会自动等、恢复后续跑。
- **已知数据缺口**：swe-rebench-v2-fv 25 题的 verifier `pytest --ctrf` 在任务镜像里不可用，oracle 闸门拦下，暂不入训。

## 2. 交付物（按用途）

### 一键脚本（`examples/harbor_opd_rl/`，README 在同目录）
| 文件 | 用途 |
|---|---|
| `run_tb21_pipeline.sh` | 驱动：按序跑 stages，跳过 PASSED，`FROM_STAGE=` / `SKIP_STAGES=` |
| `stages/00_env … 80_acceptance.sh` | 每阶段独立可复现；`common.sh` 共享变量与进程卫生 |
| `train_tb21_lora_smoke.sh` | 训练入口（官方 quickstart 的 env-var 覆盖风格）。开关：`TRAINER_MODE`（默认 colocate_async）、`DAPO=1`、`TEACHER=1`、`FAIL_ON_ROLLOUT_ERROR`、`RESUME_FROM_PATH`、wandb、prefix caching / CUDA graph 默认开 |
| `tb21_terminus2_smoke.yaml` | Harbor task config：terminus-2、`max_turns 50`、`max_total_tokens 32768`、`trial_timeout_sec 2400`、Modal 2cpu/4GB |
| `{base,rl,opd,hybrid}.yaml`, `launch.py` | 早期 DSH 路线的原生 recipe，路线 ③ 复用 |

### 运维
| 文件 | 用途 |
|---|---|
| `deployment/bootstrap/gpu-pod-restore.sh <port> [--cache-local]` | pod 重建/新机后一键恢复：host key、Modal/HF/wandb 凭据、模型拷本地 NVMe、重证 lane。需要 `export WANDB_API_KEY` |
| `deployment/bootstrap/uv-lane-bootstrap.sh` | 从 freeze 快照重建 uv lane（拒绝 /workspace 外路径，激活证明） |
| `deployment/versions/uv-lanes/ua-verl-py312-vllm023.freeze.txt` | lane 唯一版本快照（含 harbor 0.16.1、modal 1.5.5） |
| `docs/verl-uni-agent-harbor-opd-rl/uv-runbook.md` | 环境手册（继承自 MetaRSI） |

### 代码改动（上游 adapter，opt-in、带单测）
- `uni_agent/tasks/harbor/reward.py`：`HARBOR_REWARD_MODE=pass_ratio`，verifier CTRF 部分得分（5 测）。
- `uni_agent/tasks/harbor/task.py`：`trial_timeout_sec` 整条 trial 墙钟，超时 exit 124（3 测）。
- `stages/10_data.sh`：`DATASET=stage1` 接 `gump2049/xDAN-Harbor-Stage1-Tasks`，剥掉不可拉取的 `docker_image` 别名。

### 分析
- `.claude/skills/rl-training-analyst/`：SKILL.md（指标字典、诊断手册、统一对比表规则）+ `scripts/wandb_pull.py` + `scripts/report.py`（跨线对比表）。
- `docs/verl-uni-agent-harbor-opd-rl/architecture.html`：Mermaid 架构图。

## 3. 设计约束（铁律）
- Uni-Agent owns Agent/Task/Gateway/轨迹准入/TQ；VERL owns optimizer 与同步；Harbor owns verifier；Modal 只做沙箱。不切 Tinker trainer，不引入第二套 agent loop。
- Gateway 必须在链路里：训练需要采样时的原始 token / logprob / action mask。terminus-2 跑在宿主机，所以不需要公网 tunnel；DSH 进沙箱（路线 ③）才需要。
- 验收看三层：机制（阶段 PASSED）、动力学（wandb 与 train.log 逐步一致）、权重（delta + resume 连续）。`80_acceptance.sh` 给 PASS / MECHANICS_ONLY / FAIL。
- 每次 push 前 `ruff check .` 与 `ruff format --check .`，**不接管道**。
- 所有资产只放 `/workspace`（pod 重建会清 `/tmp` `/root`）。凭据不进仓库。
- **共享卷警告**：单卡 pod（12063）和双卡 pod（11965）挂同一个 `/workspace`，源码 `src/uni-agent` 也是同一份。有 run 在跑时不要 `rsync --delete` 或 git 切换源码；每条 run 用独立 `DATA_DIR`。

## 4. 已踩坑（详见 lessons.md）
- **环境**：venv 曾建在 `/tmp` 被清；pod 重建改端口（12524 → 30284 → 12063 → 新机 11965）并丢 `/root` 凭据；sshd 偶发握手超时不等于训练中断。
- **Modal**：一天约 80 个沙箱触到 spend limit；一条 trial 在上下文摘要后卡在 Modal API 30+ 分钟，Harbor `--agent-timeout` 不覆盖 → `trial_timeout_sec` 兜底 + `FAIL_ON_ROLLOUT_ERROR=0` 补组；`modal container stop` 非交互要 `-y`。
- **训练脚本**：DSH 专属 `require_verifier_reward` 让 Harbor session 全失败；`total_epochs=1` 在小数据集只够 samples/batch 步；VERL v1 checkpoint 在 `global_step_N/actor/`；`set -e -o pipefail` 下 grep/find 无匹配会静默退出。
- **数据**：Terminal-Lego 的 `task.toml` 带不可拉取的 `docker_image` 别名，需剥掉让 Harbor 按 Dockerfile 构建。
- **信号**：二值 reward 下 4B 22/22 全 0；pass_ratio 后组内出现方差才有梯度；grad_norm 只在组内有方差的 step 非零。
- **进程**：`pgrep -f <脚本名>` 会匹配自己的 ssh shell，用锚定到可执行文件的 `ps | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo"`。
- **Teacher**：VERL 原生 Teacher 是独立 vLLM（prompt_logprobs 打分），需要**独立 Ray 资源池、整数张 GPU**，单卡不行（`TEACHER_SHARE_GPU=1` 是未验证的取巧）。

## 5. 下一里程碑：路线 ② 真 Teacher（pipe-r4）与 DAPO 曲线（pipe-r5）

### 5.1 看进度（只读）
```bash
# 双卡：pipe-r3 / pipe-r4 阶段结果与 checkpoint
ssh -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177 'R=/workspace/verl-uni-agent-harbor-opd-rl/runs; for r in pipe-r3 pipe-r4; do grep -a -oE "\"stage\":\"[a-z]+\",\"status\":\"[a-z]+\"" $R/$r/pipeline-summary.jsonl | tail -3; done; tail -3 $R/pipe-r4/driver.log'
# 单卡：pipe-r5
ssh -p 12063 -i ~/.ssh/id_ed25519 root@157.157.221.177 'tail -3 /workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r5/driver.log'
```
wandb 为准：project `xDAN-Verl-Uni-agent-Harbor-rl-opd`。

### 5.2 怎么起一条新 run（参考现成命令）
- 双卡 9B + 27B：`docs/verl-uni-agent-harbor-opd-rl/pipe-r4/chain.sh`（拷模型到 `/tmp/models`，等前一条 run 的 PID 退出，再跑整条 pipeline）。
- 单卡 4B + DAPO：`PIPE_ROOT=… DATA_DIR=…/data-r5 DATASET=stage1 STAGE1_SLICE=0 STAGE1_SOURCES=terminal-lego-15k TRAIN_STEPS=20 ROLLOUT_N=8 CONCURRENCY=16 TRAIN_MAX_SAMPLES=20 VAL_MAX_SAMPLES=5 VAL_BEFORE_TRAIN=True TEST_FREQ=10 GPU_MEMORY_UTILIZATION=0.45 HARBOR_REWARD_MODE=pass_ratio DAPO=1 bash examples/harbor_opd_rl/run_tb21_pipeline.sh`，用 `launch-detached.sh` 启动。
- 两台 pod 共享 `/workspace`：每条 run 用自己的 `DATA_DIR`，否则 data 阶段会删掉另一条 run 正在用的任务目录。
- 续跑只需 `PIPE_ROOT=… FROM_STAGE=<stage>`；resume 自动读 `train/stage-env.sh`。

### 5.3 之后
- [ ] pipe-r4 看点：9B rollout 阶段能否推理、actor 是否 OOM、`actor/distillation/loss` 是否离开 0、Teacher 每步耗时。
- [ ] pipe-r5 看点：`training/filter_groups/*`（DAPO 丢弃与重采）、reward 曲线 20 步内是否上升、held-out 第 0/10/20 步。
- [ ] SWE-rebench verifier 修复后 `STAGE1_SLICE=0` 混合 41 题；held-out 扩到 ≥ 20 题。
- [ ] `report.py` / `80_acceptance.sh` 增加 OPD 与 Teacher 检查。
- [ ] 路线 ③：agent 换 DSH（`deployment/services/harbor_modal_ingress.py`、`harbor_run_controller.py`）。

## 6. 分支 / 部署状态

| 项 | 值 |
|---|---|
| 分支 | `verl-uni-agent-harbor-opd-rl`，origin 同步，无 PR |
| 单卡 pod | `root@157.157.221.177:12063`，host `b9f9aa87466b`，1 × RTX PRO 6000 96GB；跑 pipe-r5 |
| 双卡 pod | `root@157.157.221.177:11965`，host `dbcea07805e9`，2 × RTX PRO 6000 96GB，256 核 / 1.5 TB RAM / 本地盘 100 GB |
| 共享卷 | `/workspace`（`72jdno5cuk`）；项目根 `/workspace/verl-uni-agent-harbor-opd-rl/{src,envs,data,runs,cache}` |
| 远端源码 | `src/uni-agent` rsync 副本（无 .git），`runs/source-manifest-6b7f362.json` |
| lane | `envs/ua-verl-py312-vllm023-ws1`（py3.12，Torch 2.11，vLLM 0.23，harbor 0.16.1，modal 1.5.5） |
| 模型 | `/workspace/models/{Qwen3-4B-1cfa9a7,Qwen3.5-9B,Qwen3.8-27B}`；双卡 pod `/tmp/models/` 有本地副本（重建会丢） |
| 数据 | TB 2.1 全 89 题；stage1 Terminal-Lego 20 train / 5 val（`data/`、`data-r4/`、`data-r5/` 各一份）；swe-rebench 25 题 verifier 不可用 |
| wandb | project `xDAN-Verl-Uni-agent-Harbor-rl-opd`，entity `xdan-ai`；pipe-r1 `ohz52n9r` / `6iwtnfu6`；pipe-r2 `dzlqgapu` / `eg1ix7eo`；pipe-r3 `pg4xsj19` |
| Modal | profile `l98348740`（2026-09-17 起；旧 `shootime007` 触顶后停用）；沙箱由 Harbor 逐条销毁，跑完 `modal container list` 核残留 |
| 凭据（远端，pod 重建后重拷） | `/root/.modal.toml`、`/root/.netrc`、`/root/.cache/huggingface/token` |

## 7. 冷启动 checklist（新 session 或新机器）
1. 读本文件 → `todo.md` → `memory.md` 末节 → `examples/harbor_opd_rl/README.md`。
2. `git status && git log -3 --oneline`，确认 HEAD 已推送。
3. §5.1 检查新 pod；缺什么跑 `gpu-pod-restore.sh`。
4. `nvidia-smi` 与 `ps -eo pid,cmd | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo"` 确认无遗留进程；不停别的项目进程；共享卷上另一 pod 的 run 目录不要动。
5. 用 §5.2 起 pipeline（一律 `launch-detached.sh`，前置 `modal-quota-wait.sh`）；监听只看阶段结果、checkpoint、错误事件；跑完用 `report.py` 出统一对比表。
6. 每个节点 commit/push，关键事实写 `memory.md`，踩坑写 `lessons.md`。
