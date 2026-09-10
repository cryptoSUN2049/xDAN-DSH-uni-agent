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

先保留本次16步诊断及其原始结果，不在运行中改协议或奖励。此前曾优先建议增加DSH合法tool-call示例，但下文对实际prompt_ids的审计已否定“缺少封装说明/示例”的假设，因此撤回其优先级。现有输入已含工具schema和XML封装示例；新few-shot只能视作具体化/强调位置的另一个实验变量，不能称补齐缺失，更不能无证据优先。也不能自动执行任意最终JSON，它会改变动作边界。

保留的最小公开诊断是下文B角色歧义候选：对同题只调整B继承的保存可选措辞及其明确的恢复指令，控制器仅如实说明index存在性，不增加tool few-shot。只暴露真实文件存在/路径，不暴露配置值、oracle plan、候选答案；仍要求学生自行读取、筛选事实、求解依赖并创建产物。该候选尚未证明有效，也不能假设会同时修复裸JSON问题。

候选先各用一个公开WS03和WS01同预算n4观察：真实调用、成功memory读取、必要事实保存、业务奖励方差；不挑成功轨迹、不给格式动作替代业务奖励。确认出现原任务奖励差异后，才考虑新身份的最小RL重复实验；若仍全零，先保留失败诊断，不盲目追加步数。改协议须版本化，不能与r4旧结果混算，不能把该探索性诊断称P2封存效果。

## 短课程与core的B提示对比：只读补证

比较成功短课r1执行commit `b47521df1d6cd6b930ab6ac85ef41c670f2405d2` 与core r4执行commit `511bd71` 的任务/reader构造。旧commit的 `work_state/short_tasks.py` 与当前文件逐字节SHA256相同：`1b422c0f41ff758d665c4539d4dadf2dc58a36197b324c684d94f40ee94a6345`。这只是提示来源核对，不重采样，不改当前提示。

| 方面 | 短课WS07 | core四族 | 解释边界 |
|---|---|---|---|
| B检索顺序 | `Read the index, then the handoff it references, before producing results.` | `Recover ... from the memory index if present and your public sources.`；另有 `First read the public task specification and any available memory index before choosing values.` | core也要求先读，但带存在条件；不等于完全未说明检索 |
| 公共输入 | `reader_files={}`，有用信息只在memory | B有notice/request/policy等公共文件 | 8链中3个B只读notice；不能据此断言公共源存在必然干扰 |
| 保存/恢复角色措辞 | B明确 `Do not ... change memory.` | A/B共用 `Memory artifacts are optional; organize only useful recovery state.` | 保存可选的A规则带到B，可能与读取已有必要事实混淆；实际B权限仍禁止改memory |
| 完成条件 | `Only successful file writes count as outputs. Finish after writing the two result files.` | B明确要求create两文件，但没有相同的“实际成功写入后才结束”句式 | 文字承诺后结束仍不符合原任务，不是应判成功的例外 |
| 文件内容/工具协议 | stage共同说明 `Use command=create ... business JSON text in file_text`，tool-call外壳不是文件正文 | 同样stage说明，且core额外列exact字段、禁止wrapper与虚构动作 | 3个错误产物不是缺失JSON/字段说明；不能靠再次重复schema自动解释为修复 |

**`Memory discovery entry ... (may be missing; do not invent contents).` 在成功短课旧commit的stage.py已存在，core沿用同句。它不是core新增回归。** 短课也有这句但成功，不能把新任务失败单独归因于该句。短课更简单的业务、两文件强制路线和无公共竞争输入同时变化；没有同题受控比较便不能推断任何单句的因果效果。

最直接的实际B证据：step2 `memory-10c8074196704738a3049e7b8a16889f` 的冻结index真实存在且事实完整，但其B最终文字称 `Since the memory discovery entry may be missing, I will focus on the public task specification.`，随后仅承诺创建文件；trace没有工具调用、输出目录为空。来源为已绑定的 `rollouts/2.jsonl` 中uid `4e7def1d-18f7-4f5a-80bc-6f3a286a17b0_1_1`，以及该chain的reader trace/冻结memory；上文dump/crosswalk哈希保持不变。这支持“存在条件被误用”的可测试假设，不证明改句后一定恢复成功。

下一最小诊断候选因此是：在公开WS01/WS03、保持真实A保存/复杂业务/原评分/模型预算不变时，仅替换B继承的保存可选措辞，使用控制器可验证的index存在信息与读取要求；不给配置值、选择答案或oracle plan。先比较实际memory读取与成功文件产物，不把业务降为抄答案。工具裸JSON的4个B是另一协议遵循失败，下面已确认其输入并不缺少封装示例；不同时新增few-shot造成混杂。本轮没有实施这些候选，r4原证据和提示保持不变。

## 实际模型输入已有工具schema与封装示例

只读核验固定模型 `/workspace/models/Qwen3-4B-1cfa9a7/tokenizer_config.json` 的chat_template，并用该目录tokenizer.json反解**已消费step1四条B**的实际NPZ prompt_ids/response_ids。仅CPU、单线程，CUDA_VISIBLE_DEVICES为空，未加载模型权重或重跑生成。

chat_template字符串UTF-8 SHA256为 `a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8`。四个实际prompt均有完整 `str_replace_editor` function schema（含command/path参数），以及明确要求工具调用用XML标签包裹的如下模板示例：

```text
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>
```

这不是只查模板源码后推测生效：四个实际prompt_ids反解均匹配该示例。NPZ位于 `/root/runs/core-train-r4/agent-logs/step_1/<Gateway session>/trajectory.npz`：

| chain | B Gateway session | prompt token数 | NPZ SHA256 |
|---|---|---:|---|
| memory-f4003c2f784f47c7ac4ac37a3846ad24 | memory-B-562e03fce6c941988547388891c87902 | 1405 | `71c5c9ff94a1fcc8edb644a566cbbe60a03c9826f78f65f0dffbb97715a4150b` |
| memory-a9f0c723d1e7400caa2f2bcc86090d86 | memory-B-874b43ccaf6b4c4cab7fd09c4806afa1 | 1400 | `2eaee9de2a3ccafa7d632837085e15d02d031d1a8da3c34a8d045bd55cf6683b` |
| memory-ee6e21c6a35942cf86367df5366ede27 | memory-B-3b38d3d33b7b49fcb7ecc318e4db89d3 | 1400 | `5a19e8b942f7cfc745910d4681c4fb955372fa965b93e016b6c6e08abe12776e` |
| memory-07768ef866674faf8dd45db8cb567cce | memory-B-6ed9b2ce89fb41d6ab8012d98c45fc7b | 1385 | `ca055df9e7f516166c16d20c2ad7efe5ba0cf2ec531bb9590e41ab29e02b63be` |

四条实际response_ids均输出 `{"name":"str_replace_editor","arguments":{"command":"view","path":".../reader-data/sources/request.json"}}`（空白格式各异），随后im_end；没有tool_call标签，原始trace工具调用数均0。工具名和command意图正确，但模型没有遵循已提供的调用封装，因此不能把问题归因为缺少schema、Gateway丢掉示例或工具调用已执行。该审计不证明模板最优，也不证明重复示例无效；它只排除“已有输入缺失示例”作为本次优先修复理由。
