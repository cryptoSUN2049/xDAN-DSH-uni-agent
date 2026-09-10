# WS06 reload 失败终态

2026-09-10：原511源码、母step16，run `core-r4-reload-ws06-r1`，exit1/820.021秒。

writer的agent-result和Session v2最后turn/end均明确`max-tokens`。回执fresh=true、finished=false、eligible=false；没有执行reader B，不能标记完整A/B消费或任务成功。Session共452行，最后step89；不是只凭Python异常猜测原因。

本题明确告知下一会话已有完整短请求，可不创建/检查memory文件并立即结束。实际writer仍耗尽预算，说明当前策略未表现出克制操作/及时停止。暂不能将具体反复动作因果归为某一提示句，仍需逐事件分类。

独立val将该不完整轨迹拒绝并退出：`reward_info must declare finished=true`。这不影响已结束母训练，也不应回写旧合同将其伪标完成。后续应保留任务失败结果并完善评估隔离，具体新准入合同见core-negative-trajectory-admission-review.md。

持久原件在`/workspace/reports/core-r4-reload-results/ws06/`：agent-result、receipt、Session v2、train.log、run-manifest、外层终态日志，全部复制后SHA256回读一致。清单见同名JSON。本记录不代表完整目录归档、母checkpoint复核或正式消费审计通过。
