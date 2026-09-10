# Core train r4 首个 step 的局部证据

这是运行中的 step 1 局部核验，不是 after-run 全审计，也不代表训练完成或有效学习。原始路径、哈希、八条身份和完整 metrics 见同目录 `core-train-r4-step1-evidence.json`。

- `rollouts/1.jsonl` 实际 8 条唯一 UID，精确匹配组 `1469d0c4-8d8b-4435-9901-bc5da6ba8309` 的四条链、每链 A/B 各一条；无缺失、重复或未知消费键。
- 在执行 checkout `uni-agent-core-511bd71` 只读调用现有 `audit_memory_chain_crosswalk` 和 `_stage_lineage`，重审原始 trajectory/token、stage receipt、fixture、任务生成器、冻结内容和 reader-parent 绑定；核验通过。另核 submission 的完整键及 crosswalk 哈希。
- 八个 stage receipt 与 gateway session 身份各自唯一；全部 finished、eligible、fresh，原始 stage reward 与 rollout score 均为 0。任务 ID 与 family/variant/seed 逐条记录在 JSON。
- 首个尝试组 `0cf3c2e8-777f-49bf-9f2a-5264c72d2287` 因 2/4 session 失败于 05:49:07 UTC 被拒绝；它不是本次已消费组。step 1 metrics 的 evicted_samples 为 1。
- step 1：生成 799.397 秒、actor 更新 16.364 秒、总计 832.856 秒；reward、advantage、loss、grad_norm 均为 0。只证明消费和更新调用链走通，不能声称产生了有效策略学习。

核验没有运行 `audit_memory_training` 全量入口，没有连接 TQ 或启动额外 GPU 作业，没有修改远端输入和证据。指标文件仍在追加，因此仅绑定 step 1 原始 JSON 行哈希；rollout、crosswalk 和 submission 使用完整文件哈希。后续 steps、最终 checkpoint 与 after-run 审计仍待执行。
