# APUS Agent SFT 数据配方 v2：Fable＋GPT-5.6核心

2026-09-24。用户明确希望Fable＋GPT-5.6成为核心数据。本文作为当前配方权威，取代v1.1的440现成/560新生目标；旧计划保留历史。**本表是目标配额，非已验收可用量；来源身份与质量审计不因品牌降低。**

## 1. 双轴原则

教师来源轴与能力领域轴分别记录。核心教师主要提供任务分解、工具决策、验证、纠错与交付过程；数据领域决定模型能做哪些工作。公开Fable/GPT5.6以代码为主，不能贴成办公/翻译标签。新的办公/翻译示范也可由GPT5.6生成，但必须记录真实返回的教师身份，不能预写Fable/GPT6。

## 2. 首轮1000独立训练任务

| 层/领域 | 数量 | 来源配额 | 目的 |
|---|---:|---|---|
| 强教师基础：代码/终端/工作流程 | 400 | GPT5.6 Sol 240；Fable原始/独立来源160 | 学习高质量执行、验证、纠错；作为最大单一数据层 |
| 本地办公 | 160 | UltraData Office40；Spreadsheet-RL train任务新生60；自有办公60 | 文件交付、跨文件一致性 |
| 数据处理 | 140 | FineEnvs80；自有新生60 | CSV/SQL/分析/图表与可复现报告 |
| 中英翻译 | 120 | 自有新生120（两个方向各60） | 术语、数字、结构与多轮修订 |
| 商务/事实写作 | 100 | 自有新生100 | 邮件20、提案20、事实报告30、纪要10、编辑20 |
| 通用保留 | 80 | Cascade60；Math-v4 15；Science-v2 5 | 指令/中文/安全/推理防退化 |
| **合计** | **1000** | **600现成示范＋400新生产** | 小规模学习验证，不是最终全部训练量 |

新生产400 = Excel60＋办公60＋数据60＋翻译120＋写作100。新生产首选可接入且通过种子任务验收的GPT5.6；GPT6作为候选比较教师，未核接口/成本前不承诺份额。Fable是否可用于新生成须另核API与用途，不把公开数据可见等同于API可用。

数据来源占比不是最优算法结论。400核心将代码/终端比重从v1的20%提高到40%，相应压缩专项工作数据；这是用户重视强教师基础后的候选取舍，须用办公/翻译/写作独立评测确认没有被挤压。若MiMo已具备足够代码能力而目标工作提升不足，下一版降低代码占比，不为了维护教师比例牺牲目标。

## 3. 核心400如何选

### GPT-5.6 Sol：240

来源：[greghavens/gpt-5.6-sol-coding-and-debugging-traces](https://huggingface.co/datasets/greghavens/gpt-5.6-sol-coding-and-debugging-traces)。优先implementation的build/debug/feature/refactor与验证恢复；数据工程类别可交叉标注，但每任务只计一个主领域。model-judge、seed-authoring另池，不能直接当成功实现。

卡片1474来源轨迹含不同kind，并不证明已有240个合格train任务。需按task/session/source_trajectory及reviewed_task分组，去重后实际验收。累积前缀只监督最终assistant动作。

### Fable：160

在以下来源联合审计后分配，不强行对每库定满额：

- armand0e原始ClaudeCode母本，避开Glint重复。
- TeichAI独立Cursor捕获，工具语义适配与长度筛选。
- AlinCiocan原始事件流，跨源重叠必须实查。
- DSFF编码调试镜像仅可证teacher子集；当前本地84行切片均未attested，不能据仓库名填入配额。

160是上限/目标，不是已确认160。会话可能含多个任务，也可能跨文件拆片，须重建task-family；不能将会话数、事件数、前缀行数直接等同独立任务。若不足，保留缺口并提出新版本，不重复采样冒充。

## 4. 可训练的数据结构

```text
DataRelease
├── manifest.json          # 来源revision/许可/hash、配额与实际数量、模板/tokenizer版本
├── tasks.jsonl            # task_id、family、split_group、domain、语言、来源
├── trajectories.jsonl     # teacher/session/harness、messages、tools、真实结果与工件
├── supervision.jsonl     # trajectory引用、target_message_index/span、loss_policy
├── verification.jsonl    # outcome、grader版本、证据、infra与可重放等级
├── splits/               # train / dev / sealed任务清单
└── rejected.jsonl        # 排除/争议及原因，不静默丢失
```

这是资产结构设计，不是已经存在的训练release。每条轨迹必须有：

- `task_id / session_id / source_trajectory_id / split_group`；重复前缀共享任务组。
- `primary_domain / secondary_capabilities / language`。
- `teacher_claimed / teacher_evidence / teacher_verified_status`，不只存一个宣传名称。
- 来源repo/revision/许可、harness/tool schema/environment版本。
- 结构化role/content/可选reasoning/tool_calls/tool_call_id，原始payload引用。
- `supervision_mode`：whole_trajectory 或 next_assistant_action。
- `target_message_index/spans`、实际input/loss token统计。
- 成功/失败/未知、grader与执行证据、截断、成本。

whole_trajectory：监督约定的assistant动作与答案，环境结果不算目标。next_assistant_action：只监督指定最后动作，历史assistant也是上下文，不重复计loss。不同格式不能用同一个“全部assistant都监督”的开关混训。

## 5. 任务数、token与采样

1000指独立任务目标，不是1000 JSONL行。前缀展开行可能远多于1000，但不得放大某个长会话权重。按任务组组织采样，显式选择每次目标动作或用组权重修正；冻结方案后做token审计。

表中任务份额40/16/14/12/10/8%，同时作为首轮期望的loss-token占比参考，不能宣称两者自然相等。真实长度审计后公布采样系数；先报告未经加权与加权后的监督分布。不要靠截断真实历史强行达标。

核心400不先单独训完再盲目接600，以免产生阶段遗忘混淆。首轮建议分层混合、独立保留来源标签；不同阶段训练只作为另一个受控实验。400强教师池与旧版160比较时保持总更新token和评测预算一致。

## 6. 开发、评测与规模

- 20种子包含在100产线校准任务内，整个校准池不进入正式train/dev/sealed。
- train1000按本表。
- dev100：代码40/办公16/数据14/翻译12/写作10/保留8。
- sealed200：代码80/办公32/数据28/翻译24/写作20/保留16。
- 共1400独立任务规划。公共benchmark另列，绝不以其答案补训练缺口。

任务、repo、文档集合、同源镜像与reviewed_task按组隔离，之后才生成/展开轨迹。小领域评测样本有限，报告置信区间和单题，不宣称覆盖全部能力。

## 7. 组件与执行门

Curator：任务规格/批处理/缓存；Uni-Agent/已验收harness：教师真实执行；专用Verifier：工具/代码/计算/文件；独立rubric+人工抽检：翻译语义与事实写作。母本中立，APUS模板迁移单独小实验，不阻塞采集。

后续执行顺序：核心来源完整文件审计与种子控制 → 教师接口/硬预算确认 → 20/100验收 → release冻结 → 同预算SFT效果实验。当前仅设计；未获得核心400合格数量、未启动新计费生成或训练。

参考：[强教师复核](strong-teacher-sft-review.md)、[20种子计划](agent-sft-seed20-plan.md)、[tool-call专项](apus-chat-v1-tool-call.md)。

## Qwen3.8-Max补充候选

已搜到单教师49772条与混合库57937条，见[专项复核](qwen38-max-sft-review.md)。教师为Max-Preview，非27B；用途条款、benchmark污染和质量仍待放行，当前配额0，不改变本版1000分布。
