> 2026-09-24目标澄清：高性能9B具体优先接近Opus4.6的日常工作与Agent能力（交付物、工具、多步恢复、人工介入与成本）。OPD主线独立验证，midtraining并行准备；数学/知识作护栏。新画像方案见daily-agent-capability-plan.md，未实测的Agent/teacher优势填not_measured。

> 2026-09-24 导航更新：唯一HTML入口 [我们的科学训练产线](../../docs/performance-9b/training-production.html)。按产线架构与阶段目标双维组织；MiMo原报告为研究依据，architecture.html保留历史。组件选型不等于已部署，专项以验收结果完成。

# Performance-9B：MOPD 核心项目记忆

更新：2026-09-24。性质：目标、已核验约束、设计判断；不是训练完成报告。

## 当前主目标与权威索引（2026-09-24）

用户再次明确：核心是科学、专业、全流程、可观测、可分析的大模型训练产线，包括如何发现问题和受控解决问题、核心指标与infra；1000条OPD是首个验收实验，而不是把目标缩为一次训练。

- [唯一HTML入口](../../docs/performance-9b/architecture.html)
- [产线总纲：指标/诊断/修复/职责](../../docs/performance-9b/training-production-charter.md)
- [项目索引与冷启动](../../docs/performance-9b/project-index.md)
- [1000条执行设计](../../docs/performance-9b/training-pilot-1k-plan.md)
- [详细v2组件合同](../../docs/performance-9b/training-system-v2-design.md)
- [真实训练验收](../../docs/performance-9b/overnight/index.html)

当前阶段明确多领域单27B教师OPD，长期MOPD目标不变。当前两份模型的文本原始token/评分/loss/更新/reload已通过实测；thinking1024仍fail，2048单例1751闭合。旧“待验收”“先纯RL”表述按历史解释。

建设闭环：数据版本/实验注册→原生文本或Agent执行→统一run/step/sample/policy身份→本地事实账本/W&B/verl-insight→固定验证/行为/数值/算法适用信号/infra/成本→预警与确认→安全暂停→根因实验→最小修复回归→独立评测/归档。纯OPD不能用GRPO有效组门；missing不填0，PAUSED不被supervisor重启。

真实缺口：W&B offline，完整指标映射/实际trace后端/质量止损尚未证明上线；代码执行与聊天评分不齐；旧30题非sealed。原始大题库不等于1000高质量ready。新pilot数据未构建、新扩训未启动。

## 1. 用户目标与资源边界

- 目标是全面高性能9B，主线是多领域、多教师在线蒸馏MOPD；不能擅自缩为SFT或单教师OPD。SFT是知识导入/对照，单教师probe是基础验收。
- 训练体系同时完善：固定验证集、行为预算、有效RL组比例、自动暂停、W&B/verl-insight观测与可追溯链路。
- 用户提供的资源信息：现有Qwen3.8-27B开放教师，以及Fable/Opus/GPT来源高质量SFT数据；超大教师留到后期。具体型号身份、数据质量及超大模型硬件需求尚未独立核验。
- 学生现用Qwen3.5-9B；与27B的当前文本评分兼容性已实测，分域教师优势与广泛收益仍待更大独立验证，不因同属Qwen而默认成立。

## 2. 已核验的VERL约束

- 官方OPD文档明确：teacher必须共享student tokenizer/vocab。没有模型家族名称检查，不等于支持任意异族。
- 当前代码直接向教师传学生sequence_ids，读取prompt_logprobs；未提供通用跨tokenizer对齐。
- MOPD默认distillation.teacher_key=data_source；样本字段匹配teacher配置key，一样本选一教师。不是所有教师投票或融合。
- domain可按math/code/swe/science/instruction_chat/tool_use设计；中文、安全作为跨域标签。domain、上游来源与teacher_id分开记录。
- 自定义domain路由需验证loader→DataProto→rollout字段保留。六域不强制六教师；一个通用教师覆盖多域仍是单教师。
- 入口：verl/examples/on_policy_distillation_trainer/run_qwen3_8b_mopd_fsdp.sh。
- 路由/评分：verl/verl/experimental/teacher_loop/teacher_manager.py。
- 损失：verl/verl/trainer/distillation/losses.py；示例k1+PG，关闭任务奖励时优势为stopgrad(log p_teacher - log p_student)，作用于学生实际生成token，带mask/裁剪等处理。

## 3. 打分的原理边界

- token评分比较的是同上下文、同一token事件的概率；模型参数量、层数或MoE形式并非数学硬条件，token语义对齐才是。
- 不同tokenizer会切出不同边界和前缀，按位置相减或复用token ID都不成立。重分词后平均分摊概率只是近似，不能称为原来的严格token KL。
- 完整字符串/片段概率对齐在原理上可研究，但需定义共同事件、边界、结束符和概率归属；简单累加两套token logprob不自动等价于字符串分布KL。当前项目未实现/验证此路线。
- token logprob反映教师行为偏好，不是正确性或thinking逐步真值。可能奖励熟悉措辞、冗长或错误延续。
- 同族只减轻对齐难题，不证明教师更强、评分正确或训练有效。
- 答案级judge、动作级语义/执行评分不要求相同tokenizer，但属于奖励机制，不能冒充原生token级MOPD。

## 4. 静态强教师SFT数据怎么用

- 异族教师文本可以用学生自己的模板/tokenizer做离线SFT，不要求共享tokenizer。
- 可从SFT数据提取问题、domain、环境与验证依据作为MOPD提示池；学生必须重新在线生成。
- 已保存教师答案/thinking仅作示范、审计、参考或辅助SFT，不替代学生on-policy轨迹，不产生未取得的在线teacher logprob。
- 同题多教师答案/翻译/切片必须按任务族分组，不能跨训练与验证。
- 工具轨迹不能将旧教师的工具结果接到学生新动作之后；必须真实重执行或验证环境状态一致。
- 普通闭源生成API、只返回其自身生成token logprob的API，均不自动满足任意学生续写逐token评分需求。

## 5. 推荐路径与对照（设计建议，未验收）

A. 成本较低：精选异族SFT→9B；测现有27B在各域是否强于SFT后的学生，再决定各域OPD是否值得做。
B. 真正MOPD：用各域精选示范适配共同兼容开放底座，形成领域adapter/checkpoint；验收互补优势后，通过在线MOPD整合到9B。
- B中的领域专家是闭源知识的中间代理，不能宣称等同原闭源教师；多加一层蒸馏可能丢失能力。
- 同一底座不同领域checkpoint可以构成多教师，不要求不同厂商。不同路由名或prompt不能冒充不同专家模型。
- 对照至少区分起点、精选SFT、单教师OPD、多教师MOPD；分域收益与通用保留同时报告。
- 双卡多教师常驻、adapter评分切换、分时轮换均未验收；不假定已有支持、不承诺容量和时长。

## 6. 数据与监测原则

- 首选原始可追溯来源和可核验样本，年份/教师品牌/长thinking都不是质量证明。2026为主参考，不将旧源新包装当全新数据。
- MoreThought当前不进入首轮；理由与各来源清单见首次训练数据集合.md。HF已归档不等于训练准入。
- 先固定验证与行为预算，检查成功率、长度、超时、工具成本、thinking/action/final结构和参数真实更新。
- GRPO组全对/全错导致组相对任务奖励无差异，不能据此推断纯OPD无信号；纯OPD要看教师评分覆盖、概率差与梯度。
- 失败传播、checkpoint保存重载、模板/掩码/评分对齐必须真实通过；旧日志和设计不代表当前运行状态。

## 7. 冷启动与下一步

1. 先读本文件，再读首次训练数据集合.md顶部v0.2主目标；其后v0.1只是辅助历史方案。
2. 核查当前分支/改动、实际训练状态，保留既有工作，不重复启动。
3. 审计现有异族SFT数据的来源、domain、正确性、长度、污染与许可证。
4. 验证9B/27B tokenizer、特殊token、模板及同轨迹评分；做分域教师/学生能力对照。
5. 冻结domain→来源→teacher→评分接口→verifier映射与显存预算，再设计最小MOPD实验。

## 8. 依据与相关入口

- [VERL官方OPD](https://github.com/verl-project/verl/blob/main/docs/algo/opd.md)：2026-09-24实际读取，共享tokenizer/vocab约束明确。
- [Nemotron-Cascade 2 §4.4](https://arxiv.org/html/2603.19220v2)：2026论文，从共同SFT起点的领域最佳checkpoint选择教师，利用共同tokenizer避免额外对齐。
- 数据方案：docs/performance-9b/首次训练数据集合.md。
- HF归档：docs/performance-9b/hf-data-archives.md。
- 训练执行记录：tasks/verl-uni-agent-harbor-opd-rl/performance-9b-execution.md（历史时间戳，不能替代实时状态）。

## 2026-09-24：9B与27B文件实查（不是完整评分验收）

- 官方固定revision：Qwen3.8-27B `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`；Qwen3.5-9B `c202236235762e1c871ad0ccb60c8ee5ba337b9a`。
- 两者architecture均Qwen3_5ForConditionalGeneration，config词表大小248320；27B为64层/hidden5120，9B为32层/hidden4096。不据此推断相同base血缘或预训练数据。
- 官方vocab.json/merges.txt的git对象相同，远端/workspace/models两目录SHA256也相同。
- tokenizer.json：9B SHA256 5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42；27B 0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3。服务器与官方对应一致。
- 解析比较：model/normalizer/pre_tokenizer/post_processor/decoder相同；27B added_tokens额外含248070–248076七个audio/TTS token。共同added token无属性差异。不能称完整tokenizer相同；新增ID在学生logit空间中存在不意味着其语义已训练。
- 模板差异：27B thinking开启默认reasoning_effort=xhigh并注入说明；支持preserve_thinking且默认保留历史thinking；9B从content解析think块的处理不同；工具参数序列化有差异。
- 文本共享token子空间具备进一步验证基础；top-k中出现扩展token的概率质量、运行时AutoTokenizer覆盖行为、实际prompt/response mask和教师评分位置尚未验收。
- 本次只读比较模型文件，未加载权重、未改模型文件、未启动训练。需继续实际编码/模板探针及评分验收，不能据文件相似判定OPD已通过。

## 2026-09-24 Agent SFT 与协议迁移

用户希望继承MiMo数据思路，用强教师真实执行与高质量HF资产建设Agent SFT。权威方案为docs/performance-9b/agent-sft-data-production-design.md与mimo-agent-sft-9b-report.html。保留中立轨迹，先用Qwen原生导出；Apus协议待明确，不默认新建特殊token。SFT不是OPD，模拟工具反馈不是环境执行证据，静态数据不自带在线teacher。先选模型起点并隔离模板迁移干预，再做单/多harness等预算对照。
