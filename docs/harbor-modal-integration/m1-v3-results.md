# M1 v3：真实更新与独立 reload 证据

2026-09-08，训练代码dcbd323，DSH7840，配对VERL fefb080，固定Qwen3-4B模型与trim任务，RunPod RTX PRO 6000。

- `/workspace/runs/dsh-m1-v3/exit-code` = 0，两步optimizer完成。
- step1 loss 0.0031915158、gradient norm 0.055908203125；step2 loss -0.0107645285、gradient norm 0.08837890625。
- 两步训练reward均值0.53125、范围0.25—1.0；PG loss可为负，不据此判数值错误。
- step1→step2：504个LoRA张量均变化，399个基础权重均不变，所有比较数值有限；`/workspace/reports/dsh-m1-v3-state-delta.json` passed=true。
- step1模型state SHA256：d4274fe30398b9448eb8b2a0ed485aafbe526e6c07eecf58b1a87d4c665d5886。
- step2模型state SHA256：651fd51d04bf04a63c2c75520f0bc64ae33d2abce3d18d769078b3b61ad74c5c。
- 固定cf2d3f5审计读取器对未修改的原始产物复核，`/workspace/reports/dsh-m1-v3-final-audit.json` eligible=true：10组全部eligible-and-consumed，0 rejected、0 unmatched consumption、3 variance groups。
- 审计读取器修复只兼容数值metrics和独立reward_info；旧重复lineage字段若存在仍校验一致性，回执与trace摘要仍严格校验。

## 尚未完成或不能推出的结论

基线两题reward均0.25、accuracy均0；step1与step2留出accuracy仍均0。没有能力提升证据。张量比较是两个训练step之间，不冒充初始模型对最终模型的逐张量比较。

独立 reload 已完成，证据见下节；使用同代码、模型、LoRA 与留出预算，val-only。

M2 Harbor DSH训练与可复建总交付仍未完成；本结果不代表完整G1通过。

## 独立 reload 实测通过

- reload exit-code=0；05:27:08日志明确Loaded model from global_step_2/actor/model_world_size_1_rank_0.pt，非基础模型回退。
- 唯一日志step为2，没有actor训练指标，没有新增模型checkpoint。
- 两题reward均0.25、accuracy均0，与基线同预算；不宣称提升。
- /workspace/reports/dsh-m1-v3-reload-audit.json：eligible=true，2/2组eligible-and-consumed、0 rejected、0 unmatched consumption。
- 此证据限定固定7840 DSH与dcbd323训练组合；最新DSH Session API迁移需要独立审计，不自动继承通过状态。
