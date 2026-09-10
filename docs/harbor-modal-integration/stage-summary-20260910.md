# 阶段总结与恢复导航 · 2026-09-10

本页用于 GPU 关机后的接续。**原生训练已真实执行，核心记忆课程的有效学习尚未验收；reader 诊断 CPU 工程包已完成，真实 GPU 诊断未执行。** 用户报告 GPU 已关闭，本轮没有连接服务器或启动任务。

## 1. 目标与当前节点

| 阶段 | 目标 | 当前结论 |
|---|---|---|
| P1 | DSH → Uni-Agent → VERL 在线 RL，真实消费、有效更新、checkpoint、独立 reload | 运行与消费有证据；core-train-r4 的有效更新未通过 |
| P2 | 同 harness、固定条件下训练前后任务收益及记忆消融 | 未完成，不能由脚本通过或提示改善推断 |
| P3 | 真实 offload/compact、跨会话恢复与跨场景能力 | 后续目标 |

长期希望模型按任务需要管理 handoff、task/goal、memory 与索引，保真保存、选择性检索、处理变更，在中断后可靠恢复工作。文件数量和压缩 token 数不是成功指标。DSH 调度与 RSI 目标保留；本轮先解决记忆链的真实学习信号。Harbor、异步、Modal、SFT 不作为当前前置。

## 2. 已完成及未通过的证据

- 数据资产：520 个训练实例、160 个公开开发实例已保存。此数字不是已消费任务数，也不代表相同数量的独立任务模板。
- `core-train-r4`：16 步、16 组、64 条 A/B 链、128 条唯一轨迹实际消费审计通过。但任务优势/梯度为 0、最终 LoRA B 为 0；**不认定有效学习**。
- 母 step16 独立 reload：WS01/03/05 执行审计通过、业务 reward 0；WS06 writer 达到限制，未执行 B、没有对应消费。
- 固定 `5e6b326` 预算修复：真实触顶 8192 token 并记录原因；正常路径 A1037/B302 token、1 组2条消费、exit0，业务 reward 0。预算控制通过，不等于任务能力提升。
- 正常 WS01 离线审计：A 保存了关键事实，B 未读取 memory，产生错误输出。它支持优先调查 reader 检索行为，不证明提示就是唯一原因。
- 最新 `2f3ea86` reader 工程包：prepare/check/run、一次冻结与多 B 隔离、原 verifier 复算、可信失败保留、版本/实际 runtime 预检、可恢复证据记录。898 项 CPU 测试通过，相关行覆盖率90%，Ruff 双门通过。**未部署 GPU，也未验证真实模型效果。**

详细证据：

- [当前验收目标](../../tasks/harbor-modal-integration/active-engineering-goal.md)
- [reader CPU 结果与测试范围](core-reader-role-diagnostic-cpu-result.json)
- [旧 GPU 归档](gpu-shutdown-checkpoint-20260910.md)
- [WS01 失败分析](core-budget-normal-r1-failure-analysis.md)

## 3. 固定版本与责任边界

| 项目 | 固定值/入口 |
|---|---|
| 工作区 | `.Codex/worktrees/harbor-modal-integration` |
| GitHub 分支 | `cryptoSUN2049/xDAN-DSH-uni-agent` / `worktree-harbor-modal-integration` |
| 本次可执行代码 | `2f3ea8688fc384ef437a3f8d0749edfedc58b9b7`；后续阶段总结提交只更新文档 |
| VERL | `fefb080262e1c015a0ea05f958822a6a512dc795` + `preserve-finish-reason-v1` overlay |
| DSH | `0.1.3a2`，源码 `b2369692ea530007075ebcd18d39fdba0bbd3982` |
| 基础模型 | `Qwen/Qwen3-4B`，revision `1cfa9a7208912126459214e8b04321603b3df60c` |
| 包/发布物 pin | `deployment/versions/g1-deployment-lock.json` 及配套清单 |

训练集成由本项目负责；DSH 本体与历史研究由 xDAN-DSH-Exp 负责。不得自动升级 SDK/runtime 或重复实现一套 DSH 外层 Agent Loop。诊断复用 Gateway 的真实 token 采集，但不启动 VERL trainer、不提交 TQ、不产生参数更新。

## 4. 本机备份及未覆盖部分

本轮重新核验三份原始证据 tar：总计 **51,176,549 bytes**，SHA256 全部与既有清单一致；归档可读取。位置：本 worktree 的 `outputs/gpu-shutdown-20260910/`。

另新建代码快照 `outputs/stage-checkpoint-20260910-2f3ea86/uni-agent-source-2f3ea86.tar.gz`：5,922,999 bytes；**967 个 Git blob 内容逐项核验**。这是固定 integration 源码快照，子模块实际内容、Python 环境、模型及 ignored outputs 不在该 tar 内；恢复 VERL 仍需固定版本与 overlay。

哈希、绝对路径与校验时间统一记录在 [备份清单](stage-backup-20260910.json)。阶段总结与交接文档还会复制进该本机备份目录；其独立文件哈希保存在目录内 `handoff-files.json`。

**模型 checkpoint 尚未下载到本机。** 历史保存位置为 `/workspace/uni-agent-g1/checkpoint/core-train-r4/global_step_8`、`global_step_16`，关机后可用性待重连确认。不要误称“全部模型已备份”。本机 outputs 被 Git 忽略，不在 GitHub；清理/删除 worktree 前必须先迁走这些归档。

## 5. 下次最短恢复路径

1. 先读 [冷启动检查点](../../tasks/harbor-modal-integration/checkpoint-20260910-reader-ready.md) → [handoff](../../tasks/harbor-modal-integration/handoff.md) → [reader 操作指南](core-reader-role-diagnostic-runbook.md)。
2. 获得新 SSH 地址，检查 `/workspace` 是否同一卷；校验归档、模型、checkpoint、持久 Python 与 venv。旧 IP/PID/MIG UUID 不可复用。
3. 优先复用 `/workspace/venvs/uni-agent-rebuild-cf2d3f5`。其解释器在 `/workspace/tools/uv-python/cpython-3.12.3-linux-x86_64-gnu/bin/python3.12`；按 [GPU 恢复指南](gpu-reconnect-runbook.md) / [宿主恢复设计](pod-recovery-design.md) 补宿主缺口，先检查再决定是否重装。
4. Git 拉取后建立固定源码 checkout，验证 paired VERL overlay、真实 SDK/runtime 和绝对 import 路径。新机器重新发现 GPU/MIG，核实其他会话进程归属，不抢占。
5. 按 reader 操作指南：新目录 `prepare --canary` → `check` → `run`。实际 DSH 父环境必须设置 `DSH_RUNTIME_MODE=exe`、绝对 `PYTHONPATH`。不能拿旧 manifest 直接启动。
6. Canary 通过执行/证据合同后，固定代码与提示，新目录准备16题比较。每题1个A，原/新提示各4个B；4次是重复采样，不是新任务或训练组。不得补采成功覆盖失败。
7. 用逐题结果判断是否存在可信成功路径与奖励区分度，再回归原生 RL。验收实际任务消费、组内优势、有限非零梯度、参数变化、checkpoint 与独立 reload；固定 harness 下另做训练前后对照。

若没有 GPU，仍可读取本机证据和代码，但不要虚构后台训练。无须再批准已经批准的 reader 实现；新服务器地址和云盘可用性是恢复执行所需信息。
