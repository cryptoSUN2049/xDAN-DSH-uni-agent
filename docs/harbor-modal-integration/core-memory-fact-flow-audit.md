# Core memory：r4 32 条链事实流审计

这是对既有 r4 原件的只读补证，不是新评估、训练或数据扩展。先详细读取 WS01、WS03、WS05、WS06 各一例，再遍历原报告全部 32 条链。此次只写本报告及同名 JSON；不启动 GPU、不修改奖励、不改变旧分数。

## 1. 结论

28 条依赖 A memory 的链中，24 条冻结 index 已保留必要源事实，23 条 B 没有成功读取任何 memory 文件；另外 1 条 B 读到了完整 index，但未读取公开选择规则，也未写结果。4 条可以确认 A 必要事实缺失，其中 2 条空包、2 条占位或悬空索引。**没有实例足以证明“B 完整读到所有必要上下文后，仍把记忆中的正确事实用错”**；不能把所有 B0 归为 B 推理失败。

WS06 的 4 条空包是合法负例。有 1 条 B 读公开请求并正确计算 capacity=125，但配置多出 rule 字段，精确对象检查失败。另 3 条没有读取公开请求，其中 1 条无产物、2 条默认 capacity=100。应把 schema 错误与算术错误分开。

| 家族 | 链数 | A 必要事实缺失 | 冻结事实存在但 B 没读 memory | B 读 memory 后无产物 | 无需 memory |
|---|---:|---:|---:|---:|---:|
| WS01 | 16 | 2 | 14 | 0 | 0 |
| WS03 | 4 | 2 | 2 | 0 | 0 |
| WS05 | 8 | 0 | 7 | 1 | 0 |
| WS06 | 4 | 不适用 | 不适用 | 不适用 | 4 |

表格采用主要可观测断点，不是互斥的因果证明。A 缺失链也没有 B memory 读取，不能据此保证修 A 后会成功。A 索引缺陷有两条与事实缺失重叠；没有发现“事实仅在其他有效文件，但 index 坏掉且 B 尝试后无法恢复”的独立证据。

## 2. 原件与验证边界

原件相对根 `work-state-train-r4/chains/<chain_id>/`：`writer/fixture.json`、`reader/fixture.json`、`frozen/memory.bin`、`frozen/manifest.json`、`packed-memory.bin`、`reader-data/memory/*`、A/B 的 `run/traces/*/session.jsonl`、`run/results/*/verifier-receipt.json`、`reader-data/outputs/*`。不公开主机地址、凭据或无关原始日志。

- 32/32 reader fixture SHA256 与 [旧 rootcause JSON](work-state-r4-zero-reward-rootcause.json) 一致；32/32 最终产物原文与旧报告一致。
- 冻结 bundle/manifest 哈希匹配 fixture writer_binding；packed bytes 等于 frozen bytes；每项 base64 解码后大小/哈希匹配，并逐项等于 B 展开的 memory 文件。
- 两个 fixture 的 task/source_version 相同；全部 A/B read_files 原件哈希匹配；A trace 匹配 writer_binding；64 份 receipt 均绑定对应 trace 哈希，且 evidence 包含对应 fixture 哈希。
- B 全部 tool call/result 按 callId 配对，检查所有路径，不能只检查 index。19 次成功 view（18 次公共源文件、1 次 memory/index）返回的编号文本逐行匹配源文件完整正文，先后记录到 JSON 的 seq/result_seq。
- 没有重新计算 source_version 的规范化算法，也没有重新做 crosswalk、准入、tensor 审计；这些沿用 [r4 原审计](work-state-r4-zero-reward-rootcause.md)。receipt 绑定验证不等于新签发或独立重新执行 verifier。

JSON 保存每条链的原件哈希、源读取顺序、memory 文件清单/哈希/事实摘要、B 全部工具顺序/返回摘要哈希、输出对象及分类；不复制整段 memory 或完整日志。事实存在判断基于源文件与冻结原文比较，不要求记忆正文必须可被 JSON parser 直接解析。畸形引号、代码围栏、辅助 handoff 的旧绝对路径等另列 presentation_flags。

## 3. 四族详细证据

**WS01，第 1 条，`memory-1c9db4c3deaa42059cf87b8d63b33504`。** A 在 seq9→10 成功读取 workflow，冻结 index 保存 capacity=168、schema_version=2、completed=[initialize]、migrate 依赖 initialize、verify 依赖 migrate。B 只在 seq9→10 读 notice；seq14→15 写 capacity=100/schema_version=1，seq19→20 写 [config_update]。所有 B 工具均已核对，没有读取其他 memory 文件。可确认检索缺失；无法确认若强制读后会正确计划。

**WS03，第 30 条，`memory-471a7ee8c1054cc2b0bf448a2db693c3`。** A 在 seq9→10、14→15、19→20 分别读数据库、cache、requirements，index 保存三个完整来源；合法组合为 database=option-b、cache=option-a。B 无工具调用、无输出。相比第 32 条只保存指向未打包文件的链接，本例可区分“事实已传递但未检索”与“A 未传递事实”。不能将无输出进一步解释成已尝试求解失败。

**WS05，第 9 条，`memory-14c5de78e19d4d8db16792bf5d6bdae1`。** A 成功读 decisions，index 保留 other scope/rev99/remote/168、this scope/rev1/local/1、this scope/rev2/local/168；B 无调用无输出。另第 16 条 `memory-ee55259d69b84663a3eb47166ac9acca` 是全批唯一成功 memory 读取：seq9→10 读完整 index（同样结构，retention=118），随后 completed，无其他工具/产物。它没有读公开 policy，不能称“正确上下文已完整获取”。第 14/15 条只读 policy，输出 region=this-worktree、retention=2，把 scope/revision 元数据写进配置，仍没有读实际配置事实。

**WS06，第 18 条，`memory-937313278f7b4e149722e731edecaae5`。** A 无工具/空 memory 合法。B seq9→10 读 peak=118、reserve=7；seq14→15 写 {capacity:125, rule:"capacity = peak + reserve"}，seq16→17 写 []。`scoring.py:33–43` 要求 config 对象精确相等，额外 rule 导致失败。该例实际算术正确，明确是读后产物 schema 失败，不能写成“125 被算成 100”。

## 4. 全 32 条矩阵

“事实有”指冻结正文含任务所需事实；非证明模型可稳定理解。读取栏列全部成功 view；无表示没有成功读取任何文件。编号与 JSON 一致。

| # | 家族/seed/step | chain 后 8 位 | A 事实 | B 成功读取 | 可确认断点 |
|---:|---|---|---|---|---|
| 1 | WS01/s101/1 | `63b33504` | 有 | notice.json | B 未读 memory |
| 2 | WS01/s101/1 | `85cb683c` | 有 | 无 | B 未读 memory |
| 3 | WS01/s101/1 | `1c71be2a` | 有 | notice.json | B 未读 memory |
| 4 | WS01/s101/1 | `6e144a23` | 有 | 无 | B 未读 memory |
| 5 | WS01/s202/2 | `0b50fb24` | 有 | notice.json | B 未读 memory |
| 6 | WS01/s202/2 | `de96d140` | 有 | notice.json | B 未读 memory |
| 7 | WS01/s202/2 | `4a76e151` | 有 | notice.json | B 未读 memory |
| 8 | WS01/s202/2 | `8f8fc94c` | 有 | notice.json | B 未读 memory |
| 9 | WS05/s101/3 | `5d6bdae1` | 有 | 无 | B 未读 memory |
| 10 | WS05/s101/3 | `07860414` | 有 | 无 | B 未读 memory |
| 11 | WS05/s101/3 | `41b8e2a2` | 有 | 无 | B 未读 memory |
| 12 | WS05/s101/3 | `8a314e7b` | 有 | 无 | B 未读 memory |
| 13 | WS05/s202/4 | `fa4f53d3` | 有 | 无 | B 未读 memory |
| 14 | WS05/s202/4 | `44dea492` | 有 | policy.json | B 未读 memory |
| 15 | WS05/s202/4 | `0829c55d` | 有 | policy.json | B 未读 memory |
| 16 | WS05/s202/4 | `6ac9acca` | 有 | index.md | B 读 index 后停步 |
| 17 | WS06/s202/5 | `d969f572` | 不需要 | 无 | B 未读公开请求 |
| 18 | WS06/s202/5 | `edecaae5` | 不需要 | request.json | B config 多字段 |
| 19 | WS06/s202/5 | `f50caf50` | 不需要 | 无 | B 未读公开请求 |
| 20 | WS06/s202/5 | `1498f1b2` | 不需要 | 无 | B 未读公开请求 |
| 21 | WS01/s101/6 | `8806ba34` | 有 | notice.json | B 未读 memory |
| 22 | WS01/s101/6 | `4b27f7a5` | 有 | 无 | B 未读 memory |
| 23 | WS01/s101/6 | `4ece0fd8` | 缺失 | notice.json | A 缺事实；空包 |
| 24 | WS01/s101/6 | `f82417ee` | 有 | notice.json | B 未读 memory |
| 25 | WS01/s202/7 | `5ede00a0` | 有 | notice.json | B 未读 memory |
| 26 | WS01/s202/7 | `8f512d93` | 缺失 | notice.json | A 缺事实；索引占位/悬空 |
| 27 | WS01/s202/7 | `a361bbc0` | 有 | 无 | B 未读 memory |
| 28 | WS01/s202/7 | `fd8acb85` | 有 | notice.json | B 未读 memory |
| 29 | WS03/s101/8 | `113d4eaa` | 缺失 | request.json | A 缺事实；空包 |
| 30 | WS03/s101/8 | `2db693c3` | 有 | 无 | B 未读 memory |
| 31 | WS03/s101/8 | `2a8ac114` | 有 | request.json | B 未读 memory |
| 32 | WS03/s101/8 | `0d76a3e1` | 缺失 | request.json | A 缺事实；索引占位/悬空 |

## 5. 最短下一步与未决项

1. 无需再重跑 r4 零更新或扩大任务集。先用此矩阵锁定 B 检索/完成协议作为首个修复假设；不直接假设要先 warm-start 或提高训练步数。
2. 如需验证因果，最小新实验应固定已有真实 A 冻结工件，对 B 做单题配对诊断，保留原题/评分/模型和独立身份；目前 base CLI 不支持固定 A 只跑 B，需先呈现小设计并按主线授权实施。不能把 oracle memory 当成学生 A，更不能把提示变化后结果混入旧基线。
3. A 空包/占位的 4 条是独立缺口：已读来源仍只保存链接的两条，需要检查写入与可达性完成协议。畸形 JSON、缺围栏、辅助旧路径和一次自依赖矛盾也需保留，但 B 未读取，无法据此归因当前零分。
4. 尚未知：模型为什么停步、若读取后能否用对、改善 B 检索能否迁移到 dev、有效 RL 是否能学到完整多文件恢复。trace 的 completed 只说明该回合终止，不证明任务完成；这 32 条已有业务分全零。

A reward 固定为 deferred-to-reader（`verifier.py:116–152`），不能用 A0 判定记忆质量。计划验证只检查 config/plan 工件与依赖集合，没有执行外部数据库迁移、部署或工作流；本报告也未证明 context compact、性能提升或记忆训练提分。短课程成功与本次原四族失败必须继续分开报告。
