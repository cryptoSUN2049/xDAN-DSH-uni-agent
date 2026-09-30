# MiMo 五领域实现与真实训练覆盖

截至 2026-09-30 07:55 UTC，用户因账户无余额暂停续训推进，尚未完整复刻并验收五个领域。当前已验收的是 **Code 单任务小样本工程闭环**；R20 多任务 Code 顺序课程准备不能替代其他领域的训练验收。

| 领域 / 数据子集 | 本 worktree 的实际验收范围 | 尚缺的完成证据 |
|---|---|---|
| Code / code | task 001661：真实双卡 world2/FSDP1、DSH/Harbor/Modal、独立评分、有效 GRPO 更新、C3→C4 原生恢复、W&B 原生 API 对账；新任务002549生产源码/原Python无注入校准0/0/1，原生两rank恢复C4与policy4采样已实证；当前W&B API crashed/history0、step5更新未验收 | 新增任务真实训练消费及逐任务参数更新尚未完成；002857/000466候选校准0/0/0未放行；全量 Code 训练未验收 |
| Cyber / cyber | 未取得本链路真实训练验收 | 漏洞环境、工具与规则 verifier 适配，真实采样和更新 |
| General / general | 未取得本链路真实训练验收 | 环境资产/状态与业务工具、rubric judge，真实采样和更新 |
| Visual / webdev | 未取得本链路真实训练验收 | 浏览器渲染、视觉 grader 与训练奖励协议，真实采样和更新 |
| Music / music | 未取得本链路真实训练验收 | ABC 生成/转换及规则评分的独立路径，真实采样和更新 |

Code 验收以 [R19 最终报告](r19-final-acceptance-20260930.md) 和其中绑定的原始证据为准。R20 的实际冻结数据与镜像见 [数据清单](evidence/r20-dataset-inventory.json)、[镜像构建结果](evidence/r20-task-images-build-final.json)。镜像构建、候选修复、CPU 探针和正负例校准均不是模型训练完成证明。

新任务原始 Python 兼容问题已修复并经62项云CPU回归、原镜像3.9/3.10/3.11无注入合成 CLI测试；参见 [兼容设计及产物组装合同](r20-original-python-compat-design.md)。002549 新task_ref为`sha256:d0ae13a84e57d3f616a1cef5f17bd76819bba5c4f4a6faa58706e710be106979`；其实际生产校准与先前操作层兼容校准分开，不沿用旧task_ref。

## 复刻含义与架构边界

本项目使用固定 MiMo 模型/数据和逐任务原始环境，采用 DSH harness、Harbor/Modal、VERL FSDP/LoRA 实现云端闭环。这是功能适配路线；不能称已原封不动重现 XiaomiMiMo 的 mimoagent/K8s/Megatron 配方或报告结果。原始五域路径差异与接口不兼容已记录在 [集成设计](mimo-dsh-integration-design.md)。

当前统一 worker/policy 仍固定一个任务及一个 DSH image。R20 采用每任务独立 run/spec/image、原生 checkpoint 连续恢复的顺序课程；不会宣称单 run 混合采样或跨领域联合训练。

## 后续验收顺序

1. 在已授权四小时窗口内完成所选 Code 小数据集；分别记录校准、真实消费、有效更新、checkpoint、W&B/Insight 和所属资源清理。未完成任务保留未完成状态。
2. 若目标升级为五领域覆盖，先冻结每域至少一个任务及明确的独立 grader 合同，分别做真实 smoke/update/recovery 验收。是否复用 DSH 由各域执行需求决定。
3. 五域独立验收后，再评审混合调度、奖励尺度与批次分组；不同领域奖励不直接视为同一语义。领域覆盖通过也不等于原配方/全数据/能力提升复现。

最新停止推进与恢复边界见 [R20暂停交接](r20-paused-status-20260930.md)。云端存储、C5和所属资源清理尚未复核，不能沿历史running快照宣称本轮已成功。
