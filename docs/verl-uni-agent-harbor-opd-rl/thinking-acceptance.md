# Thinking 三层验收协议

状态：用户批准建设；本协议已定义，自动采集与真实对照尚未完成。

## 1. Token 与上下文对齐（正确性硬门）

- 冻结学生、教师、tokenizer、chat template、thinking 开关与实际 token IDs；不得由展示文本重新 tokenize 冒充原轨迹。
- 在短轨迹、多轮工具反馈、思考结束符、EOS、截断、空 thinking 和失败恢复上逐例核对。
- 教师 logprob 第 t 项必须对应相同历史条件下的第 t 个学生 token；核查 causal shift，禁止让未来工具结果参与当前 token 的条件。
- 区分 reasoning、analysis/plan、action、结束符、工具观察、模板注入及 padding；生成来源与语义类别分别标记。非 thinking 模式中的 JSON analysis 不等于原生 reasoning channel。
- 外部观察/模板注入不参与生成 token loss；检查未完成 episode 被整体 mask 的数量。每条记录 expected、scored、loss-bearing token 计数。
- **放行**：token 身份和位置无错位；mask 和计数守恒；数值有限；抽样 teacher 分数与独立 forward 参考在预先设定精度容差内一致。818-token 格式探针只能证明该用例，不能覆盖所有真实轨迹。

## 2. 教师监督可靠性（诊断与准入）

- reasoning、analysis/plan、action、结束符分别记录 teacher/student logprob 差值均值/分位数、有效 token 数、clip 比例及加权 loss 占比。
- 按成功/失败、长度、任务来源和终止原因分层，检查正蒸馏信号是否偏向错误动作、冗长或无法结束。
- 比较 teacher 在相同工具/预算下的独立任务表现；另采样检查教师对 student 错误历史的评分，不把独立高分当成离轨状态评分正确的证明。
- 当前 k1 + PG 只提供 teacher-student 概率差信号，不是过程正确性标签；纯 OPD 未用 verifier reward 纠偏。不得称其为已实现的过程奖励模型。
- **放行**：身份完整、计数可解释、教师适用任务范围明确。没有分区采集或失败样本证据时标 unknown，不能自动判通过。初版只分区观测，不同时更改 reasoning/action 权重。

## 3. 同预算独立效果（能力门）

- 首先固定一个 checkpoint 对照 thinking off/on；模板兼容检查未通过则拒绝该臂。推理开关对照与训练配方对照分开进行。
- 冻结任务、工具、verifier、采样设置、重复数、总 token/turn/time 预算；reasoning tokens 算入总预算。超预算不追加额度挽救特定臂。
- 逐任务记录成功率、格式/工具错误、超时、总 token、turn、wall time、成本和基础设施缺口；按任务聚类作配对区间，不将重复采样当独立任务。
- 监控集用于预警，dev 用于选择，sealed 在候选锁定后评测。预先冻结回退 margin 与确认规则，不凭两次小样本下降自动宣布退步。
- **放行**：结果完整且满足预注册能力与成本门；未显著改善就报告不确定，不把思考更长或 loss 更低写成提升。

## Infra 接口（拟实现）

本地 `thinking-audit.json` 保存模型/数据/模板身份、三层 verdict（pass/fail/unknown）、证据路径和原因；W&B 使用 `thinking/alignment/*`、`thinking/supervision/*`、`thinking/outcome/*`，共享 run/attempt/step/checkpoint 身份。P1 控制器消费明确主指标；缺失证据不能填 0。

## 最小实施顺序

1. 离线读取本次 OPD trajectory.npz/json，恢复 token、mask、三类 logprob 的身份与可用性。
2. 加分区计数与对齐测试，覆盖真实多轮轨迹和错位/缺字段反例。
3. 教师评分独立抽检通过后，运行同 checkpoint 的 thinking off/on 小规模验证。
4. 三层证据完成后再讨论是否对 thinking 加权、引入过程奖励或扩展多教师；一次只改变一个机制。
