# Handoff：verl-uni-agent-harbor-opd-rl

更新：2026-09-17 00:50 UTC。面向"新开 2 卡机器、快速部署新实验"的冷启动。历史逐轮记录在 `handoff-history.md`，持久决策在 `memory.md`，踩坑在 `lessons.md`（14 条），任务清单在 `todo.md`。

## 1. TL;DR

- **目标**：用 VERL 生态把"真实软件工程任务上的 agent 能力"训进模型，评测口径 Terminal-Bench。三步路线（用户 2026-09-16 定）：① terminus-2 + Modal 纯 RL 通路 → ② DAPO + OPD（Teacher）联合更新 → ③ DSH harness 进沙箱。
- **路线 ① 机制验收 PASS（2026-09-16 16:47 UTC）**：`examples/harbor_opd_rl/run_tb21_pipeline.sh` 一条命令跑完 env → data → oracle → rollout → 3 步训练 → checkpoint 差分 → 断点续训 → wandb 交叉验收。证据 `docs/verl-uni-agent-harbor-opd-rl/pipe-r1/`。
- **算法核过是对的**：从 rollout dump 重算 GRPO 组内 advantage 与 grad_norm 逐步吻合；action mask 正确（56% 模型 token 参与 loss）；504/504 LoRA 张量变、399/399 base 不变。
- **正在跑**：pipe-r2（旧单卡 pod，端口 12063）：stage1 Terminal-Lego 20 题、6 步 colocate_async、n=8、并发 16、held-out 前后评估，wandb `dzlqgapu`。
- **新 2 卡 pod 已接入**（端口 11965，host `dbcea07805e9`，2 × RTX PRO 6000 96GB，同一共享卷）：源码已同步到 HEAD，凭据恢复中。下一步 pipe-r3：`TEACHER=1` 开路线 ②。
- 分支 HEAD `6b7f362`（+ 本次 docs），领先 main 约 280 提交，全部已推送 origin。

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
- **共享卷警告**：旧 pod（12063）和新 pod（11965）挂同一个 `/workspace`。pipe-r2 在旧 pod 跑完前，新 pod 不要动 `runs/pipe-r2`，不要 `rsync --delete` 源码（已同步过一次）。

## 4. 已踩坑（详见 lessons.md）
- **环境**：venv 曾建在 `/tmp` 被清；pod 重建改端口（12524 → 30284 → 12063 → 新机 11965）并丢 `/root` 凭据；sshd 偶发握手超时不等于训练中断。
- **Modal**：一天约 80 个沙箱触到 spend limit；一条 trial 在上下文摘要后卡在 Modal API 30+ 分钟，Harbor `--agent-timeout` 不覆盖 → `trial_timeout_sec` 兜底 + `FAIL_ON_ROLLOUT_ERROR=0` 补组；`modal container stop` 非交互要 `-y`。
- **训练脚本**：DSH 专属 `require_verifier_reward` 让 Harbor session 全失败；`total_epochs=1` 在小数据集只够 samples/batch 步；VERL v1 checkpoint 在 `global_step_N/actor/`；`set -e -o pipefail` 下 grep/find 无匹配会静默退出。
- **数据**：Terminal-Lego 的 `task.toml` 带不可拉取的 `docker_image` 别名，需剥掉让 Harbor 按 Dockerfile 构建。
- **信号**：二值 reward 下 4B 22/22 全 0；pass_ratio 后组内出现方差才有梯度；grad_norm 只在组内有方差的 step 非零。
- **进程**：`pgrep -f <脚本名>` 会匹配自己的 ssh shell，用锚定到可执行文件的 `ps | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo"`。
- **Teacher**：VERL 原生 Teacher 是独立 vLLM（prompt_logprobs 打分），需要**独立 Ray 资源池、整数张 GPU**，单卡不行（`TEACHER_SHARE_GPU=1` 是未验证的取巧）。

## 5. 下一里程碑：2 卡 pod 上的 pipe-r3（路线 ② 起步）

### 5.1 新 pod 就绪检查
```bash
ssh -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177 'nvidia-smi -L; ls /root/.modal.toml /root/.netrc /root/.cache/huggingface/token; ls /tmp/models; cat /workspace/verl-uni-agent-harbor-opd-rl/runs/source-manifest-6b7f362.json'
```
若凭据缺失：`export WANDB_API_KEY=<key>; bash deployment/bootstrap/gpu-pod-restore.sh 11965 --cache-local`。

### 5.2 pipe-r3 配置（先 4B 自评 Teacher 打通接线）
```bash
cd /workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent
PIPE_ROOT=/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r3 \
DATASET=stage1 STAGE1_SLICE=20 STAGE1_SOURCES=terminal-lego-15k \
TRAIN_STEPS=6 RESUME_EXTRA_STEPS=1 ROLLOUT_N=8 CONCURRENCY=16 \
TRAIN_MAX_SAMPLES=20 VAL_MAX_SAMPLES=5 VAL_BEFORE_TRAIN=True TEST_FREQ=6 \
MODEL_PATH=/tmp/models/Qwen3-4B-1cfa9a7 \
TEACHER=1 TEACHER_MODEL_PATH=/tmp/models/Qwen3-4B-1cfa9a7 TEACHER_GPU_MEM=0.8 \
HARBOR_REWARD_MODE=pass_ratio DAPO=0 \
nohup bash examples/harbor_opd_rl/run_tb21_pipeline.sh > /workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r3/driver.log 2>&1 &
```
- GPU0 = actor + rollout vLLM，GPU1 = Teacher（VERL 独立资源池）。2 卡下先保持 `colocate_async`；`separate_async` + Teacher 需要第三张。
- 换 9B / 27B Teacher：先 `huggingface-cli download` 到 `/workspace/models/`，改 `TEACHER_MODEL_PATH`。
- 期望新增指标：distillation 相关（teacher logprobs、OPD loss）；`report.py` 的 OPD 三行从 N/A 变实数是下一项脚本工作，acceptance 也要加 Teacher 检查。

### 5.3 之后
- [ ] `DAPO=1`：多数 step 组内有方差后开。
- [ ] Student 换 Qwen3.5-9B。
- [ ] `STAGE1_SLICE=0` 去掉 `STAGE1_SOURCES`：41 题两来源混合；扩批等 Tinker 线发布。
- [ ] 路线 ③：agent 换 DSH，重启 ingress / tunnel / registry 镜像（`deployment/services/harbor_modal_ingress.py`、`harbor_run_controller.py`）。

## 6. 分支 / 部署状态

| 项 | 值 |
|---|---|
| 分支 | `verl-uni-agent-harbor-opd-rl`，origin 同步，无 PR |
| 旧 pod（跑 pipe-r2） | `root@157.157.221.177:12063`，1 × RTX PRO 6000；pipe-r2 结束后可释放 |
| 新 pod | `root@157.157.221.177:11965`，host `dbcea07805e9`，2 × RTX PRO 6000 96GB，256 核 / 1.5 TB RAM / 本地盘 100 GB |
| 共享卷 | `/workspace`（`72jdno5cuk`）；项目根 `/workspace/verl-uni-agent-harbor-opd-rl/{src,envs,data,runs,cache}` |
| 远端源码 | `src/uni-agent` rsync 副本（无 .git），`runs/source-manifest-6b7f362.json` |
| lane | `envs/ua-verl-py312-vllm023-ws1`（py3.12，Torch 2.11，vLLM 0.23，harbor 0.16.1，modal 1.5.5） |
| 模型 | `/workspace/models/Qwen3-4B-1cfa9a7`（新 pod 另有 `/tmp/models/` 本地副本）；9B / 27B 未下载 |
| 数据 | TB 2.1 easy 4 题；stage1 Terminal-Lego 20 train / 5 val（`data/stage1/`）；swe-rebench 25 题未用 |
| wandb | project `xDAN-Verl-Uni-agent-Harbor-rl-opd`，entity `xdan-ai`；pipe-r1 `ohz52n9r` / `6iwtnfu6`；pipe-r2 `dzlqgapu` |
| Modal | profile `shootime007`；沙箱由 Harbor 逐条销毁，跑完 `modal container list` 核残留 |
| 凭据（远端，pod 重建后重拷） | `/root/.modal.toml`、`/root/.netrc`、`/root/.cache/huggingface/token` |

## 7. 冷启动 checklist（新 session 或新机器）
1. 读本文件 → `todo.md` → `memory.md` 末节 → `examples/harbor_opd_rl/README.md`。
2. `git status && git log -3 --oneline`，确认 HEAD 已推送。
3. §5.1 检查新 pod；缺什么跑 `gpu-pod-restore.sh`。
4. `nvidia-smi` 与 `ps -eo pid,cmd | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo"` 确认无遗留进程；不停别的项目进程；共享卷上另一 pod 的 run 目录不要动。
5. 用 §5.2 起 pipeline；监听只看阶段结果、checkpoint、事件；跑完用 `report.py` 出统一对比表。
6. 每个节点 commit/push，关键事实写 `memory.md`，踩坑写 `lessons.md`。
