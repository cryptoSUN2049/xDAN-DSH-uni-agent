# 强教师SFT专项复核：Fable 5 / GPT-5.6 / GPT-6

2026-09-24。纠正：此前过度依据部分Fable派生库问题，将原始/独立来源一并弱化；数据画像中的评级冲突未充分消解。强教师示范应当单列为Agent SFT基础资产，但身份、完整性、任务验收、许可与独立性必须分别确认。

本轮为官方卡/元数据及已有本地切片复核，不是全量数据验收。卡片所述规模是发布者统计，不是我们已确认可用数量。

## 1. 恢复优先级的来源

| 来源 | 本轮证据 | 当前决定 |
|---|---|---|
| [greghavens/gpt-5.6-sol-coding-and-debugging-traces](https://huggingface.co/datasets/greghavens/gpt-5.6-sol-coding-and-debugging-traces) | 当前卡：17939累积前缀行，1474来源轨迹，含629独立model-judge和4seed-authoring；真实Codex执行、工具输出、验收和复核；CC-BY-4.0 | 提升为优先核心来源；implementation/judge/seed分层。按task/session而非行数计量，先train分区筛选 |
| [armand0e/claude-fable-5-claude-code](https://huggingface.co/datasets/armand0e/claude-fable-5-claude-code) | 画像local X与HF S指向同revision；重复关系与母本价值被混为一谈。已有切片有完整动作/反馈，raw trace可见模型字段；thinking有空块 | 恢复为优先原始来源；与Glint家族二选一。无明文thinking不排除action/answer SFT；元数据层级冲突需逐会话核验 |
| [TeichAI/Fable-5-Cursor-Traces](https://huggingface.co/datasets/TeichAI/Fable-5-Cursor-Traces) | 画像记录独立Cursor来源、工具schema；已有切片含assistant和tool消息 | 优先独立来源审计；Cursor工具语义与APUS不同，不能只改工具名后训练 |
| [AlinCiocan/fable-5-claude-code-traces](https://huggingface.co/datasets/AlinCiocan/fable-5-claude-code-traces) | 卡片18会话/9497事件；切片是原始事件流，不是现成messages SFT；卡提示可能与其他源重叠，不能沿画像声称已零重叠 | 小规模高价值候选；先重组去重、会话完整性与来源核验 |
| [DSFFGFG456/fable-5-coding-and-debugging-traces](https://huggingface.co/datasets/DSFFGFG456/fable-5-coding-and-debugging-traces) | 画像记录原greghavens库镜像；存在model_attested/observed_models。本地84行切片均model_attested=false且teacher_model为空；卡称2380轨迹→12490前缀行，均非我们验收数量 | 优先全量身份审计，不能直接计为已证明Fable。只在真实存在且通过检查时接纳attested子集；字段true也非独立密码学保证 |

### GPT-5.6必须正确使用的细节

- 一行是“累积上下文+一个下一步动作”，不是独立任务。loss只作用于 `target_message_index` 对应最后assistant动作；之前assistant消息只是上下文，不能再次全量监督。
- 上游 `source_trajectory_id/task/session/split` 必须保留；task变体与judge的 `reviewed_task` 应在同一split组，避免implementation在train、review在eval。
- `kind=model-judge`包含accept/reject，reject是审核结论，不等于这条审核轨迹质量差；但也不能当作成功编码示范。首轮主要选implementation，judge用于单独质量/审查子池。
- `exec`携带JavaScript编排源码。需要兼容runtime或语义保持转换；不能改成bash名字就认为工具兼容。
- 官方卡明确隐藏reasoning不导出；可用的是commentary、动作选择、修正和可见摘要。不要宣传成完整内部CoT。

## 2. GPT-6当前搜索结果

本轮使用HF datasets API搜索 `gpt-6` / `gpt6`，两组返回相同4个仓库。检索不证明整个HF再无其他未按名称索引的来源；现有画像未明确列出经审核GPT-6通用Agent母本。

| 来源 | 实际查看到的内容 | 决定 |
|---|---|---|
| SakitsunaAI/gpt-6luna | 2026-09-23创建；无README，文件名mimo7b_coding_math_reasoning_100k.jsonl | 未确认teacher/许可/生成证据，不纳入，仅待查 |
| Choiszt/humanclaw-gpt6-lowthinking-results-logs | 无README，文件树大量embodied评测视频/结果 | 与当前办公Agent训练目标不符，不默认训练 |
| yssssjtu/gpt6_robotdata | 无README，机器人动作/相机数组，含AgiBotWorld路径 | 机器人领域资产，不当通用Agent SFT |
| [HaomingLuo/GPT-6-FEniCSx-Single-Attempt-Pass-Rate](https://huggingface.co/datasets/HaomingLuo/GPT-6-FEniCSx-Single-Attempt-Pass-Rate) | 卡称GPT-6 Astra，496个通过的科学计算代码；无工具生成，外部控制执行；明确来自PDEAgent-Bench评测 | 可作科学计算专项研究；首轮通用Agent配额0，避免将评测成功答案混入训练 |

结论：**GPT-6应列为重点自生产教师候选，但暂未找到足以直接加入本轮的通用Agent开源母本。** 不用GPT-5.6改名冒充GPT-6，不把“名称含GPT-6”视为身份验证。

## 3. 现有配方修订（不增加首轮1K总量）

保留用户工作领域配额：代码200、办公200、数据200、翻译150、写作150、通用100；代码200内部改为：

| 来源 | 原配额 | 修订目标 | 理由 |
|---|---:|---:|---|
| GPT-5.6 Sol原始轨迹 | 40 | 100 | 提高强教师工程过程、验证与纠错的直接监督 |
| Fable原始/独立来源池 | 0 | 60 | 恢复被误弱化的母本；跨来源去重后分配，不保证各库现成可用 |
| Open-SWE成功轨迹 | 120 | 20 | 保留公开仓库与另一种行为分布对照 |
| 新生成代码任务 | 40 | 20 | 补我们工具链/预算/恢复缺口 |

Fable60为条件目标，若合格独立任务不足则不凑数，记录缺口并另提补采方案。其他领域不被代码挤占；未来发现Fable/GPT在办公/写作的真实数据可按同域替换，不根据教师名把代码轨迹贴上办公标签。

总数变为：**440现成SFT + 80开源Excel环境新生 + 480自有任务新生 = 1000**。新生产轨迹560条（原580）；其中可用GPT6-sol等教师真实执行，但该身份与API、成本仍需实核。

强教师“根基”的意义是可靠决策过程、验证和纠错覆盖，不是所有token都来自一个品牌。保留独立评测与通用回归；初轮小样不能保证显著能力提升。

## 4. 下一步实查合同

1. 对上述5个优先来源固定revision/许可并获取可用完整文件；卡片/切片≠全量ready。
2. 统计独立任务、session、重复前缀、教师可证比例、工具配对、上下文截断、真实成功证据。
3. 分别定义whole-trajectory与next-action数据的mask，保存真实token控制案例。
4. 生成逐源接受/有限用途/拒绝清单；明确任务型能力与可见reasoning层级。
5. 对比“含强教师池”与原配方时冻结训练token/预算，避免将更多计算误当来源质量收益。

原始画像完整保留，不覆写旧评级；本复核解释冲突并作为当前准入指导。不得把伪造、镜像重复、缺工具结果的派生库因为用户重视教师品牌而放行。
