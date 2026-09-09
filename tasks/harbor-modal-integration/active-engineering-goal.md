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

2026-09-09本次 get_goal 返回原生四能力 objective，平台 status=usageLimited；用户表示额度已解除，当前工具调用和子代理已恢复。目标内容未变、尚未完成；平台暂停/恢复由用户或系统控制，不能用 update_goal 伪造 active。继续执行已授权工作。

## 2026-09-09 较早实测增量（历史，现状见下）

- DSH runtime-grounding：8k失败；24k容量对照完整执行/轨迹回读，但reward0，模型仍未正确查询Tool。
- 文件证据context r2：4/4严格执行通过，奖励全0，真实引用/读取覆盖不满足合同。仅文件证据基线，非真实context切换或RL训练。
- Linux记忆封闭策略：14真实工具调用正反例通过；学生A/B链CPU接线完成；writer r1失败，反馈修复后r2真实验证中，credit尚未实现。
- RSI候选持久化：27新增测试通过，晋升/回滚及新进程选择已验证；固定Linux runtime实际加载/回滚18工具调用已通过；学生候选效果与训练未验收。
- T2日志工具：一个公开开发题4次采样已结束，未观察到成功，严格评估exit1；不是4任务/GRPO训练组。接下来优先真实记忆链与分级RL课程，不重复全零原配置。

上述报告位于docs/harbor-modal-integration/native-*-result.json与native-memory-policy-linux-canary-r1.json。N1—N5均未因此标完成。

## 当前数据与训练准入

- 任务量、独立场景数与采样次数分别记账；重复行或n次rollout不增加独立任务数。没有可直接套用的“行业统一最小数量”。
- context v2现有12 train/4公开dev，仅工程课程；两步更新不等于消费全部12题。必须报告实际消费任务、有效组、奖励分布与更新。
- 2026-09-09 v2探索r2：4 dev×4独立采样，340.01秒exit1。统一失败源于verifier错误拒绝合法view_range，修复前不据此否定学生能力或直接扩大运行。旧回执保留。
- memory旧writer r2已确认一次越权而拒绝，保留失败，不追认；后续prompt revision2的两族完整A/B已通过，见当前快照。
- 后续扩大数据优先增加能力规则/难度/任务模板覆盖；封存测试不用于调提示或挑样本。工程跑通与能力增益分别验收。

## 当前验收快照（不修改N0—N5/P1退出条件）

- context-v2-train-r1：两步真实RL，实际消费2题/8尝试；仅首步有非零任务梯度。14组消费审计、252 LoRA变化/399 base冻结及optimizer审计通过；独立reload四组通过，严格准确率0。
- constraints-r3与updates-r1：两族真实A写入→冻结→新B读取均reward1，身份/回执/事实及云盘归档通过；training=false，尚非memory RL或能力提升。
- context-v2-curriculum-r1：12有效batch、48消费、11唯一题，6步非零梯度；step6→12全部504 LoRA变化、399 base冻结，optimizer6→12和1008 moments审计通过。严格原audit=false保留，D3被拒且未消费、D2补采。独立step12 reload已470.012秒exit0、4/4 fresh评估消费通过，无再训练；dev strict0/4，工程结果不宣称能力提升。
- RSI配对worker准备器/监督入口已7c37cb2推送，仍未真实学生H0/H1比较或晋升。memory实际策略版本完整性2f1995a仅CPU通过，未部署当前GPU。
- 下一接线：独立memory训练stage verifier、Framework单stage机械抽取、可信A/B阶段准备与整链TQ信用；旧eval回执不能改split冒充train。继续保留DSH唯一Agent Loop与固定resident backend。

当前即时进程与后续命令以handoff.md为准；上述新增证据不等于四能力训练和封存泛化验收完成。
