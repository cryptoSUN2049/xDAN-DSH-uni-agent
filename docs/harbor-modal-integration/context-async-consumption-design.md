# Context 单阶段异步消费审计设计（暂停，未实现）

2026-09-09。独立只读审计发现以下证据缺口。用户随后调整优先级回核心记忆/context，本设计仅保留调研，不启动实现或 GPU。

## 最小接口和文件

拟新增 `examples/dsh/ops/audit_context_async_consumption.py` 及 `tests/uni_agent/examples/test_audit_context_async_consumption.py`；旧同步 auditor/schema 不改。

拟 API：`audit_async_consumption(run_root: Path, *, partition='train') -> dict`；CLI `run_root --partition train --output NEW_PATH`，输出 `dsh.context-async-consumption.v1`。只读输入且独占创建输出，不覆盖原报告。

输入：实际 run-manifest、manifest声明的 agent-log trajectory.json/npz、原始 DSH trace/result/verifier receipt、实际 trainer rollout JSONL，以及可验证的逐组失败/淘汰证据。记录所有输入文件 SHA。复用旧 `_audit_dump` 对 token/logprob、NPZ SHA、finished、原始receipt及身份做严格校验；不沿用其提交步等于消费步的join。

## 关联与判据

- `(partition, transfer_queue_key)` 是唯一消费join；独立记录 group UID、submitted_step、consumed_step/batch、session_index、trajectory_index、真实版本span。
- 同一完整n4组所有sibling/context必须在同一消费batch中出现一次；跨step重复、部分消费、未知key、组身份重复、receipt跨组复用均阻断。
- 不把submitted_step减一或TQ fallback当真实策略版本。要求 generation_count>0、versioned_generation_count相等、version_evidence_complete=true、整数非负min/max且min<=max；允许真实跨版本span。
- 已消费组必须通过原始轨迹校验与版本完整性。记录实际分数，合法零分/同分不淘汰。
- 未消费组仅凭缺key不能判为合法stale/failure。必须有绑定uid、partition及真实事件的失败/淘汰证据；其余归入unknown-unconsumed并令总审计失败。部分已消费与失败/淘汰声明矛盾也阻断。
- 通过还要求作业终态、至少一完整组真实消费、无未知/重复/证据损坏。报告不证明optimizer更新、性能提升或多阶段记忆信用兼容。

## 实施前真实缺口（不能靠离线猜测补齐）

1. `uni_agent/framework/framework.py:1329–1361` 的 `_trajectory_meta` **没有保存** `min_global_steps/max_global_steps/generation_count/versioned_generation_count/version_evidence_complete`。这些存在Gateway `session.py:832–849`的trajectory extra字段，但普通dump当前丢弃。`framework.py:1593–1598`还允许TQ版本fallback，因此仅新离线auditor无法严格验证真实span。需要另行批准最小证据序列化扩展或独立绑定原Gateway原始generation证据的路径；绝不能默认complete。
2. `replay_buffer.py:320–365` 淘汰后只返回聚合指标并clear groups，没有持久化逐uid的stale淘汰回执。不能把evicted_samples计数分摊给任意未消费组。
3. `framework.py:751–758` 有带uid的strict group rejected日志并写TQ failure；日志缺明确partition/提交步，单独正则命中仍需绑定run和唯一group身份。TQ失败写入异常与普通任务失败也要分开。
4. trajectory dump在实际TQ写入之前，不能把“有dump”称为已经提交成功。消费本身可证明其进入实际batch；未消费则需要实际submission/terminal事件。

## 预定TDD覆盖

跨步消费成功；同step同步兼容；多context完整组；跨step重复拒绝；部分组/未知key/receipt跨组拒绝；缺版本/false完整标记/伪造fallback/非法span拒绝；真实跨版本允许；有真实绑定失败/淘汰证据的未消费分类；只有聚合eviction计数时unknown拒绝；运行未完成与空运行拒绝；原同步audit不变。

当前未写代码、未修改框架/VERL、未新增运行。先解决上述证据生产端缺口，再冻结独立审计设计，避免制作一个只能依靠假fixture通过的auditor。
