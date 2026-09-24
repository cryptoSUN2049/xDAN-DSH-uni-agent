> 2026-09-24目标补充：最终追求接近Opus4.6的日常工作与Agent能力。本文1K配额是受控文本OPD试验，不代表完整Agent训练配方；新增同预算工作任务画像与迁移验收见[daily-agent-capability-plan.md](daily-agent-capability-plan.md)。正式改变配比须发布新实验版本，不覆盖旧设计。

# 约1000条多领域OPD：科学产线首次受控实验

日期：2026-09-24。状态：执行设计与资产盘点完成；1000条数据尚未构建，新训练未启动。归属：[产线总纲](training-production-charter.md)。用户已确认1000条试验方向；新增infra实现按项目设计审批流程执行。

## 1. 本次冻结的研究问题

同一9B起点，单27B教师、多领域纯OPD，能否在同预算独立任务上取得分域收益而不过度增加长度与成本？这次检验效果及产线闭环，不声称完成长期多教师MOPD。静态高质量专家示范只提供题目/参考/审计，不替代在线学生轨迹。首轮不同时改变mid-training、SFT起点、教师数和工具环境。

## 2. 数据配比与实查缺口

| 域 | 独立训练目标 | monitor | dev | sealed | 已有资产与必须补齐 |
|---|---:|---:|---:|---:|---|
| 数学 | 250 | 12 | 50 | 50 | Nemotron原始7732条/DeepMath57046条可读，但需逐题来源与答案核验 |
| 指令遵循 | 250 | 12 | 50 | 50 | IF16575条可读；每类规则正负控制、约束可满足性与内容要求审查 |
| 代码 | 200 | 10 | 40 | 40 | MBPP sanitized官方train仅120条；需补可执行官方训练源，不能借benchmark测试split凑数 |
| 聊天/安全/中文 | 200 | 10 | 40 | 40 | 当前Cascade片段仅240行且为头部；需固定revision分层取样、校准rubric/盲评 |
| 科学/知识 | 100 | 6 | 20 | 20 | 旧第三方Science40题只保留4题；新官方候选需前提、依据、答案核验，不直接扩旧源 |
| 合计 | 1000 | 50 | 200 | 200 | 1450独立题目目标；不足不放宽质量、不重复扩充 |

以上是设计配额，不是已存在ready集合。来源可读位置与固定归档见hf-data-archives.md；临时路径 `/private/tmp/performance-9b-hf-archive`、`/private/tmp/overnight-mbpp` 需迁移至持久版本化资产后才作为run依赖。第三方Eurus、未验收Agent任务与MoreThought维持暂不准入。

四个split按题族/源任务/仓库/翻译改写簇拆分，先去重再分割。与历史30题、已知benchmark身份联合比对；历史30题仅作回归，不纳入新sealed。旧122条标记historically_trained，不假装首次接触。报告exact/近重复/来源核验的实际范围，不能声称能排除预训练污染。

每条有accepted/rejected/uncertain裁决、source repo/revision/file/row、许可证、task/cluster ID、原始hash、domain、语言、安全标签、参考与验证依据、学生token长度。参考答案不是prompt输入，不能泄漏给学生。

科学20题/分割只是探索规模；置信区间宽时报告不确定，不能把200题总量作为每域统计充分的保证。正式主指标阈值与样本量根据训练前基线方差和最小有意义收益冻结，不能看完模型收益再定。

## 3. 算法、预算与曲线

沿用已验收文本原生VERL路径：9B学生、27B教师、LoRA、k1+PG、use_task_rewards=False、n=1、thinking-off。actor T0.8/teacher原始prompt评分T1分别记录；实际模型/模板/环境使用hash锁定，不凭目录名认定base/instruct。

先统一EOS/stop合同并测试HF/vLLM/VERL实际结束行为。训练与评测预算分别记录，跨模型评测预算一致；本次不把thinking1024失败改成通过，也不默认将预算扩大到未经测试上下文。

初始计划batch8、1000题一遍对应125个update（无补采/丢弃时）；正式总步数以冻结数据与dataloader审计确定。最多一遍首试，不自动增加epoch。保存step0及25/50/75/100/125，训练前后smoke与正式run分离。

曲线横轴同时报告update、独立题目暴露、有效response token、GPU小时；按domain分层展示正确率、评分覆盖、token P50/P95、截断/超时、监督信号与成本，禁止用总loss解释全面学习。

两卡学生/教师分配延续已验收配置。训练中monitor使用受控验证阶段/既有worker，不额外在占用GPU上启动第三套引擎；触发质量预警后暂停更新做dev确认。所有保留checkpoint在训练退出后串行独立reload跑dev，得到完整学习曲线。best仅按预注册dev规则选，最后base/best/final做sealed对照；身份相同的候选不重复造独立结果。

启动前先用2–4步测吞吐、显存和评价成本，写入最大wall/GPU小时、磁盘、teacher token、验证成本和deadline。没有填写硬cap不得RUNNING；不新增外部付费sandbox额度，不默认开放题judge外部消费授权。代码grader使用验收后的隔离执行环境。

## 4. 数据与控制状态机

candidate → reviewed → split_frozen → grader_verified → ready_for_pilot。
每域配额/来源审计/独立评分有缺口时，保留blocked_reason，不把schema通过称为高质量。

run依次通过manifest/env → grader正负控制 → base/teacher基线 → collector对账 → stop-policy故障注入 → 2–4步真实smoke → 125步有界实验 → 全checkpoint dev → sealed与报告。

必需门：数值有限、teacher评分/IDs/mask正确、指标不缺失、原始样本有来源、停止配置正确、更新和reload有效。OPD的RL有效组比例明确not_applicable。质量/长度门采用预注册预警+确认策略；纯OPD不能因reward组无方差停训。

## 5. 拟修改文件与接口（实施前审查）

| 专项 | 复用/新增位置 | 最小接口/产物 |
|---|---|---|
| 版本化数据 | 新增examples/harbor_opd_rl/data_pilot/；复用既有manifest/去重工具 | build(reviewed_manifest, split_policy)→train/monitor/dev/sealed+quality/exclusion/hash清单 |
| Grader合同 | 新增独立grader模块；复用已验证的math/IF函数 | grade(sample_id, output, budget, verifier_version)→score/status/reason/evidence；infra与task failure分离 |
| 观测collector | 新增examples/harbor_opd_rl/control/；复用file_logger解析 | normalize(raw_event)→版本化event；source/valid/missing_reason必须存在 |
| 控制policy | 同control目录；与stage/supervisor集成 | decide(run_state, metrics, policy)→CONTINUE/PAUSE/FAIL+reason+evidence；幂等、仅本run |
| 分析skill | .claude/skills/rl-training-analyst/SKILL.md及scripts | 从run manifest定位项目与算法；OPD/RL分型；证据对账、异常时间窗和根因建议 |
| W&B/trace | uni_agent/rl_insight现有facade/adapter、VERL真实producer接线 | 同run/step/sample/policy身份；后端失败显式降级，关键本地账本不丢 |
| 报告与导航 | training-production.html、既有report.py骨架、本目录实验产物 | 一个导航入口；分域学习/行为/成本/事故/源码证据；状态不得虚报 |

原有未提交修改保留，先单独保存或有界提交已验证资产，不能自动stash/reset。仍在既有隔离worktree推进，不修改主目录。

## 6. 测试与退出条件

- 数据：分组跨split无重叠、故意重复/损坏/缺来源拒绝；实际数量、token和排除原因与manifest一致。
- Grader：已知正确/错误/空输出/超时/异常样本；代码参考解在隔离环境执行，聊天盲评校准与争议处理。
- Collector：0/未启用/未计算/缺失区分；迟到重复幂等；旧run历史回放与原日志一致。
- Policy：NaN、缺teacher评分、超cap、质量预警+确认、观测中断；PAUSED不被supervisor复活；不杀其他run。
- 接线：真实2–4步从trace点击/索引定位到原始rollout/评分/梯度/ckpt；W&B与本地对账；声明完整infra通过时，verl-insight至少一条真实后端trace。若后端降级只放行有完整本地证据的pilot，infra状态保留未验收，不宣称产线全部建成。
- 恢复：如声明resume支持，必须比对模型/optimizer/scheduler/RNG及数据游标，不能以adapter reload代替resume。
- 效果：base/teacher/best/final同预算、全部保留checkpoint完整dev，按题聚类CI，未评分/infra单列。
- HTML桌面/手机可读、证据链接有效；lint与必要合同/集成测试通过后保存提交与handoff。

退出为两份独立结论：产线是否完成真实验收；本次OPD是否改善模型。允许前者通过而后者无效/不确定。没有可靠分域评分不能宣称训练全能9B成功。
