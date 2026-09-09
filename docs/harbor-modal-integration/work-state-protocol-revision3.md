# Work-state protocol revision 3：业务输出与持久化合同说明

2026-09-09，用户已批准任务范围内的最小合同修复。先记录设计与RED测试，后实现；旧r1/r2产物不修改、不追认。GPU与运行checkout不变。

## 目标与边界

真实r2显示A仅口头handoff未持久化，B混淆业务config/plan与编辑器命令。独立review另外发现WS06双地区输出字段未公开。revision3只澄清公开协议，不改源事实、truth、oracle、业务评分、安全准入与A0→B二元终局机制。

## 文件与API

- `examples/dsh/capabilities/work_state/tasks.py`：`make_task()`形状不变，`protocol_revision=3`；四族reader_goal说明顶层字段类型、业务取值来源、plan语义。所有说明只依赖family/variant的公开规格，不从truth读取正确值。
- `examples/dsh/capabilities/work_state/stage.py`：实际A/B prompt增加新文件可以create/file_text、最终聊天不会转交B、工具调用外壳不属于业务文件等说明；不改StageSpec、路径权限或冻结逻辑。
- 对应`test_work_state_tasks.py`、`test_work_state_stage.py`：真实生成prompt合同、跨seed不泄漏答案、原事实与oracle字节不变、公开WS06两variant可解回归。

## 精确语义

A初始memory目录是新的，缺失可选目标并非坏路径；只在需要保存时使用create和file_text，成功工具写入字节才转交。final_response不会转交B，保存有用事实须由index可发现。六文件不必全写，WS06仍可不持久化。

B先读公开任务规格与存在的记忆入口。config.json是业务顶层字段对象，不含工具command/path/file_text包裹。WS01 capacity/schema_version为整数且保持来源要求，不自行增加版本；plan是尚未完成的业务节点ID，满足依赖、排除completed。WS03每component对应catalog option ID字符串；WS05依据policy.keys与来源类型，按scope/revision/authority选事实。WS06分别capacity或east_capacity/west_capacity整数，公开公式而不填求解结果。没有workflow时plan必须空数组；所有plan元素均非tool-call或自然语言描述。

## TDD与放行

先RED：revision3/保存语义/输出合同断言失败；WS06用公开说明键名与源公式能独立生成合格输出。再GREEN并复跑tasks/stage/verifier/framework/recipe相关回归。固定seed所有源文件、truth与oracle在revision2→3完全相同，另核不同seed的goal文本相同（不夹带个案答案）。不以CPU测试或prompt修订宣称GPU学习成功；先新身份baseline，后按原业务门训练与独立验收。

## 实施与验证结果

revision3已实现并冻结待root review；未部署GPU。新增12项tasks合同测试+1项真实Stage prompt/Task subprocess测试先RED（旧revision2/字段未公开/空目录说明缺失），再GREEN。tasks+stage62项通过；tasks/stage/verifier/bundle/consumption/prepare_memory_training/framework/VERL credit/runtime canary CPU测试合计145项通过。Ruff check/format与diff check通过，保留Ray弃用警告。

8种结构固定seed29的writer_files、reader_files、truth、oracle_memory、oracle_outputs完整指纹与revision2相同；跨seed的reader_goal保持相同，协议说明不夹带个案答案。WS06两种结构均可只根据公开键名/类型/公式与原request数值构造合格输出，oracle_memory仍为空。源代码bundle与source_version随协议内容自然变更，后续必须新准备数据和新run；不得把旧run receipt套到新版本。
