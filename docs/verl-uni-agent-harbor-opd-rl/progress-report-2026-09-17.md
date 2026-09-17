# 进度汇报：Uni-Agent × Harbor × VERL 训练通路（截至 2026-09-17 09:20 UTC）

## 终局目标

用 VERL 生态把"真实软件工程任务上的 agent 能力"训进模型，评测口径 Terminal-Bench 2.1。技术路线三步：
① terminus-2 + Modal 沙箱的纯 RL 通路 → ② DAPO + OPD（27B Teacher 逐 token 蒸馏）联合更新 → ③ DSH harness 接入沙箱。目标模型：Student Qwen3.5-9B，Teacher Qwen3.8-27B。

## 当前进度（事实）

| 里程碑 | 状态 | 证据 |
|---|---|---|
| 全流程脚本化（环境 → 数据 → oracle → rollout → 训练 → checkpoint 差分 → 断点续训 → 验收） | **完成，验收 PASS**（2026-09-16 16:47） | `docs/verl-uni-agent-harbor-opd-rl/pipe-r1/acceptance.json` |
| 算法正确性（GRPO 组内 advantage、action mask、LoRA 权重变化） | **核实** | 重算 advantage 与 grad_norm 逐步吻合；504/504 adapter 变、399/399 base 不变 |
| 学习信号（reward 方差 → 非零梯度） | **出现**：pipe-r2 六步 grad_norm 0.053 / 0.0065 / 0.0091 / 0.0147 …，训练集 reward 0.19–0.60 | wandb `dzlqgapu` |
| 清理后数据集接入（`gump2049/xDAN-Harbor-Stage1-Tasks`） | **接入**：Terminal-Lego 20 题训练、5 题 held-out（仓库现有 50 题） | `runs/pipe-r2`、`runs/pipe-r3` |
| 路线 ② Teacher 接线（独立 GPU、prompt_logprobs、hybrid loss） | **打通**：双卡 pod 上 4B 自评 Teacher，`actor/distillation/*` 指标出现 | wandb `0jz8wq6h` |
| 27B Teacher / 9B Student 权重 | **就绪**（已下载到共享卷） | `/workspace/models/` |
| 训练前 held-out 基线（5 题） | 0.328（pipe-r2）/ 0.394（pipe-r3），同一模型的差异即噪声水平 | `runs/pipe-r*/train/agent-logs/*/step_0` |
| TB 2.1 官方基线（4B） | **初步 ≈ 0%**：两次评测（n=1 / n=3）有效样本 54 / 62 条全部未通过；因 Modal 额度中途触顶，样本不完整，需额度恢复后重跑 n=1 定为正式基线 | `runs/eval-tb21-4b-base-n1`、`-n3` |
| pipe-r2（stage1 20 题纯 RL）验收 | **PASS**（07:46）：7/7 步非零梯度且与 wandb 对账一致；resume 从 step 7 接续 | `docs/verl-uni-agent-harbor-opd-rl/pipe-r2/acceptance.json` |
| 训练后 held-out（5 题 n=1） | 0.328 → 0.497（step 6）→ 0.458（step 7）；同一 checkpoint 两次评估相差 0.06，**5 题只能证明机制，不能证明提升** | wandb `dzlqgapu` / `eg1ix7eo` val-core |
| pipe-r3（4B 自评 Teacher，路线 ② 接线） | **train + delta PASS**（08:30）：6 步梯度全非零，`distillation/*` 全程在线；resume 在 step 7 保存后被 Modal 额度打断，额度恢复后自动续跑 | wandb `pg4xsj19`、`docs/…/pipe-r3/` |
| TB 2.1 官方基线（4B，n=1，正式） | **0/66 有效通过**（上界约 4.5%），23 题因镜像构建/额度未完成；三次评测一致 | `docs/…/tb21-4b-baseline-n1/summary.json` |

基础设施：2 台 RunPod pod 共享一个网盘（单卡做评测，双卡做训练）；wandb 项目 `xDAN-Verl-Uni-agent-Harbor-rl-opd`；一条命令冷启动（`gpu-pod-restore.sh`）与一条命令训练（`run_tb21_pipeline.sh`）；agent 可执行的操作 skill 与人工手册各一份。

## 当前阻塞（09:20 UTC）
**Modal spend limit 第三次触顶**（06:46 加的 $10 在 2.5 小时内用完：pipe-r3 约 1000 个沙箱 + 基线 89 个）。这是工作区"账期上限"设置，需要在 Modal 设置里调高，而不只是充值。pod 上已布置额度探针链，恢复后 pipe-r3 resume/验收自动完成。早前的阻塞记录：凌晨 02:48/02:50 两台 pod 的 Ray 收到 SIGTERM（与本机断网同窗口），已改用 setsid 脱离会话启动并加信号日志；共享卷曾配额满（500 GB → 已扩 1 TB），已加 checkpoint 保留机制（最近 10 个、坏文件自动剔除）。

## 今天解决的阻塞
Modal 消费上限、pod 两次重建、Modal API 挂起（加 trial 级超时与失败补组）、小数据集 epoch 上限、二值 reward 全 0（改用 verifier 部分得分）、数据集镜像别名不可拉取。全部记入 `tasks/lessons.md`（15 条）。

## 离"能力提升"还差什么

| 层次 | 判据 | 预计 |
|---|---|---|
| 训练集 reward 明显上升 | 41 题 1–2 epoch（20–40 步），平滑曲线单调上升 | 6–12 小时训练 |
| 同分布 held-out 提升 | held-out ≥ 30 题、n ≥ 4，+10 点且 CI 不跨 0 | 依赖数据扩批（Tinker 线发布） |
| Terminal-Bench 2.1 提升 | 89 题、同 harness、n=3，+3–5 点且 CI 不跨 0；需 9B Student + 27B OPD + ≥500 题 + 200–500 步 | 约 1–2 周 |

## 下一步（已排程）
1. pipe-r2 验收 → 单卡 pod 跑 4B TB 2.1 基线（n=1，约 1 小时）。
2. pipe-r3 结束 → 双卡 pod 起 pipe-r4：41 题 + 27B Teacher OPD，30 步，观察 Teacher 吞吐与 `distillation/loss`。
3. 数据扩批后：held-out 扩到 30 题；Student 换 9B；开 DAPO。

## 需要的决策 / 资源
- 数据扩批（Terminal-Lego 15k 派生更多批次）由 Tinker 线发布，本线只改切片参数。
- Modal 每日额度需覆盖约 300 个沙箱。
- 更大显存 GPU 是吞吐优化，不是能力缺口（2 卡已覆盖完整算法）。
