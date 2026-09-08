# 当前主线：原生DSH训练工程与四类能力

更新：2026-09-09。用户明确重新设计原生优先；Harbor训练暂停，非本阶段必需项。

权威设计：[系统方案v3](../../docs/harbor-modal-integration/uni-agent-system-plan-v3.html)；[任务与合同](../../docs/harbor-modal-integration/native-capability-roadmap.md)。用户已批准v3实施，按有界作业与分阶段验收推进。旧G1完整保存于engineering-goal-before-native-redesign-20260909.md，不删除失败或通过证据。

## 目标

复用固定DSH 0.1.3a2 + Uni-Agent + 配对VERL，优先跑通DSH调度、跨会话记忆、上下文管理、受控RSI四类真实任务，再以固定模型/任务/配置/verifier独立重跑验证结果复现。环境从零安装作为后续交付项，不阻塞能力主线。工程、能力、泛化与性能分别验收，不以checkpoint变化代替能力提升。

## 节点

- [x] M1原生最小RL：真实更新、消费审计、独立reload与公开留出评估通过。
- [x] Harbor Docker资产/清理恢复验证保留；后续学生RL暂停。
- [ ] N0-R 结果复现：四类任务真实完成后，以独立新run重跑任务/评分/reload，记录确定性与采样波动。
- [ ] N0-E 环境复建：后续工程交付，非四能力前置；已有新venv保留。
- [ ] N1 四能力动作/数据/奖励合同与真实基线。
- [ ] N2 DSH调度独立任务能力实验。
- [ ] N3 记忆与上下文分别验收，再组合。
- [ ] N4 受控候选生成/验证/晋升/回滚及RSI学习。
- [ ] N5 四类封存评估与可复建模型发布。
- [ ] P1 能力任务可运行后单卡colocate_async有界对照；不阻塞N2，不新增GPU。

## 固定约束

Uni-Agent 89733ec81a69c3cc93ac90479de7ea7f01e51c1f；VERL fefb080262e1c015a0ea05f958822a6a512dc795；DSH b2369692ea530007075ebcd18d39fdba0bbd3982 / 0.1.3a2。每run另固定完整集成commit、模型、任务/verifier/Harness摘要与实际安装清单。保持DSH唯一Agent Loop。

SFT/数据生产由其他会话承担；本仓拥有在线RL消费与验收，不新增teacher调用、GPU或Modal。任务必须有步数/token/wall-clock预算。checkpoint继续/workspace/uni-agent-g1/checkpoint/<run>；私有凭据/root/runs。每通过一环节commit/push前Ruff双检查和相应测试。

## 现状与下一步

M1 v2-r4及reload报告为当前通过证据，公开两题baseline已满分不证明提分。Harbor r1失败已停止，cleanup修复04c26ee已推送，Docker恢复负例通过但不代表学生RL通过。已准备的Harbor r2不得继续启动，私有临时spec会到期。
下一步是N1四能力接口与真实任务，随后N2—N4分别训练/评估；N0-R复现结果贯穿各能力验收。原生训练使用已验收venv，不等待N0-E新环境安装。

## 平台goal状态

2026-09-09已通过get_goal核实：新版原生四能力objective已激活，status=active。继续按N0—N5推进，所有必要验收完成前不标complete。
