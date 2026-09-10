# Core r4：已消费前两步的探索性失败分析

范围：仅 `/root/runs/core-train-r4/rollouts/1.jsonl`、`2.jsonl` 对应的 2 个 n4 完整组、8 条 A/B 链、16 条实际消费行。不是 after-run 全审计、封存测试或效果评估；未改 GPU、运行代码、数据、奖励，未重跑任务。首个被拒/evict 的组不在本次样本中。

## 结论

- 5/8 条 A 已正确保存必要事实，3/8 条 A 冻结包为空。5个非空 index 的 JSON 代码块逐项解析后与 A 源 JSON 一致，不只凭文件存在推断。
- 8/8 条 B 都没有实际读取任何 memory 文件。检查全部工具路径，而不是仅搜索 index。
- 5/8 条 B 没有产物：其中 step1 四条只输出裸工具调用 JSON，没有 `<tool_call>` 封装、trace 无工具调用；step2 一条仅用自然语言承诺读写后结束。
- 3/8 条 B 实际读了公共 notice 并成功创建两个文件。JSON对象/数组格式与字段类型合法，但 capacity=100/schema_version=1 与真实3616/3不符，plan 是虚构业务动作或文件名，均业务错误；不是 JSON 解析失败。
- 已知两步原奖励/优势/梯度全零与上述失败一致；此处不重新审计梯度，也不能据两题八次采样判断全课程不可学或全部任务均如此。

## 实际消费与原件校验

按 dump.uid 精确匹配同 step 的 crosswalk.tq_key，两个集合均8项且相等；再逐项核 receipt 文件hash/receipt_id、原奖励与dump.score、receipt→trace hash与fixture evidence；核A/B源文件hash、冻结bundle/manifest绑定及每个展开memory文件hash。3次B成功view返回的编号正文均与完整notice源逐行一致。

| 输入 | SHA256（不含前缀） |
|---|---|
| rollouts/1.jsonl | `204558a3b735564bedb4829e7ab9e36efc5547a2f1885537cd5c11403d30dd31` |
| step1 crosswalk | `66751c4968d62e9ed675b821854de1d8c5d77e4af1e86f821802178559f2c850` |
| rollouts/2.jsonl | `df9c22b21c299c3e17b09475f3a8c1a8e69f26bbbb38f1068428fdedd4890b0e` |
| step2 crosswalk | `4e3097f9d5f1b0c5b7ae2cde166b0be3bcb26179b5d0e2a2d276cfc90f46007a` |

crosswalk目录分别为 `chains/groups/1c2f7e0faa414043b9a62ade9de3774b/`、`chains/groups/08c92b7a0b8340a1b30e3634d8b1862a/`。每链原件位置为 `chains/<chain_id>/writer|reader/fixture.json`、`run/traces/*/session.jsonl`、`run/results/*/verifier-receipt.json`、`frozen/memory.bin` 与 `reader-data/outputs/`。没有调用 `after_run` 全审计，也未重算token/optimizer证据。

## 八链矩阵

step1 全部是 `work-state-memory-core-v1-ws03-v0-s1001`；step2 全部是 `work-state-memory-core-v1-ws01-v0-s1002`。这是 **2 个独立任务**，不是8个独立任务，更不是四族覆盖。

| step | chain_id | A | B实际行为 / 最终产物 |
|---|---|---|---|
| 1 | `memory-f4003c2f784f47c7ac4ac37a3846ad24` | 读三个源，index完整保存catalog/requirements，另5文件 | 裸view request JSON未形成工具调用；无产物 |
| 1 | `memory-a9f0c723d1e7400caa2f2bcc86090d86` | 无工具调用，空包 | 同上 |
| 1 | `memory-ee6e21c6a35942cf86367df5366ede27` | 只view不存在的index，收到错误；空包 | 同上 |
| 1 | `memory-07768ef866674faf8dd45db8cb567cce` | 无工具调用，空包 | 同上 |
| 2 | `memory-a9b6b657e01444e1aa53e83245ae2b18` | 源事实完整保存，6文件 | 只读notice；100/1；plan=[configure_capacity, define_schema_version] |
| 2 | `memory-10c8074196704738a3049e7b8a16889f` | 源事实完整保存，index+handoff | 仅文字承诺读写；无工具调用、无产物 |
| 2 | `memory-b58d781819744c76b897bc2e2d88e588` | 源事实完整保存，6文件 | 只读notice；100/1；plan=[config, plan] |
| 2 | `memory-a4d9f0ddc5664f92bb638c22029ca7a5` | 源事实完整保存，6文件 | 只读notice；100/1；plan=[config_json, plan_json] |

WS03有效事实要求事务数据库与cache协议匹配；本题唯一组合database=option-b、cache=option-c。只有首条A完整保存，B却没有实际读取任何文件。不能把模型输出的 `{name, arguments}` 字符串当成已经执行view，也不能反过来断言模型没有发出调用意图。

WS01的4个index均保留 capacity=3616、schema_version=3，completed=[initialize, prepare]，后续copy→migrate→switch依赖完整。三条有产物的B工具顺序均seq9→10读notice、14→15建config、19→20建plan；notice只有字段/目标/计划格式，不含配置值或依赖。另一条B文字称“index可能缺失”而直接结束，实际index存在。

所以当前没有“完整读到记忆后仍求解错误”的实例。5条A传递成功并未形成B检索；3条A缺失与B调用未执行同时存在，不能假设只修A就会成功。所有B trace均completed只表示回合结束，不证明业务任务完成。

## 下一学习实验的最小候选

先保留本次16步诊断及其原始结果，不在运行中改协议或奖励。下一候选优先是**工具调用/完成协议的单变量公开诊断**，不是缩减业务任务：在同一模型、真实源、memory隔离与原score_task下，只增加不含本题答案的DSH合法tool-call封装示例；核真实tool/call及结果回传，而非接受聊天中裸JSON作为已执行动作。不能把自动执行任意最终JSON当作“容错修复”，它会改变动作边界。

若公开诊断确认封装已可靠、但仍跳过memory，再单独比较“控制器如实列明已存在的memory入口”与当前“入口可能不存在”的恢复提示。只暴露真实文件存在/路径，不暴露配置值、oracle plan、候选答案；仍要求学生自行读取、筛选事实、求解依赖并创建产物。两种改动不要一次合并，否则无法知道哪项起作用。

候选先各用一个公开WS03和WS01同预算n4观察：真实调用、成功memory读取、必要事实保存、业务奖励方差；不挑成功轨迹、不给格式动作替代业务奖励。确认出现原任务奖励差异后，才考虑新身份的最小RL重复实验；若仍全零，先保留失败诊断，不盲目追加步数。改协议须版本化，不能与r4旧结果混算，不能把该探索性诊断称P2封存效果。
