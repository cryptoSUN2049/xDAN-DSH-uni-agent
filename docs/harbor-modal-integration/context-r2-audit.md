# Context baseline r2 只读诊断

来源：GPU `/root/runs/dsh-context-baseline-r2/artifacts/`，固定本次launch记录（主线程报告commit8ff）。
只读逐题 agent-result、verifier-receipt 与 canonical trace；没有改写结果或重新给分。

| 实例 | 真实动作与最终报告 | 原评分解释 |
|---|---|---|
| directed-present | 两次只读current，未读unrelated；value=3；仅一个citation且source为绝对路径 | 读取覆盖/引用覆盖/引用ID均未满足，0 |
| directed-missing | 两次只读current，未读unrelated；正确弃答；citations为空 | 读取覆盖/引用覆盖不满足，0 |
| conflict-present | 两源都真实读取；value=3；只引current且source为绝对路径 | 引用覆盖/精确source ID不满足，0 |
| conflict-missing | 两源都读取；正确弃答；两个citation但source均为绝对路径 | 精确source ID不满足，0 |

四题finished=true、eligible=true，真实runtime的六列行号+双空格格式符合verifier。
没有观察到表外读取或轨迹结构破坏，严格准入成功不等于业务任务成功。
原reward全部0合理，不能将答案/弃答正确单项替代完整证据合同。

停下反复改提示碰运气。后续设计应分别记录答案正确、弃答正确、读取覆盖、引用覆盖、
引用ID/行号/原文准确与成本。分解指标首先用于诊断，不回写r1/r2奖励。
若要采用部分奖励或新课程，需独立版本与冻结合同，并检验是否只学输出格式、是否有
正负奖励差异及是否保留真实证据约束；不能为了让旧结果通过而事后改评分。
