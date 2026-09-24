# APUS SFT 20K 配额与能力缺口报告

更新时间：2026-09-25

## 结论

当前不能生成可训练的 20K 版本。质量审计 v5 的 `training_ready=false`，`approved_rows=0`。现有 10,494 条仅属于 provisional candidate，不能当作已验收训练数据。

## 目标配额

| 能力域 | 20K 目标 | 当前 provisional | 当前 approved | 可确认缺口 |
|---|---:|---:|---:|---:|
| code | 7,000 | 10,494 | 0 | 7,000 |
| reasoning | 3,000 | 0 | 0 | 3,000 |
| office | 3,000 | 0 | 0 | 3,000 |
| data | 2,500 | 0 | 0 | 2,500 |
| translation | 1,500 | 0 | 0 | 1,500 |
| writing | 1,500 | 0 | 0 | 1,500 |
| general | 1,500 | 0 | 0 | 1,500 |
| **合计** | **20,000** | **10,494** | **0** | **20,000** |

“可确认缺口”按 approved pool 计算；这避免把 provisional 数据误报成可训练供给。code 的 10,494 条只能作为待复核候选，不能直接填充 7,000 条配额。

## v5 审计证据

- 输入结构记录：62,030；来源行元数据：293,074；任务组：26,757。
- provisional candidate：10,494，全部标为 `code`；teacher 为 `qwen38` 10,489、`gpt56` 5。
- quarantine：51,536。
- hard/review 阻断仍包括 teacher provenance、language、semantic quality、contamination、tokenizer/mask；另有 80 条 CJK 和 65 条 Arabic 脚本冲突。
- Qwen3.5-9B tokenizer adapter 对 10,494 条候选全部渲染通过（v9，错误 0），但这只证明模板可渲染，不证明 assistant loss mask、语义质量或教师真实性。

证据文件：

- `quality-audit-evidence/quality-audit-v5-manifest.json`
- `quality-audit-evidence/qwen35-tokenizer-audit-v9.json`

## 下一步准入顺序

1. 对 10,494 条候选做抽样与全量机械语义检查，补充 source quality score、空内容、异常长度、重复和污染证据。
2. 在 Qwen3.5 模板上实现并验证显式 assistant/tool loss mask；不能依赖当前模板返回的空 mask。
3. 对 teacher provenance、license、language 做逐源可追溯证明；未知项继续 quarantine。
4. 仅当每个能力域存在 approved pool 后，按固定 seed 做 20K 分层抽样；不足部分必须报告缺口并暂停训练导出。
5. 20K 训练前验收必须输出 manifest、分域计数、source hash、task-group hash、token 长度分位数和 mask coverage。
