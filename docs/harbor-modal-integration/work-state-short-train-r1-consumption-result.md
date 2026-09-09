# WS07 首轮训练：最终消费及任务梯度核验

最终CPU核查快照：2026-09-09 12:17:59 UTC。运行`ws-short-train-r1`，固定源码`b47521df1d6cd6b930ab6ac85ef41c670f2405d2`；实际run-manifest状态completed，child291433。主线程监督记录exit0/1770.035秒；本报告独立读取原manifest、消费行、原回执/NPZ与日志，不读取大模型或checkpoint。

**最终原audit通过：8个完整n4组，64条唯一A/B实际消费行，6个唯一任务实例。第2和第4步有真实组内B奖励方差、有限非零任务梯度；其余六步任务梯度为0。**

## 完整消费证明

原审计输出：`/root/runs/ws-short-train-r1/final-consumption-r1/audit.json`，passed=true、run_completed=true、consumption_verified=true。8/8组逐键与trainer JSONL匹配，原阶段token/receipt/版本/冻结工件重评核验通过。errors、unknown/unadmitted、duplicate、overlapping均为空；未将提交crosswalk本身伪装为消费证据。

详细原始摘要及文件哈希见[JSON](work-state-short-train-r1-consumption-result.json)。8个组分别保持n4兄弟同题、A后B完整消费；权重版本分别为trainer step−1，符合固定sync contract。

| step | 实际任务seed | 四个原B终态奖励 | actor grad_norm | advantage min / max |
| --- | --- | --- | --- | --- |
| 1 | s102 | [1,1,1,1] | 0.0 | 0 / 0 |
| 2 | s104 | [0,1,1,0] | 0.14892578125 | -0.866023898 / 0.866023898 |
| 3 | s106 | [1,1,1,1] | 0.0 | 0 / 0 |
| 4 | s107 | [1,0,1,1] | 0.16845703125 | -1.49999702 / 0.499998987 |
| 5 | s108 | [1,1,1,1] | 0.0 | 0 / 0 |
| 6 | s101 | [1,1,1,1] | 0.0 | 0 / 0 |
| 7 | s102 | [1,1,1,1] | 0.0 | 0 / 0 |
| 8 | s104 | [1,1,1,1] | 0.0 | 0 / 0 |

第2步pg_loss=-0.020112289115786552，第4步pg_loss=-0.008506059646606445。所有8步记录的指标有限。末B奖励广播同链A/B，组内有效方差来源是四个B；不能把A原reward0与B1当成两份独立信号。第2步的具体真实导航行为已在[首个信号报告](work-state-short-r1-first-signal.md)核验。

## 任务覆盖与拒绝组

实际消费任务为s101、s102、s104、s106、s107、s108，共6个唯一实例，只有一个训练结构；s102、s104各被再次消费。**8更新步不等于8唯一题**。s103和s105未形成本轮已消费组；不能宣称训练清单全部独立实例均已训练。

原日志有4个严格拒绝组：s101一次、s103两次、s105一次。四条对应的reader回执均fresh=true、finished=true、eligible=false；它们所在整组未被消费，与8已消费uid交集为空。安全失败被隔离，原拒绝回执没有删除、改奖励或补TQ。三条已准入的B质量0也真实保留并消费，不与安全拒绝混淆。

32个已消费B终态奖励分布：29个1、3个0（29/32）。这是**训练采样中的条件任务合同得分**：排除了4个整组拒绝，且含重复实例，不是总体成功率、独立测试集准确率或能力提升证据。

## 准确验收边界

此次可确认完整同步训练采样/严格准入/原token与奖励绑定/TQ消费，以及第2、4步真实非零任务梯度。最终原消费审计不证明optimizer状态或参数变化，checkpoint delta与独立reload由其他独立验收继续完成。第5–8步虽然任务梯度0，后续参数仍可能因optimizer momentum变化；不能将其称为新任务学习信号。

本课程结果单独标记，不改写原r4课程零更新事实；未用dev挑prompt、温度或最佳checkpoint。模型记忆/上下文/RSI的泛化效果仍未证明。
