# Handoff：verl-uni-agent-harbor-opd-rl

更新：2026-09-18 01:00 UTC。历史逐轮记录在 `handoff-history.md`，持久决策在 `memory.md`，踩坑在 `lessons.md`（41 条），任务清单在 `todo.md`，成本复盘在 `../modal-cost-postmortem.md`，替代沙箱调研简报在 `../modal-alternatives-brief.md`。

## 1. TL;DR

- **目标**：用 VERL 生态把真实软件工程任务上的 agent 能力训进模型，评测口径 Terminal-Bench 2.1。三步路线：① terminus-2 + Modal 纯 RL 通路 → ② DAPO + OPD（Teacher）联合更新 → ③ DSH harness 进沙箱。
- **路线 ① 与 ② 的机制都已闭环**：pipe-r1/r2（4B 纯 RL）、pipe-r3（4B 自评 Teacher）、**pipe-r4（Qwen3.5-9B Student + Qwen3.8-27B Teacher）2026-09-17 20:07 验收 PASS**。证据在 `../pipe-r4/`，wandb `m848n94f`。
- **效果尚未验证**。pipe-r4 只有 6 步、held-out 只有 7 道且训练前就 0.988（饱和），得分从 0.988 降到 0.914 属噪声，不能当作退步或提升。
- **当前两个硬阻塞**：Modal 工作区账期花费上限触顶（两条线都建不了沙箱，需工作区所有者在后台调高）；单卡 pod（端口 12063）自 2026-09-17 15:52 起 SSH 无响应，需在 RunPod 控制台重启。
- **昨天烧了 358 美元**，主因是 Harbor 的 Modal 沙箱默认活 24 小时且进程被杀不销毁。修复已落地，见第 4 节。

## 2. 一条命令起一轮训练

```bash
ssh -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177
cd /workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent

# 换模型或换配置后，先冒烟（1 步 4 题，几十条沙箱）
bash examples/harbor_opd_rl/launch-detached.sh \
  /workspace/verl-uni-agent-harbor-opd-rl/runs/<run>-smoke/driver.log \
  "ROUND=<run>-smoke TEACHER=1 bash examples/harbor_opd_rl/run_opd_round.sh --smoke"

# 正式一轮
bash examples/harbor_opd_rl/launch-detached.sh \
  /workspace/verl-uni-agent-harbor-opd-rl/runs/<run>/driver.log \
  "ROUND=<run> TEACHER=1 TRAIN_STEPS=20 bash examples/harbor_opd_rl/run_opd_round.sh"
```

`run_opd_round.sh` 的默认值就是 pipe-r4 验证过的配置：9B 学生开 prefix caching、单批 8192、显存比例 0.45；27B Teacher 显存比例 0.70、单批 4096、最多 4 条序列；并发 16；数据取审计通过、剔除共享评估集、只要 medium/hard；内置模型本地暂存、等 Modal 额度、等前一条 run 退出、开跑前清理泄漏沙箱。对照组把 `TEACHER=1` 改成 `TEACHER=0` 即可，其余保持一致。

## 3. 设计约束（铁律）

- Uni-Agent owns Agent/Task/Gateway/轨迹准入；VERL owns optimizer；Harbor owns verifier；Modal 只做沙箱。
- 验收看三层：机制（阶段 PASSED）、动力学（wandb 与 train.log 逐步一致）、权重（delta + resume 连续）。`80_acceptance.sh` 给 PASS / MECHANICS_ONLY / FAIL。
- 每次 push 前 `ruff check .` 与 `ruff format --check .`，不接管道。
- 资产只放 `/workspace`；凭据只放 pod 的 `/root`，不进仓库。
- 两台 pod 共享 `/workspace` 与同一份源码：有 run 在跑时不要覆盖它正在执行的脚本（`40_train.sh`、`60_resume.sh`、`run_tb21_pipeline.sh`）；每条 run 用独立 `DATA_DIR`。
- **列 PID 与杀 PID 必须分两条命令**，杀的那条只出现数字。

## 4. 成本纪律（2026-09-18 新增）

| 规则 | 落地位置 |
|---|---|
| **沙箱生命周期在创建时传入，服务端强制** | `tb21_terminus2_smoke.yaml` 的 `environment_kwargs`：`sandbox_timeout_secs=2700`、`sandbox_idle_timeout_secs=1200`、`app_name=verl-harbor` |
| 沙箱规格按任务契约，不统一覆盖 | `tb21_terminus2_smoke.yaml`（`override_cpus`/`override_memory_mb` 留空） |
| trial 超时 1800 秒 | 同上 |
| 杀训练后必须清理泄漏沙箱 | `deployment/bootstrap/modal-sandbox-cleanup.sh --apply` |
| 清理脚本与守卫（兜底，不常驻） | `deployment/bootstrap/modal-sandbox-{cleanup,guard}.sh`，只在怀疑泄漏时手动用 |
| 每轮开跑前自动清理一次 | `run_opd_round.sh` |
| 换配置先冒烟 | `run_opd_round.sh --smoke` |
| 并发 16（与 Tinker 线约定，峰值 48） | `run_opd_round.sh` 默认值 |
| 规格与生命周期实测 | `deployment/bootstrap/modal-sandbox-probe.sh`，额度恢复后先跑它 |

## 5. 与 Tinker 训练线的协作（会话 `xdan-dsh-uni-agent-e1`）

- **共享评估集 eval-set-v1**：保留名单已冻结在 `gump2049/xDAN-Harbor-Stage1-Tasks-Full` 的 `eval-set-v1/reserved.json`，我们的数据阶段默认剔除。100 道正式清单（50 SWE + 50 Terminal-Lego，基座时对时错）待 Modal 恢复后产出，届时用作两条线共同的 held-out。
- **他们的关键发现**：9B + 27B 蒸馏后输出暴涨、留出题退步（15/16 → 11/16）。我们 pipe-r4 没有重现，轨迹长度反而从 24.7k 降到 14.4k。两边配置差异（二值 vs pass_ratio、有无 KL 惩罚、组大小 4 vs 8）正好用于交叉验证。
- **数据事实**：Terminal-Lego 全集 easy 9223 / medium 4440 / hard 153，按 index 顺序取几乎全是 easy；9B 在未筛选题上得 0.92，学不到东西，所以默认只取 medium/hard。

## 6. 下一里程碑

1. Modal 额度恢复 → 自动跑 `runs/pipe-r8-smoke`（已排队）；先跑 `modal-sandbox-probe.sh` 确认规格与销毁行为。
2. 冒烟通过 → 正式一轮：9B + 27B Teacher，20 步以上，100 道按难度筛的题，held-out 换成共享评估集。
3. 单卡 pod 恢复 → 同参数、`TEACHER=0` 的对照组，用于分离 Teacher 的贡献与开销。
4. 用共享评估集复测 pipe-r4 的 checkpoint，确认 0.988 → 0.914 是不是噪声。
5. 之后：开 DAPO、扩到 500 题、Terminal-Bench 2.1 正式评测。

## 7. 冷启动 checklist

1. 读本文件 → `todo.md` → `memory.md` 末节 → `../modal-cost-postmortem.md`。
2. `git log -3 --oneline`，确认 HEAD 已推送。
3. 双卡 pod：`ssh -p 11965`，`nvidia-smi`、`tail runs/modal-guard.log`（守卫是否在跑）、`bash deployment/bootstrap/modal-quota-wait.sh --once`（额度是否恢复）。
4. 单卡 pod：`ssh -p 12063`；连不上说明还没重启，端口变了要先跑 `gpu-pod-restore.sh <新端口>`。
5. 起跑用第 2 节的命令；监听只看阶段结果、checkpoint、OOM、额度、显存告警。
6. 每个节点 commit/push，关键事实写 `memory.md`，踩坑写 `lessons.md`。
