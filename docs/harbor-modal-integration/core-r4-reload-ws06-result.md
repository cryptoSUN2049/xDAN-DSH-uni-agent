# WS06 reload 失败终态

2026-09-10：原511源码、母step16，run `core-r4-reload-ws06-r1`，exit1/820.021秒。

writer的agent-result和Session v2最后turn/end均明确`max-tokens`。回执fresh=true、finished=false、eligible=false；没有执行reader B，不能标记完整A/B消费或任务成功。Session共452行，最后step89；不是只凭Python异常猜测原因。

本题明确告知下一会话已有完整短请求，可不创建/检查memory文件并立即结束。实际writer仍耗尽预算，说明当前策略未表现出克制操作/及时停止。暂不能将具体反复动作因果归为某一提示句，仍需逐事件分类。

独立val将该不完整轨迹拒绝并退出：`reward_info must declare finished=true`。这不影响已结束母训练，也不应回写旧合同将其伪标完成。后续应保留任务失败结果并完善评估隔离，具体新准入合同见core-negative-trajectory-admission-review.md。

持久原件在`/workspace/reports/core-r4-reload-results/ws06/`：agent-result、receipt、Session v2、train.log、run-manifest、外层终态日志，全部复制后SHA256回读一致。清单见同名JSON。本记录不代表完整目录归档、母checkpoint复核或正式消费审计通过。

## 失败后的独立母文件复核

原511 checkout使用既有prepare_memory_training.check(..., after_run=True)在CPU执行，已通过源码/runtime/config与母checkpoint逐文件身份校验。新报告/workspace/reports/core-r4-reload-results/ws06/after-run-source-and-checkpoint-check.json，SHA256 5298387c65361f6c8cce3c5392cccce21702b678fd2dec15355be3e28be90e88。此项补齐失败后母checkpoint未改写证据，不改变writer未完成、无B、无消费的结果。该新增报告不在此前reload tar内，单独保留在云盘。

## 正式消费审计补齐

原审计已生成，原件见 `core-r4-reload-ws06-consumption.json`，SHA256 `16a68fdf0f65e2e15558050097fd00bcce95036102a41c76b0eedf7d6f427d6c`。passed=false、consumption_verified=false、run_completed=false，0组/0条消费；errors为空仅说明未检出消费记录错误，不表示任务完成。与writer未完成、B未执行的原始证据一致。报告单独保存在云盘，未追加入此前归档。
