> 已由 [v2强教师核心配方](agent-sft-data-plan-v2.md) 替代；本页保留历史，不作为当前采样配置。

# APUS Agent SFT 首轮数据计划 v1

2026-09-24（强教师复核修订v1.1，详见[专项复核](strong-teacher-sft-review.md)）。目标：继承 MiMo 9B 的通用 Agent 基础，优先增强本地办公、数据处理、中英翻译、事实写作，同时保留代码与通用能力。以下是**合格数据目标配额**，不是已构建数量，也不是最终模型的充分训练规模。

本计划取代旧6000条通用SFT草案作为当前Agent SFT首轮配方；原版9B的1K OPD实验合同独立保留，不混用实验结果。参考：[数据画像抽查](mimo-agent-sft-evidence/portrait-audit.json)、[20种子](agent-sft-seed20-plan.md)。

## 1. 规模与领域

| 领域 | 独立训练任务目标 | 占比 | 为什么 |
|---|---:|---:|---|
| 软件维护/终端 | 200 | 20% | 保留现有优势，支撑其他工作中的脚本与调试 |
| 本地办公/文件交付 | 200 | 20% | 从回答升级为可用docx/xlsx/pptx和跨文件一致性 |
| 数据处理/分析 | 200 | 20% | CSV/SQL/计算/图表/报告，适合可执行验证 |
| 专业中英翻译 | 150 | 15% | 术语、数字、格式、语义与多轮修订，现有数据缺口大 |
| 事实与商务写作 | 150 | 15% | 报告/邮件/提案/综合与编辑；不以小说或RP替代 |
| 通用能力保留 | 100 | 10% | 指令、安全、中文、数学/科学，监测遗忘 |
| 合计 | 1000 | 100% | 首轮验证配方，效果成立才扩量 |

这些是任务数，不是token比例。冻结release前，用实际学生tokenizer统计每域input/loss/tool/reasoning/final token，公布实际监督分布。若长代码轨迹挤占其他领域，调整采样权重或增加合格短任务；不截断成功轨迹来凑配比。

## 2. 数据集、数量、理由与准入

| 来源 | 目标任务 | 领域/用途 | 入选理由 | 必须通过的门 |
|---|---:|---|---|---|
| [nvidia/Open-SWE-Traces](https://huggingface.co/datasets/nvidia/Open-SWE-Traces) | 20 | SWE | 真实仓库动作/反馈及resolved信息 | 成功、无捷径、完整轨迹、可重放抽检；repo/task去重及评测隔离；固定清洗后revision |
| [greghavens/gpt-5.6-sol-coding-and-debugging-traces](https://huggingface.co/datasets/greghavens/gpt-5.6-sol-coding-and-debugging-traces) | 100 | 终端代码/调试 | 画像中较贴近目标的母本 | 按session/task而不是前缀行计数；保留工具结果、授权与执行证据 |
| Fable 5原始/独立来源池（armand0e / TeichAI / AlinCiocan；DSFF镜像须身份筛选） | 60 | 代码/工具 | 恢复强教师母本覆盖，与GPT互补 | 独立task/session、跨镜像去重、teacher证据、真实工具反馈、许可；不足保留缺口 |
| [openbmb/UltraData-SFT-Agent-2609](https://huggingface.co/datasets/openbmb/UltraData-SFT-Agent-2609) | 40 | Office轨迹 | Office/文件/skills覆盖 | 先抽审Office子集、turn mask；不可回放要明确标注；上游附加条款及转载限制 |
| [Spreadsheet-RL/Spreadsheet-RL](https://huggingface.co/datasets/Spreadsheet-RL/Spreadsheet-RL) | 80 | Excel任务来源，需新生成轨迹 | 有训练任务、工作簿与评分环境 | 只train；parser重复合并；评测全部隔离；许可和环境验收 |
| [FineEnvs/data-agent-sft](https://huggingface.co/datasets/FineEnvs/data-agent-sft) | 120 | 数据分析SFT | 完整bash数据分析轨迹，卡称reward=1 | 核验env/输入文件、任务重叠、原始数据许可；不能只相信标签 |
| [nvidia/Nemotron-Cascade-2-SFT-Data](https://huggingface.co/datasets/nvidia/Nemotron-Cascade-2-SFT-Data) | 70 | chat/IF/safety/中文保留 | 多域保留、避免仅强化工具后退化 | 按子来源筛；采用NVIDIA对应许可而非假定CC-BY；事实与约束核验 |
| [nvidia/Nemotron-SFT-Math-v4](https://huggingface.co/datasets/nvidia/Nemotron-SFT-Math-v4) | 20 | 数学保留 | 可核验答案的无工具子集 | 解答复验、难度适配、评测去污染；不等于提升数学的充分样本 |
| [nvidia/Nemotron-SFT-Science-v2](https://huggingface.co/datasets/nvidia/Nemotron-SFT-Science-v2) | 10 | 科学保留 | 保留少量独立知识/推理检查 | 参考依据可信；数量不足不填充低质量样本 |
| 自有新任务与教师示范 | 480 | 代码20+办公80+数据80+翻译150+写作150 | 补足开源中最缺的目标工作能力 | 全链路验证、独立评分、来源/预算明确 |
| **合计** | **1000** | | | |

数量口径进一步拆开：**现成SFT轨迹目标440 + 开源任务环境上新生成80 + 自有任务新生成480 = 1000**。因此需要新生产的示范是560，不是480。HF来源任务共520，自有任务共480；不要混淆任务来源与轨迹来源。

以上HF配额全部为“待复验”。若某源不足或许可/完整性不满足，保留该格缺口；更换来源必须更新manifest，不能偷偷重复采样凑满。译文/商务写作首轮不依赖尚未证实适合的公开合集。

## 3. 有限用途与排除

- 创意写作HQ1300：本轮主训练配额0；英文创意不替代中文商务，且shadow prompt需污染审计。可独立作风格研究。
- Nemotron Multilingual：主配额0；翻译后的STEM问答不是翻译任务，可作为未来中文保留替代候选。
- Nemotron Agentic-v2：本轮主配额0；部分模拟工具反馈、异构格式、2025创建日期。不能当真实环境成功数据。
- 结构残缺、缺tool结果或重复的派生库：暂不纳入；Fable原始/独立来源不一刀切排除，按强教师专项逐源核验。
- OfficeQA、GDPval、SpreadsheetBench等测试题：仅评测；不能借“改写”回流训练。
- 2026优先是本轮来源筛选原则；2026发布的合集可能包含旧来源，记录实际来源日期，不冒称所有内容2026新生成。

## 4. 新生产560条轨迹清单

| 能力 | 新生产量 | 任务/检查 |
|---|---:|---|
| 代码与恢复 | 20 | 小型授权repo缺陷、CLI与回归；可执行测试，拒绝改测试绕过 |
| Excel | 80 | Spreadsheet-RL训练任务；工作簿重算/结构/目标检查 |
| 自有办公 | 80 | docx/pptx/xlsx、跨文件更新与引用；检查文件可读、数字/内容一致、版面抽检 |
| 数据处理 | 80 | 清洗、SQL联表、时区单位、图表；参考计算/不变量/脚本重跑 |
| 翻译 | 150 | 中译英75、英译中75；术语表、否定/数字/单位、表格脚注与修订；双语盲审结合自动约束 |
| 写作 | 150 | 邮件30、提案30、事实报告40、纪要20、编辑修订30；来源支持、事实/约束/rubric |
| 合计 | 560 | 质量未过不计入训练 |

跨领域覆盖目标（可重叠，不额外加总）：失败后恢复、多轮约束保持、文件交付、证据引用、适度澄清。先观察20/100任务实际分布再定覆盖阈值，不硬造不自然工具步骤。

翻译/写作并非所有任务都需要工具；文件操作需真实工具，纯文本内容需真实来源与评分。禁止让LLM虚构工具反馈来冒充执行轨迹。

## 5. 用哪些组件

| 层 | 首选 | 用途 | 本轮状态 |
|---|---|---|---|
| 任务规格生成/批处理 | Bespoke Curator | 结构化任务、批量请求、重试、缓存、来源/成本关联 | 官方能力已核；本项目接入待实施 |
| 教师 | GPT6-sol候选 | 任务执行/示范；按实测补其他教师 | API正式ID/endpoint/计费/配额待核，不用会话名称推断接口 |
| 多轮执行 | 现有Uni-Agent；可复用Harbor格式 | 工作区、工具、环境重置、真实观察与工件 | 当前任务包需逐项验收 |
| 客观评分 | 专用Verifier | 代码测试、工作簿重算、SQL/CSV不变量、文件与引用检查 | 正确/错误/空控制先行 |
| 开放质量 | 独立rubric judge + 人工抽检 | 翻译语义、写作事实与表达 | 教师不做唯一裁判，先校准分歧 |
| 数据质量 | 现有脚本+版本化manifest | 结构/会话/去重/评测隔离/许可/mask | 能复用不另造平台 |
| 观测 | 原始trace + W&B/HTML | 生成/工具/评分/成本/训练关联 | W&B云端和真实trace后端仍有待验收项 |

Data Designer为未来复杂属性组合的备选；NeMo Curator等用于规模增长后的清洗。首轮不同时引入多套功能重叠编排。Curator并不替代Agent执行器或verifier。

## 6. 20 → 100 → 1K及独立评测

- 20种子：每类4个锚点，验收fixture、工具和评分。
- 100产线任务：包含前20，扩覆盖、测成本、校准grader；这100个属于开发校准池，不进入正式train/dev/sealed。
- 正式train1000：按本表配额；每个任务先取一个合格示范，额外轨迹/前缀分开计数。
- 独立dev100、sealed200：按领域20/20/20/15/15/10%分配，即dev20/20/20/15/15/10，sealed40/40/40/30/30/20；按repo/文档集合/任务族隔离。
- 总规划：100校准 + 1000train + 100dev + 200sealed = 1400个独立任务。20属于100，不再加20。

开放轨迹缺少可执行环境时，可进入经过审计的SFT候选，但效果评测必须采用真实可执行/可评分任务。不同数据可验证等级分开报告。

## 7. token与成本控制

1K不是训练token量的承诺。20/100阶段实际测各域序列长度、loss token和生成/执行/评分成本，之后填写：每域总input/loss token、序列上限、packing、采样权重、总GPU小时及教师费用硬cap。

不把长轨迹直接截断到4K/8K当完整示范。超过资源能力的轨迹可按完整决策点拆成前缀训练，但必须保留足够真实历史并共用split_group，任务数仍计1。具体截取与loss策略单独验收。

候选请求数依据合格率估算：需生成的560 / 实测合格率；例如70%时约800次首轮尝试，仅为示例，不是已测合格率或预算授权。成本包含失败、重试、沙箱、独立judge及人工抽检。

## 8. 与格式/OPD/长期扩量关系

当前教师轨迹先进入中立母本，使用已验证原生协议；[apus-chat-v1专项](apus-chat-v1-tool-call.md)独立小实验，不阻塞生产。首轮以MiMo起点对照，不中途把原版OPD与新SFT收益混算。

1K是数据工厂和学习效果pilot，不是最终高性能9B的全部训练量。只有独立效果改善、遗忘受控且成本可接受，再按失败分布增加任务族与token预算。暂不指定10万/百万条终局数字，也不照搬MiMo77.4B。
