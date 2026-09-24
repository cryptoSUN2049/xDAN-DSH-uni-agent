# ms-swift 与 VERL 数据适配方案

> 2026-09-24字段设计已冻结：[统一训练数据字段契约v1](统一训练数据字段契约-v1.md)为母本columns权威入口。下文早期拟议record_id/tools等名称以新映射为准；框架导出仍待实现验收。

2026-09-24。接口核验与设计，尚未实现或通过框架运行验收。每个原始源需要明确解析规则，但不为每个源重复维护两套清洗逻辑。

## 分层

原始15库（不可改写）→逐源解析/准入→统一中立母本→固定任务组/配方/20K→ms-swift导出与VERL导出→真实tokenizer与loss验收→训练。

同一个20K task manifest生成两个框架视图；行展开不同不等于新增任务。source revision、record/task ID、teacher evidence、语言、domain、原始消息及监督策略保持可追溯。

## 原始结构的适配

| 原始结构 | 来源例子 | 必需处理 |
|---|---|---|
| messages对象数组 | MoreThought、GPT原始轨迹 | role/content/reasoning/tools标准化；保留target_message_index，检查损坏 |
| messages或messages_json为JSON字符串 | Premium、CodeFlame部分 | 解析一次，校验role与调用ID/参数/顺序，不能把整段JSON当普通回答 |
| prompt/reasoning/answer | HelioAI | 将问题与assistant推理/答案分层保存，再由目标模型模板渲染；俄语过滤 |
| 原生事件流 | Armand、Alin、Cursor等 | 重建session和消息顺序；区分用户、assistant、工具结果、内部元事件 |
| instruction/input/output或response | CodeFlame部分 | 合并输入及标准assistant，但教师未知不因转换就放行 |
| 任务/文件/评分环境 | Spreadsheet-RL | 不是现成SFT，必须有真实教师执行示范；不能仅改字段变SFT |

unknown_tool或缺失真实参数不属于单纯格式问题；不得猜造工具语义。工具定义有来源才恢复，无来源先隔离。

## 中立母本合同

核心字段：record_id、task_group、source_repo/revision/item_id、teacher_claimed/evidence、language、domain、messages、tools、supervision、quality_status、raw_hash。

messages保留system/user/assistant/tool语义、content/reasoning、tool_calls(id/name/arguments)、tool_call_id。supervision显式区分whole_trajectory和target_message，并用原始消息ID映射；不依赖转换后数组索引巧合。工具返回和用户内容不监督；历史assistant是否监督由策略决定。

## 两个导出视图

| 项目 | ms-swift SFT | 当前仓库VERL SFT |
|---|---|---|
| 建议文件 | JSONL，按固定模板注册/解析 | Parquet，messages_key/tools_key显式指定 |
| 普通消息 | messages role/content | messages role/content，经模型tokenizer模板 |
| 工具 | 官方Agent合同支持tool_call/tool_response（tool等价）及tools JSON字符串，由agent_template渲染 | 模型原生支持的assistant.tool_calls与tool响应、tools定义；不能直接把swift专用role喂入 |
| 监督范围 | 官方文档有逐assistant loss布尔与loss_scale；转换拆分工具消息后仍须测试实际labels | 当前MultiTurnSFTDataset默认监督所有assistant，忽略源target_message_index；需要custom_cls精确实现mask |
| thinking | 中立字段经目标模型模板映射，不把某个文档示例的Thought前缀硬套MiMo | enable_thinking及模板参数显式固定，检查整段与逐轮tokenization一致性 |
|验收|真实encode后的input_ids/labels/loss_scale检查|真实input_ids/loss_mask检查，不能仅验Parquet读得开|

不得宣称框架已支持MiMo9B本轮配置：具体ms-swift版本/model_type/agent_template仍需安装环境与小步实测。首轮保持MiMo已学模板，不默认换成Qwen或ReAct；必要时注册模板适配。两框架导出后的目标token及语义监督应等价，数值loss可因实现有差异，不能强求浮点逐位相等。

## 不是SFT格式与OPD/RL格式共用

本轮20K是SFT：教师示范作为监督。未来OPD/RL一般以prompt、domain/teacher route、任务环境和reward/verifier等合同驱动学生rollout；教师完整答案不能直接改名当在线OPD。可共享原始任务身份，但单独生成OPD/RL视图与防泄漏约束。

## 必须通过的golden验收

- 单轮、多轮、thinking、单/并行工具、工具失败、目标消息监督、长序列各有固定样本。
- user/tool等目标mask为0；仅目标assistant非零；累计前缀不重复监督历史。
- 原始中立→导出→渲染，调用name/arguments/id/结果对应保持不丢失；相邻assistant合并后mask仍正确。
- 未闭合thinking、空监督、工具名损坏、无效参数、不可恢复截断拒绝；长轨迹不静默截断。
- 两导出使用同一个source/task/split manifest和hash；固定dev不因框架重新随机切分。

## 依据

- [ms-swift自定义数据集](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Customization/Custom-dataset.md)：messages及loss/loss_scale；2026-09-24经Context7核验，实施时固定版本。
- [ms-swift Agent支持](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Agent-support.md)：tool_call/tool_response与agent_template合同。
- 本仓`verl/verl/utils/dataset/multiturn_sft_dataset.py:233`：assistant默认全监督；`verl/verl/trainer/config/sft_trainer_engine.yaml`：messages/tools、custom_cls、模板token mismatch警示。

CodeFlame规则已由用户明确确认：从数据中去掉Gemini 3.1（含3.1 Pro）；保留原版记录，派生版本执行排除，未知/冲突教师隔离。此数据筛选规则与框架格式适配是两件事，规则已确认不代表全量过滤已完成。
