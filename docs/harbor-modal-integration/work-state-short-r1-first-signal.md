# WS07 首个真实组内学习信号：第2步中途核验

快照：2026-09-09 11:58:28 UTC；随后只补读该组两条零分链的冻结index/handoff。训练仍在进行。本报告聚焦已经完成的第2步，不追认后续全部训练、参数变化或能力提升。

- 固定远端checkout：`/workspace/rebuild/uni-agent-work-state-short-r1`，完整源码SHA见[原始摘要JSON](work-state-short-r1-first-signal.json)（b47521d…）。运行：`/root/runs/ws-short-train-r1`。
- 同题：`work-state-short-fact-v1-ws07-v0-s104`；4个真实独立A/B sibling，原B终态奖励 **[0, 1, 1, 0]**。四条均`fresh=true / finished=true / eligible=true`，同一source_version，实际权重版本均1（训练step2使用step1权重）。
- 原crosswalk组`749d0533-9899-4e46-9cea-1eadd273383a`与`rollouts/2.jsonl`逐键匹配：8条唯一A/B实际消费，原receipt/NPZ/token/版本/冻结工件与独立重评分通过，submission绑定通过，无缺失、重复或奖励不符。不可只用crosswalk提交状态当消费证明。

## 奖励方差来自什么

| sibling | 原B奖励 | 真实行为与独立重评分 |
| --- | --- | --- |
| 0 | 0 | A把相同容量摘要写入index与handoff，index没有相对handoff引用；B读index两次，没有读handoff。业务输出正确，导航质量合同失败，仍合法准入 |
| 1 | 1 | B读index结果后下一次模型响应读handoff；收到handoff结果后下一次响应写config/plan。业务与读取合同全部通过 |
| 2 | 1 | 同上；原始事件时序、全文及业务结果均通过 |
| 3 | 0 | 与sibling0相同的index内容问题及缺handoff读取；配置/计划正确，质量0，仍合法准入 |

四条真实结果均为capacity=187、plan=[]，不是算错容量形成的方差。两条零分没有被排除或改分。成功链的关键事件列表下标为index generation8/result10 → handoff generation13/result15 → output generation18；详情与call IDs在JSON。零分链仅view index，没有view handoff。

该课程预先要求两文件入口导航，模型把事实放在index直接使用也许足以完成该单一业务任务，但不满足本课程已冻结的导航合同。这里训练的是指定保存/恢复操作模式，不能因此宣称更一般的自主记忆组织能力得到提升。

## 训练信号及消费边界

第2步原日志记录：

- `actor/pg_loss=-0.020112289115786552`
- `actor/grad_norm=0.14892578125`
- `critic/advantages/min=-0.8660238981246948`，`max=0.8660238981246948`
- 第1步pg_loss、grad_norm和优势均0。

固定VERL multi-trajectory GRPO取每个sibling的最后B奖励，再广播该链A/B。因此有效差异是四个B之间的[0,1,1,0]，不能把A原0和B原1视为两个独立奖励信号。日志`critic/rewards/mean=.25`是8条阶段行的统计，不等于四B成功率；本组B为2/4。

只执行一次原`audit_memory_training`，其运行中快照实际捕获到4组32条唯一消费，`consumption_verified=true`、errors/未知/重复/重叠均空；`run_completed=false`、整体`passed=false`必须保留。报告位于`/root/runs/ws-short-train-r1/interim-first-signal-r1.json`。其中第2组明确`consumption_verified=true / stage_evidence_verified=true`；原crosswalk的`crosswalk_consumption_verified=false`不被伪改，最终消费证明来自独立JSONL联结。

本轮仅CPU读取现有trace/receipt/小NPZ与业务工件，没有读大checkpoint/模型、没有操作GPU或变更运行源码。**可确认本组真实组内奖励方差、有限非零任务梯度及实际消费；不能据此确认参数delta、optimizer状态变化、独立reload或整体能力提分。** 后续统一做最终审计，原r4旧课程零更新结论不变。
