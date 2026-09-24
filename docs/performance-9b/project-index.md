## 统一数据契约（权威入口）

- [统一训练数据字段契约 v1](统一训练数据字段契约-v1.md)：27个顶层columns、messages/tool_calls/supervision子结构、三层数据边界及迁移验收。
- [机器可读列清单](统一训练数据字段契约-v1.columns.json)：数据版本apus-sft-v1；协议版本apus-chat-v1独立。
- 状态：字段设计已冻结；Runpod 已完成 screened-v2 → `apus-sft-v1` 结构导出与流式校验（62,030/62,030、bad=0），证据在 [contract-v1-evidence](contract-v1-evidence/)。仍不能标记 `training_ready`，因为教师证据、语言、license/source split、reasoning policy 与固定验证集尚未补齐。

## 当前进度入口（2026-09-24）

- [后台处理操作](后台数据处理操作.md)：Runpod处理器与状态查询。
- [v2筛选报告](screened-v2-evidence/report.md)、[结果解读及Fable恢复路径](screened-v2-evidence/interpretation.md)：结构候选不等于训练ready。
- [MiMo名称测试结论](mimo-identity-test/conclusion.md)：测试已结束，回到数据主线。
- [原版资产清单](原始数据资产清单.md)：16库（新增1个追溯用来源），Runpod原版哈希与HF失败状态明确区分。

## 数据主线阅读顺序（2026-09-24）

1. [原始数据资产清单](原始数据资产清单.md)：15个唯一源、原版路径、版本、数量/分布、下载范围；[JSON台账](原始数据资产清单.json)。
2. [逐库能力与实际审计](数据集能力分布清单.md)：README优先，实际差异及准入问题另记。
3. [能力目标与20K建议配方](20k数据规划与能力缺口.md)：建议配比与缺口，非已备齐数量。
4. [执行设计](sft20k-execution-design.md)：完整清洗版→三教师子版→20K→HF→小步验收→训练；批准与20K来源选择待确认。
5. [统一母本运行证据](contract-v1-evidence/validation.json)：Runpod 结构导出、哈希、分域、教师族、split 与质量缺口。
6. [质量审计证据](quality-audit-evidence/quality-audit-v5-manifest.json)：硬门禁、provisional 池、语言脚本隔离与 tokenizer 预检；当前 training-ready=0。

# 科学训练产线：项目记忆与文档索引

更新：2026-09-24。当前分支performance-9b，既有隔离worktree verl-uni-agent-harbor-opd-rl。

**核心目标：建立科学、专业、全流程、可观测、可分析与可诊断修复的大模型训练产线。1000条OPD实验是首个验收载体，长期全面9B/MOPD目标保留。**

| 需要什么 | 权威入口 | 状态 |
|---|---|---|
| Qwen3.8-Max补充候选 | [qwen38-max-sft-review.md](qwen38-max-sft-review.md) | 两个原始库已核；许可/污染/质量待放行，当前配额0 |
| Fable/GPT强教师数据复核 | [strong-teacher-sft-review.md](strong-teacher-sft-review.md) | 原始/独立Fable恢复优先级；GPT5.6加权；GPT6未发现合格通用池 |
| 首轮Agent SFT完整数据配方 | [最终训练数据清单.md](最终训练数据清单.md) | v3：核心Fable160＋GPT240，保留Fable20＋GPT60；520现成＋480新生；独立评测与成本门 |
| Agent SFT主线与20种子任务 | [agent-sft-seed20-plan.md](agent-sft-seed20-plan.md) | 20题规格已列；环境/控制/真实轨迹待建设；tool-call实验独立 |
| APUS Tool Call协议专项 | [apus-chat-v1-tool-call.md](apus-chat-v1-tool-call.md) | 设计合同；三层格式、状态机、mask、迁移与验收；实现待推进 |
| MiMo Agent SFT 9B 专题 | [mimo-agent-sft-9b-report.html](mimo-agent-sft-9b-report.html) | 19章；含数据画像准入/强教师合成/Qwen-Apus迁移/多harness，论文事实、原理解释、实施建议分开；未启动新训练 |
| 日常工作/Agent目标与教师优势 | [daily-agent-capability-plan.md](daily-agent-capability-plan.md) | 旧结果已审计；新画像与双线执行待验收 |
| 总导航与架构 | [training-production.html](training-production.html) | 唯一导航；设计与真实运行分开 |
| 产线目标、职责、核心指标、诊断与修复 | [training-production-charter.md](training-production-charter.md) | 当前总纲，2026-09-24 |
| P0–P4详细组件与历史审计 | [training-system-v2-design.md](training-system-v2-design.md) | 保留合同；旧纯RL首轮提案已由本轮OPD试验替代 |
| 1000条试验配额/门禁/文件范围/测试 | [training-pilot-1k-plan.md](training-pilot-1k-plan.md) | 设计；未构建1000条，未启动扩训 |
| 最新训练与兼容验收 | [overnight/index.html](overnight/index.html) | 真实报告；文本OPD通过，thinking1024未通过 |
| 原始验收结论与机器证据 | [full-verdict.md](tokenizer-opd-compatibility/full-verdict.md) / [full-acceptance.json](tokenizer-opd-compatibility/full-acceptance.json) | live张量、17评分案例、reload、EOS诊断 |
| 数据候选、排除与HF归档 | [首次训练数据集合.md](首次训练数据集合.md) / [hf-data-archives.md](hf-data-archives.md) | 候选/归档不等于ready；按最新pilot覆盖旧配额 |
| Thinking三层合同 | [thinking-acceptance.md](thinking-acceptance.md) | 坐标→监督可靠→独立效果；分层验收 |
| 长期MOPD原理与约束 | [核心记忆](../../tasks/verl-uni-agent-harbor-opd-rl/mopd-project-memory.md) | 不把异族静态SFT当在线token教师 |
| 冷启动与运行状态 | [handoff](../../tasks/verl-uni-agent-harbor-opd-rl/handoff.md) | 带时间戳；旧进程/费用不当实时状态 |
| 数据/指标分析工具 | [rl-training-analyst](../../.claude/skills/rl-training-analyst/SKILL.md) | 已有工具待完善；不是所有启发式均适用纯OPD |

## 冷启动顺序

1. 读本索引与handoff，确认用户最新目标及正在运行的任务。
2. 读总纲与pilot合同，确认实际执行路径是原生文本还是Agent工具任务。
3. 核查git未提交变更、数据ready状态、环境/模型/manifest、资源及预算，保留原现场。
4. 按P0指标/数据评分→控制与真实观测→smoke→有界pilot推进；不跳过必需门。
5. 每个里程碑回写handoff与证据，HTML展示实际结果而非计划完成度。

## 不可遗忘的边界

- 原生文本OPD跑通不等于Uni-Agent/Harbor/Modal工具链与全trace后端都已接通。
- 当前W&B为offline；性能自动止损与PAUSED防复活待实现，rl-insight facade单测不代表线上后端可用。
- 纯OPD n1不使用GRPO有效组门；同一面板按算法标N/A并显示实际监督健康。
- 固定验证、行为预算、学习信号、infra与成本必须共同驱动控制，并保留诊断/修复证据。
- 1000条是通过质量准入的独立训练题，不是原始候选数；代码、科学、聊天仍有真实缺口。

- [ms-swift／VERL数据适配方案](ms-swift-verl数据适配方案.md)：统一母本、双导出、thinking/tool与目标消息mask验收；当前设计非已实现。
