# 八类真实 smoke：进度与 GPU 决策

核查日期：2026-09-07。当前工作分支 `worktree-dsh-v3-live-smoke`，
目录 `.Codex/worktrees/dsh-v3-live-smoke`。冷启动先读
[本 worktree handoff](../../tasks/dsh-v3-live-smoke/handoff.md)。

## 当前结论

**现在不需要购买 GPU。** 当前交付目标是完成 CPU 执行准备；八类真实模型
episode 仍为 **0/8**，没有启动本轮训练、部署或付费调用。

| 层级 | 已有事实 | 尚未达到 |
| --- | --- | --- |
| M0 CI | `a197ead` 修复固定 VERL 测试替身及 Ruff import 分类；已推送 dsh-adapter，五项 workflows 成功 | 当前 worktree 新代码须独立验证 |
| v3 数据 | 8 families、8 seed、24 CPU cases；16 eligible、8 passed、8 tamper rejected；两次生成字节一致 | 不是模型执行结果 |
| M1 CPU | 冻结输入、运行监督、episode 新目录、UID 预登记、实际 TQ 读回记录、审计及产物封存已实现；208 项聚焦回归通过 | 完整 Linux 依赖环境与真实运行验收 |
| M1 GPU | 未创建本轮 GPU；真实执行 0/8 | 固定环境、八类真实轨迹、回执及 token 关联验收 |
| 后续训练 | 历史 v2 更新、reload 证据保留原资格限制 | 新 C4 实跑、P5 paired uplift、P6 隔离和复用验收 |

M0 CI：[Python Backend CI](https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/actions/runs/34084230958)。
该结果只覆盖 `a197eadae3b3f4150f12044faa1c0b1c4e62c9fe`；不代替新提交 CI。

本轮实现提交：`27f7efa`（严格推理与 episode 目录）、`3220216`（CPU 编排及审计）。
四个修改模块含分支覆盖率分别为：runner 87%、auditor 99%、inference CLI 95%、
task_runner 90%。[验证清单](verification.json) 记录精确范围、文件 hash 和报告位置。

本机全仓尝试为 744 passed / 7 failed / 2 skipped，另有 19 subtests passed；
它包含聚焦范围，不能与 208 相加。5 项失败缺 vLLM，1 项缺 Pillow（经 VERL
导入），这 6 项已在未修改基线 `a197ead` 复现。另 1 项 localhost 返回 502，
去除代理后基线复测通过。因此不宣称本轮完整 CI 已通过；新 PR 保持 Draft。

## 与 DSH 交接记录的关系

DSH `dsh-official-training` 的 `1af5b00d68` 已完成数据核验和执行器设计。
本 worktree 已继续推进实现，因此 **CPU 工程进度在该记录之后**；真实 smoke
仍同为 0/8。不能把新增单元测试数换算成真实任务通过数。

本项目保留状态、设计、交接和来源指针，避免冷启动依赖另一个仓库。DSH 原资料
仍作为跨仓历史来源，不复制成第二份可独立改写的训练成绩账本。
详细历史与 P0–P6 限制见 [项目状态](../dsh-adapter/project-status.md)。

## 开 GPU 的具体前置条件

1. 本轮 CPU 聚焦回归已通过；部署前需在完整 Linux 依赖下重跑 CI、prepare 和 dry-run。
2. 恢复可重建的 DSH source/Linux runtime，记录实际执行的 node closure 或 exe；
   不用未执行文件的 hash 代替运行身份。旧 DSH pin 当前不可取得。
3. 固定 Qwen3-4B 模型、tokenizer、VERL 及 GPU 依赖；部署清单须有实际文件 hash。
4. 确定并验证独立计时停机与资源删除机制；workload timeout 只结束进程，
   不能保证 RunPod 停费。费用和截止时间仍须在实际购买前确认。

此前的单卡 RTX 4090 / 两小时 / 含存储 $2 仅为设计建议，未获购买授权；报价
和库存应在创建前重查。无须现在提前充值、租长期机器或扩到多卡。

## 全局目标与下一步

全局目标是证明 Qwen3-4B 经固定 DSH / Uni-Agent / VERL 训练后，在相同预算、
verifier 和未见任务上优于 frozen base；后续再验证 Harness candidate 的隔离、
复用、canary 与 rollback。模型能启动和 optimizer 能更新都只是中间证据。

短期顺序：CPU 执行准备 → 可复建 Linux 环境及停止机制 → 短时八类 inference
smoke → 96 candidate / 32 sealed holdout / 24 demonstrations → base 校准及
累计预算约束 → GRPO / DAPO 对照 → 独立 reload / paired holdout。
M1 的 `training_eligible` 始终为 false。
