# Core 记忆生成器的显式身份路由

新增课程/生成标识统一为 `work-state-memory-core-v1`。用户已批准核心课程扩量；本设计细化prepare→stage→audit身份一致性，不改变旧任务。

- 新dataset row严格为family/variant/seed/split/generation五字段，generation必须是上述全名；旧row四字段继续走旧make_task。
- 新prepare dataset和coverage使用core_tasks.make_core_task，task ID为work-state-memory-core-v1-wsXX-vN-sN。未知generation拒绝，不能fallback到旧生成器。
- stage对五字段新row调用core生成器并检查完整ID。完整task只在controller fixture，actor parquet仍只携带task ID。
- audit依task.task_generation显式重建新task并严格绑定run plan course；旧非WS07课仍是work-state-v1，WS07仍short-fact；未知generation拒绝。同课mother、原receipt/source/trace哈希检查不变。
- prepare额外保存controller任务定义和模型可见输入两个JSON工件，纳入manifest.files及check重建检查。truth只在controller工件，不进入parquet prompt或模型可见工件。
- core_tasks.py与旧tasks.py均进入现有source closure；不得改旧task对象/ID来制造新课程。

TDD：新课显式generation与ID、旧课无generation；未知/删除/错配generation拒绝；同课reload；完整artifact确定性/hash篡改拒绝；实际shell/Hydra/runtime stage路由通过。内容多样性与真实runtime可解性由独立生成器/canary验收，本接线测试不能替代。
