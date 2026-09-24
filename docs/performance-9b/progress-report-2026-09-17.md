# 进度汇报：Uni-Agent × Harbor × VERL 训练通路（截至 2026-09-17 20:40 UTC）

## 终局目标

用 VERL 生态把"真实软件工程任务上的 agent 能力"训进模型，评测口径 Terminal-Bench 2.1。技术路线三步：
① terminus-2 + Modal 沙箱的纯 RL 通路 → ② DAPO + OPD（27B Teacher 逐 token 蒸馏）联合更新 → ③ DSH harness 接入沙箱。目标模型：Student Qwen3.5-9B，Teacher Qwen3.8-27B。

## 当前进度（事实）

| 里程碑 | 状态 | 证据 |
|---|---|---|
| 全流程脚本化（环境 → 数据 → oracle → rollout → 训练 → checkpoint 差分 → 断点续训 → 验收） | **完成，验收 PASS**（2026-09-16 16:47） | `docs/performance-9b/pipe-r1/acceptance.json` |
| 算法正确性（GRPO 组内 advantage、action mask、LoRA 权重变化） | **核实** | 重算 advantage 与 grad_norm 逐步吻合；504/504 adapter 变、399/399 base 不变 |
| 学习信号（reward 方差 → 非零梯度） | **出现**：pipe-r2 六步 grad_norm 0.053 / 0.0065 / 0.0091 / 0.0147 …，训练集 reward 0.19–0.60 | wandb `dzlqgapu` |
| 清理后数据集接入（`gump2049/xDAN-Harbor-Stage1-Tasks`） | **接入**：Terminal-Lego 20 题训练、5 题 held-out（仓库现有 50 题） | `runs/pipe-r2`、`runs/pipe-r3` |
| 路线 ② Teacher 接线（独立 GPU、prompt_logprobs、hybrid loss） | **打通**：双卡 pod 上 4B 自评 Teacher，`actor/distillation/*` 指标出现 | wandb `0jz8wq6h` |
| 27B Teacher / 9B Student 权重 | **就绪**（已下载到共享卷） | `/workspace/models/` |
| 训练前 held-out 基线（5 题） | 0.328（pipe-r2）/ 0.394（pipe-r3），同一模型的差异即噪声水平 | `runs/pipe-r*/train/agent-logs/*/step_0` |
| TB 2.1 官方基线（4B） | **初步 ≈ 0%**：两次评测（n=1 / n=3）有效样本 54 / 62 条全部未通过；因 Modal 额度中途触顶，样本不完整，需额度恢复后重跑 n=1 定为正式基线 | `runs/eval-tb21-4b-base-n1`、`-n3` |
| pipe-r2（stage1 20 题纯 RL）验收 | **PASS**（07:46）：7/7 步非零梯度且与 wandb 对账一致；resume 从 step 7 接续 | `docs/performance-9b/pipe-r2/acceptance.json` |
| 训练后 held-out（5 题 n=1） | 0.328 → 0.497（step 6）→ 0.458（step 7）；同一 checkpoint 两次评估相差 0.06，**5 题只能证明机制，不能证明提升** | wandb `dzlqgapu` / `eg1ix7eo` val-core |
| pipe-r3（4B 自评 Teacher，路线 ② 接线） | **验收 PASS**（12:10）：Teacher + 断点续训连续，7/7 步梯度非零，与 wandb 对账一致 | `docs/…/pipe-r3/acceptance.json` |
| TB 2.1 官方基线（4B，n=1，正式） | **0/66 有效通过**（上界约 4.5%），23 题因镜像构建/额度未完成；三次评测一致 | `docs/…/tb21-4b-baseline-n1/summary.json` |
| pipe-r4（9B Student + 27B Teacher，路线 ② 真 Teacher） | **验收 PASS**（20:07）：6 步 + 续训第 7 步，7/7 步梯度非零且与 wandb 一致，adapter 变 / base 不变；蒸馏 loss 0.10–0.13；长度 24.7k→14.4k 未暴涨；held-out 7 题 0.988→0.914 | `docs/…/pipe-r4/acceptance.json` |
| pipe-r7（9B 纯 RL，pipe-r4 的对照组） | **中断**：单卡 pod 约 15:52 起卡住，SSH 连不上；pod 恢复后按设置 v2 重起 | `runs/pipe-r7/chain.sh.v2` |
| SWE-rebench 数据源（22 道审计通过） | **已修复**：`docker_image` 跳过了 Dockerfile，已在本线与数据源头两处修掉，oracle 复验 3/3 | `docs/…/swe-ctrf-fix/` |
| Full 数据集（15.4k 题） | **数据阶段就绪**：按审计结果每个来源抽 50 道训练 + 20 道 held-out，实测 100 / 40、无重叠；下一轮使用 | `examples/harbor_opd_rl/stages/10_data.sh` |

基础设施：2 台 RunPod pod 共享一个网盘（单卡做评测，双卡做训练）；wandb 项目 `xDAN-Verl-Uni-agent-Harbor-rl-opd`；一条命令冷启动（`gpu-pod-restore.sh`）与一条命令训练（`run_tb21_pipeline.sh`）；agent 可执行的操作 skill 与人工手册各一份。

## 当前阻塞（12:25 UTC）
无硬阻塞。两台 pod 共跑 64 个并发沙箱（Tinker 线 16 个，已协调）。风险点：新 Modal 工作区偶发 App 创建限流；9B 与推理引擎同卡可能 OOM。早前的阻塞记录：凌晨 02:48/02:50 两台 pod 的 Ray 收到 SIGTERM（与本机断网同窗口），已改用 setsid 脱离会话启动并加信号日志；共享卷曾配额满（500 GB → 已扩 1 TB），已加 checkpoint 保留机制（最近 10 个、坏文件自动剔除）。

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
