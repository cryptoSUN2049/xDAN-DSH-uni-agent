# 首题WS01：真实独立reload与消费通过

2026-09-09，10:17:18 UTC观察到WS01 verified，第二题开始prepare。此报告冻结首题证据，**不是四题评估完成，也不是能力提升**。

- 固定源码：`9dea127bf7bb69eb916aebcc0ab69ff86f53df08`。
- Suite：`/root/runs/ws-r4-isolated-eval-r1`；首题run：`ws-r4-isolated-eval-r1-ws01`。
- 任务：`work-state-ws01-v1-s303`，独立n1 A/B新会话。
- child270480，exit0，490.011秒；无transient health failure。
- 真实日志10:14:23—24 UTC明确从母`work-state-train-r4/global_step_8`加载model、optimizer、RNG及lr_scheduler，写出`validation/8.jsonl`。
- 原消费audit：passed=true、consumption_verified=true，1组、2行、2唯一行。SHA：`b12e4bf12cd384bd2106aec68b992656a18ff754fca0daa19296c77b39fb2be2`。
- 完整[JSON证据](work-state-independent-evaluation-r1-first-task.json)保存原summary摘要、原audit及其输入摘要、母checkpoint11文件绑定与加载日志摘录。

执行器在launch返回后先`recipe.check(after_run=True)`重新核母checkpoint/版本身份，再消费审计和同题校验，再GPU清理检查，随后持久化verified并进入下一题。此顺序及真实状态迁移支持首题after-run核验通过；没有另造不存在的“post-check回执”。10:17:18 UTC现场GPU0%/0MiB。

母模型在此前8步奖励/梯度全0，本题低分也不妨碍工程reload/消费通过。奖励与能力判定沿原评分；整个suite及工作包仍未完成，余三题须各自完成并保留任何失败。
