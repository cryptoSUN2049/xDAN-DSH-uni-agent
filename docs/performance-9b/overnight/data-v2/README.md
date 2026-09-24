# 严格复审后冻结候选 v2

2026-09-24。状态：exploratory pilot，不是全面高质量认证。

原v1保持不动。本版只删除math与knowledge_mcqa中逐条复审判为exclude/uncertain的题，不改原题、不修答案、不移动split、不补造题。其他三域原样保留。

|领域|训练|开发验证|
|---|---:|---:|
|math|23|5|
|instruction|32|8|
|knowledge_mcqa|3|1|
|code|32|8|
|chat|32|8|
|合计|122|30|

**knowledge_mcqa仅3训练/1验证，只可覆盖链路，不能判断科学领域效果。** 代码为syntax诊断，chat未评分；其他域仍不等于完整质量认证。开发集不是最终保留测试集。

依据：`quality-review-80.json`包含原80题逐条决策、理由、源行和原split；`dataset-manifest.json`保存源版本/哈希、父版本产物哈希、排除名单及本版产物SHA256。152条保留记录与v1对应记录逐字段相同，样本身份不重复。

远端：`/workspace/verl-uni-agent-harbor-opd-rl/data-overnight-opd-20260924-v2/`。数据准备不代表训练已经启动或成功。
