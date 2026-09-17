# 人工操作手册：从新 GPU 机器到一次完整训练

更新：2026-09-17。与 agent 版 `.claude/skills/harbor-rl-operator/SKILL.md` 一一对应；这里只讲人要做什么、看什么、什么时候该停。

## 0. 你需要准备的
1. 一台 RunPod GPU pod（1 张 96GB 可跑纯 RL；2 张才能开 Teacher），挂载共享卷 `/workspace`（卷 id `72jdno5cuk`）。
2. 本机：`~/.ssh/id_ed25519`、`~/.modal.toml`、`~/.cache/huggingface/token`、终端里 `export WANDB_API_KEY=... GH_TOKEN=...`。
3. Modal 控制台 spend limit 够一天 300 个沙箱；wandb 项目 `xDAN-Verl-Uni-agent-Harbor-rl-opd`。
4. 本仓库分支 `verl-uni-agent-harbor-opd-rl` 已 `git push`。

## 1. 新机器上线（5–15 分钟）
```bash
MODELS_TO_FETCH="Qwen/Qwen3.8-27B Qwen/Qwen3.5-9B" bash deployment/bootstrap/gpu-pod-restore.sh <端口> --cache-local
```
看到 `[env …] passed: modal=l98348740 wandb=xdan-ai`（profile 以本机 `modal profile current` 为准） 即成功。它做了：host key、`/root` 凭据、源码 git 精确 SHA 检出（含 verl 子模块）、模型拷本地 NVMe、后台下载大模型、lane 激活证明。

失败时：
- `Connection closed` / banner timeout：pod 可能重建，去 RunPod 看新端口，重跑。
- lane 空壳：`uv-lane-bootstrap.sh`（见 `uv-runbook.md`）。

## 2. 起一次训练（1 条命令）
在远端仓库目录执行，参数按需改（完整表见 SKILL §4）：
```bash
PIPE_ROOT=/workspace/verl-uni-agent-harbor-opd-rl/runs/<run-name> \
DATASET=stage1 STAGE1_SLICE=20 STAGE1_SOURCES=terminal-lego-15k \
TRAIN_STEPS=6 RESUME_EXTRA_STEPS=1 ROLLOUT_N=8 CONCURRENCY=16 \
TRAIN_MAX_SAMPLES=20 VAL_MAX_SAMPLES=5 VAL_BEFORE_TRAIN=True TEST_FREQ=6 \
MODEL_PATH=/tmp/models/Qwen3-4B-1cfa9a7 \
TEACHER=1 TEACHER_MODEL_PATH=/workspace/models/Qwen3.8-27B TEACHER_GPU_MEM=0.8 \
HARBOR_REWARD_MODE=pass_ratio DAPO=0 \
nohup bash examples/harbor_opd_rl/run_tb21_pipeline.sh > $PIPE_ROOT/driver.log 2>&1 &
```
单卡纯 RL：去掉 `TEACHER*` 三项。要 DAPO：`DAPO=1`（前提是上一轮多数 step 组内有方差）。

## 3. 看什么（每 5–10 分钟一眼即可）
| 在哪 | 看什么 | 正常 | 异常 |
|---|---|---|---|
| `$PIPE_ROOT/driver.log` | `==> <stage>` / `passed` / `FAILED` | 阶段顺序推进 | `FAILED` → 看该阶段目录 |
| `$PIPE_ROOT/train/checkpoints/*/*/` | `global_step_N` 出现 | 每 15–25 分钟一个 | 40 分钟没新增，看下一行 |
| `$PIPE_ROOT/train/train.log` | `pending/running/finished/failure` 计数 | running > 0 且在变 | 计数 3 分钟不变且 GPU 0% 且无 `harbor trial` 进程 |
| wandb run 页 | `critic/score/mean`、`actor/grad_norm`、`response_length/mean`、`timing_s/gen` | score > 0、grad_norm 有限非零 | grad 恒 0 / NaN |
| `nvidia-smi` | GPU0 忙、GPU1（Teacher）显存占满 | 利用率跳动 | 长期 0% 见上一行 |
| `modal container list` | 活跃沙箱数 ≈ 并发数 | 跑完归零 | 跑完仍有残留 → `modal container stop -y <id>` |

## 4. 结束后
1. `cat $PIPE_ROOT/acceptance/acceptance.json | head -c 600`：`verdict` 为 `PASS` / `MECHANICS_ONLY` / `FAIL`。
2. `cat $PIPE_ROOT/acceptance/report-tables.md`：统一对比表（reward、组内方差、非零梯度 step、轨迹终止、OPD 三行、held-out）。
3. 把 `acceptance.json`、`verdict.json`、`delta.json`、`report-tables.md` 拷进 `docs/verl-uni-agent-harbor-opd-rl/<run-name>/`，commit + push。
4. 决定下一轮参数（见 SKILL §4），或换模型（`MODEL_PATH` / `TEACHER_MODEL_PATH`）。

## 5. 出问题时
| 现象 | 做法 |
|---|---|
| `spend limit` | Modal 控制台提额 → `FROM_STAGE=train` 重跑同一条命令 |
| `ImageBuildError … access denied` | 数据阶段会剥掉不可拉取的镜像别名；新来源把前缀加进 `STAGE1_STRIP_IMAGE_PREFIXES` |
| 某条 trial 30 分钟不动 | 等 `trial_timeout_sec`（40 分钟）自动杀；训练不会中断 |
| 要停 | 只杀自己的：`ps -eo pid,cmd \| grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo"`，`kill -TERM`，`ray stop --force`，然后把 `train/` 改名保留现场 |
| pod 重建 | 端口变、`/root` 凭据丢：回到 §1 |

## 6. 两台 pod 共用一个卷时
- 第二台起 pipeline 加 `SKIP_STAGES=data`（沿用已通过的数据），不要 `sync-source.sh --rsync --delete`。
- 各自用不同的 `PIPE_ROOT`。
- 源码 git 检出的换入（`src/uni-agent.git-checkout` → `src/uni-agent`）等所有 run 结束后做。

## 7. 参考
- 架构图：`docs/verl-uni-agent-harbor-opd-rl/architecture.html`
- 环境：`uv-runbook.md`；踩坑：`tasks/lessons.md`；交接：`tasks/handoff.md`
- 训练分析：`.claude/skills/rl-training-analyst/SKILL.md`
