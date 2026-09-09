# Work-state r3：首两条dev的真实行为诊断

2026-09-09 13:34:36 UTC+8（05:34:36 UTC）。只读检查`/root/runs/work-state-train-r3/chains`，protocol3、固定r3 checkout；未改代码/进程/奖励。范围只含已结束的WS01/WS03两条initial validation，不代表后续train或全dev结论。

## 直接执行

**protocol3部分改善，但没有解决终局业务任务。** WS01 A已真实保存，WS03 A仍只看不存；两B的JSON顶层形状更接近业务合同，但未依据完整恢复事实作答。两链A/B均finished=true/eligible=true/reward0，A0原本就是延迟评分，不把A0等同失败。

| 项目 | WS01 v1 s303 | WS03 v1 s303 |
|---|---|---|
| chain | `memory-0b8f6cf731284850bf928c390e4d12c7` | `memory-db8c8f3c13e341ae83b5ea37312dae0c` |
| A真实动作 | view workflow；create index.md、handoff.md，均成功 | view encoder、transport、storage、requirements；无写调用 |
| A真实库存 | index.md保存完整源JSON；handoff指回index | 空 |
| B真实读取 | 仅view notice.json；没有view index.md | 仅view request.json；没有view缺失index |
| B实际config | `{"capacity":100,"schema_version":1}` | `{"encoder":"catalog_option_1","transport":"catalog_option_2","storage":"catalog_option_3"}` |
| B实际plan | `["config.json"]` | `[]` |
| 终局评分 | 0 | 0 |

### WS01：信息已保存/传递，B跳过实际入口

A tool/call seq9读取workflow，实际源含capacity=28/schema_version=3、completed initialize与parallel-join依赖；seq14创建index.md保存完整JSON，seq19创建handoff.md。所有对应tool/result为成功，实际库存与file_text一致。

B的展开index真实存在、在fixture.read_files授权表中，且与A保存字节完全相同；B的实际prompt包含该准确绝对入口与“First read the public task specification and any available memory index before choosing values.”。因此未发现bundle丢失、未授权或入口漏传。以上核的是保存prompt/fixture/文件，未重新解码backend token输入，不能代替token/rendering审计。

B seq9只读notice（只列业务键名与目标），seq14/19便create错误config/plan。输出字段已从r2工具配置转成业务capacity/schema_version，但数值是无来源猜测，plan把输出文件名当动作节点。真实文件与调用file_text一致，没有工具parser改写证据。此例主要缺口是B没有检索已到手的恢复状态，然后未按业务依赖构造计划。

### WS03：A只识别事实却没有发布，B猜测不存在选项

A四次view后最后明确说没有在空memory目录创建文件，事实只留在聊天摘要中；不再像r2同类例子那样虚称已保存，但仍未完成持久化行为。

B公共request只包含组件键与binary/local/minimum_retention约束，没有各catalog选项。B只view该request，然后create三个正确顶层组件键和空plan；没有获得A catalog，填入`catalog_option_1/2/3`这些不存在的选项。空plan符合无workflow要求，config仍错误，二元总reward0正确。不能由controller补A文件、把聊天转交或把正确字段形状改算成功。

## 深度交互与下一诊断

1. 保留这两种可分解事实：WS01“保存和传递已成功，B未检索”；WS03“A未发布必要状态，B缺证据猜测”。不要把它们笼统说成“数据太少”或“工具坏了”。
2. 继续只读核真实n4组是否出现成功A保存+B读取的行为差异。跟踪A成功write库存、B index/source实际view、业务config与plan分项；这些先是诊断指标，不偷偷加入训练奖励或准入门。
3. 协议已明确要求先读，下一步不应马上再叠一轮同义提示。优先对照实际backend输入是否包含入口和前步反馈；如运输无误，再考虑独立版本的分层课程或更可学习的任务覆盖。当前run标准和结果保持不动。
4. WS01把全部必要内容放index虽然不体现模块化索引效率，但当前合同合法且可恢复；不应为了理想文件组织额外判它失败。长期索引/成本效果另设课程，避免把工程验收变成未经宣布的风格评判。

## 原轨迹复核位置

根目录`/root/runs/work-state-train-r3/chains/`，每项路径后附SHA256：

- WS01 A：`memory-0b8f6cf731284850bf928c390e4d12c7/writer/run/traces/fb5759e4b3c6e5951a07ea3b/session.jsonl`；`07daf76e23bf6c76443fff8f1b23d0513a05fde5f42a7ceba900283d671705cd`。
- WS01 B：`memory-0b8f6cf731284850bf928c390e4d12c7/reader/run/traces/d16ac7233f3953e38a8ba799/session.jsonl`；`84bb32125f3c0f7503329f1a254cf086875bb4da9bdd58cf141985f559af8d5f`。
- WS03 A：`memory-db8c8f3c13e341ae83b5ea37312dae0c/writer/run/traces/ec8babf557916ea1697c578b/session.jsonl`；`2afff97a9570732d67b0ed4cde561292fabe2d1451009b22c4ad31cf4966c21c`。
- WS03 B：`memory-db8c8f3c13e341ae83b5ea37312dae0c/reader/run/traces/789d731afd73e7c80a307668/session.jsonl`；`b855f2870ce617357627e4a9769967c1cf239f32a4947162523a40498744a380`。

对应chain的`writer/fixture.json`、`reader/fixture.json`、`reader/prompt.json`与`writer-data/memory`、`reader-data/memory`、`reader-data/outputs`为输入/字节库存证据。没有生成新的训练回执或追认旧结果。

## 补充：WS05与WS06，现覆盖initial dev四族

保留原文件名，追加后范围为r3四族initial dev；仍不扩张为n4训练或全流程验收。以下来自真实DSH内嵌assistant stream、tool/call/result、B实际文件和原回执；原始backend token尚未在本子任务解码，stream是Gateway/DSH接收后的生成表示。

### WS05：工具调用表达成为纯文本，业务尚未开始

chain `memory-78c17d58e4334767b66903fcceef3996`，`work-state-ws05-v1-s303`。A已保存六个memory文件；index.md/handoff.md/decisions.md包含原scope、revision、authority事实，另memory/tasks空数组及modules说明。因此本例不能解释为A没有提供资料。

B assistant/message seq8仅生成以下纯text（实际绝对路径指向该chain的reader-data/sources/policy.json）：

```json
{"name":"str_replace_editor","arguments":{"command":"view","path":".../reader-data/sources/policy.json"}}
```

该字符串是有效JSON，但没有实际结构化tool-call；内嵌stream为text block，finish.kind=stop，outputTokens=72。随后turn/end seq10报告completed。整条B **0 tool/call、0 tool/result、output目录为空**；finished=true/eligible=true/reward0。

结论：本例是实际工具调用协议/生成格式失败，未进入读取policy或scope/revision选择，不足以判断模型不会处理事实优先级。不能自动把任意裸JSON升级成可执行工具调用，也不能拿自然语言“想读”冒充已读。应对照原始backend token及当前tool parser合同确认裸JSON是模型真实输出还是编码转换问题；本子任务不据下游text独断parser责任。

原B trace：`/root/runs/work-state-train-r3/chains/memory-78c17d58e4334767b66903fcceef3996/reader/run/traces/8eaa2c189c3c44262c4b76a0/session.jsonl`；SHA256 `062566478170d3e6ab123b567f9f496a15b487a7cd0d787e4974788d3e7718f5`。

### WS06：已读完整请求，输出协议正确，但漏应用区域上限

chain `memory-02c75d94e89c404b8b4b2514ab286c08`，`work-state-ws06-v1-s303`。本任务无需memory；A仍冗余保存六份相关文件，当前评分不按文件数量加减分。

B seq9真实view公共request，seq10成功结果完整给出east_load=28、west_load=37、limit=32与“Each regional capacity is min(regional load, limit)”规则。B seq13内嵌stream随后生成两个结构化tool-call，seq14/16实际执行create，seq15/17均成功。原file_text与实际磁盘字节一致：

```json
{"east_capacity":28,"west_capacity":37}
```

plan.json实际为`[]`。两个业务字段名、整数类型、JSON结构、空plan与真实工具调用均正确；东区min(28,32)=28也正确。唯一config错误是西区仍用37，未应用min(37,32)=32。因此binary reward0符合当前业务规则，**不是输出协议机械失败，也不是没读request**。最终回复重复相同错误值，没有进一步校验。

这条轨迹证明本次生成没有正确应用已返回的上限规则，不证明模型普遍算不了min，也不排除待独立核实的下一轮token输入问题。尚未检查原后端token是否确实携带该工具结果，不将DSH持久化结果等同所有后端输入已经审计。

原B trace：`/root/runs/work-state-train-r3/chains/memory-02c75d94e89c404b8b4b2514ab286c08/reader/run/traces/dfa1fb20d21ea9ab0ce84af6/session.jsonl`；SHA256 `8f240549ec7de67549ae2c8e0d1ef439802e2383839a31969b4b26b9ce545545`。

### 四族下一诊断应分开

| 族 | 当前可证实缺口 | 不应直接归因 |
|---|---|---|
| WS01 | B未读已存在完整记忆，猜配置/计划 | bundle丢失或不会create |
| WS03 | A未发布，B猜不存在catalog IDs | 仅JSON schema问题 |
| WS05 | 裸工具JSON作为text，工具动作未发生 | scope/authority推理能力不足 |
| WS06 | 成功读取与写入，未应用min上限 | 缺memory或工具JSON解析失败 |

先核当前n4真实行为差异与原token/parser证据；保持现run与奖励不变，不立即再堆提示。四种0分背后的错误阶段不同，后续若调整课程应据此分层，而非通过隐藏答案或统一放宽评分获得表面通过。

## 本轮执行优先级确认

用户最新明确工程链路第一：先完成既定有界r3流程并保存可复建产物，再分别验收有效更新证据和能力提升。上述四族reward0作为诊断记录，**不作为中断合法训练流程的条件**；原有安全/证据准入拒绝仍不改变。本文不扩提示优化或课程改造，本轮不新增数据生产；让已定run自然完成后由主线程核消费、checkpoint与独立reload，不能用参数文件存在冒充有效学习。
