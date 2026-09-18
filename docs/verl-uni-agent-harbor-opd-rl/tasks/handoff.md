# Handoff：verl-uni-agent-harbor-opd-rl

更新：2026-09-18 07:40 UTC。历史逐轮记录在 `handoff-history.md`，持久决策与每轮记录在 `memory.md`（按时间追加），踩坑在 `lessons.md`（46 条），任务清单与每轮计划在 `todo.md`（最新是阶段 H5），成本复盘在 `../modal-cost-postmortem.md`。

## 1. TL;DR

- **目标**：用 VERL 把真实软件工程任务上的 agent 能力训进 Qwen3.5-9B，评测口径 Terminal-Bench 2.1。三步路线：① terminus-2 + Modal 沙箱的纯 RL 通路 → ② RL 加 27B Teacher 蒸馏（OPD）→ ③ DSH harness 进沙箱。① 和 ② 的机制都已跑通（pipe-r4 于 2026-09-17 验收 PASS）。
- **正在跑：pipe-r11**（双卡 pod 11965，2026-09-18 06:09 UTC 启动，wandb `xf24vrka`）。9B 学生 + 27B Teacher，100 道题、20 步，二值奖励。07:36 时在第 2/20 步。预计 15:30–16:00 UTC 全部结束（训练 → 权重差异 → 续训 → 汇总 → 验收 → 成本核验，全自动）。它还在训练，不是对比测试。
- **为什么是 r11**：pipe-r9 用了"按测试通过比例"的部分分奖励，SWE 题什么都不改也能拿约 0.94 分（`../pipe-r9/reward-floor-finding.md`），06:07 在第 4 步停掉，改二值奖励原样重开。pipe-r10 这个编号留给单卡上去掉 Teacher 的对照组。
- **已知数字**：训练前验证 3/8 解决（0.375）；第 1 步 32 条解决 15 条，4 道题里只有 1 道组内有对有错（其余全对或全错，没有 RL 梯度）。
- **待负责人决定**：Modal 额度余量约 18 美元（账期约 400、上限 500，Tinker r6 约 60、本轮约 20），建议调高；单卡 pod（12063）需在 RunPod 控制台重启，才能跑对照组；是否把训练拉到 50 步（2 个 epoch，约 20 小时、约 50 美元）。

## 2. 一条命令起一轮训练

```bash
ssh -p 11965 -i ~/.ssh/id_ed25519 root@157.157.221.177
cd /workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent

# 换模型或换配置后，先冒烟（约 6 分钟，不占 GPU）
bash examples/harbor_opd_rl/launch-detached.sh \
  /workspace/verl-uni-agent-harbor-opd-rl/runs/<run>-smoke/driver.log \
  "ROUND=<run>-smoke TEACHER=1 bash examples/harbor_opd_rl/run_opd_round.sh --smoke"

# 正式一轮（pipe-r11 用的就是这条）
bash examples/harbor_opd_rl/launch-detached.sh \
  /workspace/verl-uni-agent-harbor-opd-rl/runs/<run>/driver.log \
  "ROUND=<run> TEACHER=1 TRAIN_STEPS=20 HARBOR_REWARD_MODE=binary bash examples/harbor_opd_rl/run_opd_round.sh"
```

默认值：数据切片 `stage1-swe50e-tl50m-v1`（SWE easy 50 + Terminal-Lego medium 50，验证 4 + 4）；9B 学生 prefix caching、单批 8192、显存比例 0.45；27B Teacher 整卡、显存比例 0.70、单批 4096、最多 4 条序列；并发 16；二值奖励。对照组把 `TEACHER=1` 改成 `TEACHER=0`，其余不变。

代码同步到 pod：本机 `bash deployment/bootstrap/sync-source.sh 11965 --rsync`（有 run 在跑时不要同步它正在执行的脚本）。

停一轮：`launch-detached.sh` 的输出里有会话号 sid，`pkill -TERM -s <sid>` 结束整轮（含 Ray 与 vLLM），再 `HARBOR_MODAL_APP=verl-harbor bash deployment/bootstrap/modal-sandbox-cleanup.sh --apply --older-than 0` 清掉在跑的沙箱。

## 3. 设计约束（铁律）

- Uni-Agent owns Agent/Task/Gateway/轨迹准入；VERL owns optimizer；Harbor owns verifier；Modal 只做沙箱。
- 验收看三层：机制（阶段 PASSED）、动力学（wandb 与 train.log 逐步一致）、权重（delta + resume 连续）。`80_acceptance.sh` 给 PASS / MECHANICS_ONLY / FAIL。
- **奖励默认二值**。部分分只能按 `fail_to_pass` 计，不能把修复前就通过的测试算进分母。换数据或换奖励前先算"什么都不做"能拿多少分（`../pipe-r9/reward_floor_audit.py`）。
- **看效果要看二值解决率**，不只看奖励均值。wandb 的第 N 步指标要等第 N+1 步写入才出现；实时看 `train/rollouts/*/*/<N>.jsonl`。
- 每次 push 前 `ruff check .` 与 `ruff format --check .`，不接管道。
- 资产只放 `/workspace`；凭据只放 pod 的 `/root` 与本机 home，不进仓库。
- 两台 pod 共享 `/workspace` 与同一份源码；每条 run 用独立 `DATA_DIR`（`run_opd_round.sh` 自动按 run 名分开）。
- **列 PID 与杀 PID 必须分两条命令**，杀的那条只出现数字。

## 4. 成本纪律

| 规则 | 落地位置 |
|---|---|
| 沙箱生命周期在创建时传入，Modal 服务端强制 | `tb21_terminus2_smoke.yaml` 与 `tb21_oracle.yaml` 的 `environment_kwargs`：寿命 2700 秒、空闲 1200 秒回收、独立应用 `verl-harbor` |
| 沙箱规格按任务契约，不统一覆盖 | 同上（`override_cpus`/`override_memory_mb` 留空） |
| 每轮结束自动核验账单 | `stages/90_cost.sh` → `cost_report.py`：按小时取本轮应用的账单，Sandbox 单价折算；门槛计费/实用 ≤ 1.5、每条 ≤ 0.05 美元、残留 0；测不到记失败 |
| 杀训练后清理在跑的沙箱 | `modal-sandbox-cleanup.sh --apply`（手动兜底） |
| 换配置先冒烟 | `run_opd_round.sh --smoke` |

单价：Modal 沙箱每核每小时约 0.142 美元、内存每 GiB 每小时约 0.024 美元（是 Function 单价的 3 倍）。pipe-r9 停止时实测每条 trial 0.031 美元、计费/实用 1.0、残留 0。

## 5. 与 Tinker 训练线的协作（会话 `xdan-dsh-uni-agent-e1`）

- 共用同一个 Modal 工作区和额度。Tinker 线 r6 于 05:14 UTC 启动，预计 11–16 小时。
- **共享评估集 eval-set-v1**：保留名单在 `gump2049/xDAN-Harbor-Stage1-Tasks-Full` 的 `eval-set-v1/reserved.json`，我们的数据阶段默认剔除。100 道正式清单到位后，用作两条线共同的 held-out。
- Tinker 线的 SWE 奖励一直是二值的；他们 r5 的失败原因（上下文超限、任务时限不执行）已在本线核查，见 `memory.md` 2026-09-18 05:25 一节。
- 周报：`docs/tinker-cookbook-opd-rl/weekly/2026-W38.md`（在 Tinker 的 worktree 里，由 e1 合并）。

## 6. 下一里程碑

1. pipe-r11 跑完 → 按 `todo.md` H5 的四条判据下结论（成本、机制、学习信号、长度副作用）。
2. 同题重跑：用最终 checkpoint 在第 1–5 步的 20 道题上各跑 8 条，与训练时的解决率比较（脚本待写）。
3. 前 5 步"组内有对有错"的题若 < 25%：下一轮先按难度筛题或加大每步题数。
4. 单卡 pod 恢复 → pipe-r10 对照组（同配置、`TEACHER=0`）。
5. 下一轮待改（每轮只改一个变量）：智能体时限改为任务声明值 × 倍数；轮数上限 50 → 30 的对比；数据阶段加"什么都不做得分"关卡。
6. 共享评估集到位 → 复测 pipe-r4、pipe-r11 的 checkpoint。

## 7. 冷启动 checklist

1. 读本文件 → `todo.md` 的 H5 → `memory.md` 最后三节 → `lessons.md` 第 44–46 条。
2. `git log -3 --oneline`，确认 HEAD 已推送。
3. 双卡 pod：`ssh -p 11965`，`nvidia-smi`；看进度：`tail runs/pipe-r11/driver.log`、`grep -a "Training Progress" runs/pipe-r11/train/train.log | tail -1`、`cat runs/pipe-r11/pipeline-summary.jsonl`。
4. 效果：`python docs/verl-uni-agent-harbor-opd-rl/pipe-r9/resolve_by_step.py <run 目录>`（按步、按来源的二值解决率）。
5. 单卡 pod：`ssh -p 12063`；连不上说明还没重启，端口变了先跑 `gpu-pod-restore.sh <新端口>`。
6. 每个节点 commit/push，关键事实写 `memory.md`，踩坑写 `lessons.md`。
