# Uni-Agent 系统规划 v3：原生链路与四类能力

日期：2026-09-09。状态：2026-09-09用户已批准按v3无人值守实施；新能力训练尚未验收。

## 1. 从旧总方案继承什么

旧版 dsh-v3-live-smoke/uni-agent-system-plan.html 的正确骨架是：固定 DSH Harness → 模型学习 → 独立任务收益 → 受控 Harness 进化；原生 DSH 与 Harbor 是两个可选任务入口。沿用它的模块化职责，不继承旧版本号、0/8 状态或旧部署结论。
当前变更：原生链路先完成复建及 DSH、记忆、上下文、RSI 的分层验收；Harbor训练与Modal后置。增加跨会话记忆链的独立身份。既有v2作为历史方案，本页为新主入口。

## 2. 目标与边界

目标模型先固定Qwen3-4B，训练集成主仓本项目，DSH本体与历史研究归DSH-Exp，ContextPilot提供方法与版本化产物。保持当前Uni-Agent/VERL/DSH pin，不因路线调整再升级依赖。
“完整”拆为工程、能力、泛化、性能四张报告。一次更新不等于能力提升；四类任务能运行不等于四类能力提高。原生M1已有更新/reload通过，不重做为零起点。
本次不做SFT，不启动付费teacher/OPD、新GPU或Modal；数据生产仍由用户安排的会话承担，本仓定义RL任务、准入与验收合同。单卡异步做有界对照，不能阻塞能力训练。

## 3. 模块与真实接线

冻结任务/划分/能力标签/模型/Harness/预算
→ Uni-Agent Task协调、session分配
→ DSH SDK/runtime（唯一Agent Loop，工具/记忆/上下文动作）
↔ Gateway ↔ 当前策略推理服务（真实token、mask、logprob、policy版本）
→ 独立verifier与fresh receipt → 完整group准入
→ TransferQueue → 配对VERL更新 → checkpoint
→ 独立reload → 同预算paired评估 → 发布报告。

记忆存储属于显式任务状态；上下文选择属于动作前可观测决策；RSI候选仓与晋升控制器在任务执行外层。两者都不新增第二套Agent Loop。不从离线文本伪造on-policy rollout或logprob。
Harbor仅后续替换任务/环境入口，不能成为这条原生路径的依赖。

## 4. 正交实验合同（设计字段，不冒称已实现API）

每个run保存：task_id、family_id、split、capability_tags、数据/评分摘要、模型和Harness身份、学习方法、调度模式、部署环境、预算、证据等级。能力标签允许交叉，不能把RL/记忆/LoRA/异步当同一层分类。
TaskSpec：目标、动作空间、初始可见输入、成功判据、失败分类、允许持久产物、预算、版本与划分。
EpisodeEvidence：run_id、episode_id、gateway_session_id、policy_version、trace/receipt摘要、真实完成状态、reward、eligibility、拒绝原因。
MemoryChain：chain_id、writer_session_id、reader_session_id、允许传递的artifact摘要及访问记录。写入和读取可对应不同Gateway session，用显式chain绑定；绝不复用旧session冒充新会话。
CandidateRecord：evolution_run_id、candidate_id、parent_id、候选内容摘要、训练来源、开发验证、晋升/拒绝/回滚记录。评分器、封存集、凭据不在候选可修改范围内。
ConsumerAudit：group_id、sample_index、训练消费批次、policy版本范围、拒绝/过期/取消原因。新增字段需适配现有schema，不另造一套通用训练器。
四种循环分别标识：任务episode、跨会话chain、采样更新training run、候选演化run。ContextPilot树分支partial rollout与调度暂停恢复不互相充当证据。

## 5. 四类能力的任务与验收

| 能力 | 首批真实任务 | 独立结果与奖励 | 防止伪通过 |
| --- | --- | --- | --- |
| DSH调度 | 根据能力目录选择工具；正确define/run/stop/undefine；依赖组合；故障后恢复 | 业务结果正确+生命周期合法；记录非法调用、恢复成功、残留资源 | 不能只背API；用新工具组合/故障类型留出，已有邮箱4/2只作工程回归 |
| 跨会话记忆 | A接收约束/决定/来源，写入记忆；全新B仅获得允许记忆，主动检索并完成后续任务 | B任务成功、关键事实准确、来源有效；奖励追溯A写入决策 | B不可获得完整A对话/答案；按整条chain划分，加入冲突/过期/拒绝写入负例 |
| 上下文管理 | 长任务中保留依赖/未完成项，选择检索、摘要或裁剪；恢复后继续工具任务 | 终局正确、关键事实不丢、错误遗忘率；成本仅次级 | 必须用动作前真实观测；长度减少不能抵消事实损失；多context逐请求保持token与mask |
| 受控RSI | 识别失败→提出profile/工具组合/记忆规则候选→隔离比较→采纳或回滚→新任务复用 | 独立开发任务的预算约束收益与无回归，验证真实持久候选和回滚结果 | 输出promote字段不算晋升；不能改verifier/封存集；不以自评取代执行 |

有效、已完成的策略失败可以得0；基础设施故障、不完整或不可信证据另列，不伪装为普通0分供优化器消费。奖励版本先冻结，再训练；不能根据结果反向修改成功标准。
记忆链先定义可审计的chain结果→两会话轨迹关联→group消费方式，验证双方token归属及预算；未实现该合同前只做评估，不将B分数任意复制到A宣称已正确训练。

## 6. 分阶段路线与退出条件

| 节点 | 工作 | 完成条件 | 当前状态 |
| --- | --- | --- | --- |
| N0 原生可复建 | 独立干净checkout/venv、固定产物、安装→预检→eval→train→audit→reload | 真运行通过；声明缓存/模型/wheel复用边界；脚本不依赖Mac Harbor隧道 | M1已通过，完整新环境复建待验 |
| N1 四能力基线与合同 | runtime动作可达性审计；每类至少2种任务族的最小工程样例，含失败/负例 | 区分缺能力接口与模型策略失败；四类都能执行、评分和关联证据 | 待实施，数量仅诊断起点 |
| N2 DSH能力实验 | 固定Harness在线RL，先小批试训再扩 | 有效更新/reload；同预算独立任务改善，报告不确定性和回归 | 邮箱工程通过不代替此项 |
| N3 记忆与上下文 | 分开训练/评估两个决策，再联合长任务 | A→B真正隔离、事实保真；两能力各自独立测试，不互相替代 | 待消费者/动作审计 |
| N4 受控RSI | 先评估候选生命周期，再训练提议/验证/采用/回滚行为 | 持久候选在新进程/新任务可复用，回滚真实有效；独立测试收益 | 当前报告字段不足，未完成 |
| N5 联合模型发布 | 固定模型与Harness，四类封存测试，完整重建与独立reload | 四类逐项出结果，任何未通过项不能标成整体能力通过 | 待N2—N4 |
| P1 单卡异步支线 | N0后固定任务/预算的colocate_async对照 | 配置真实生效、更新/reload、暂停和取消正确；报告有效任务/分钟及质量 | 上游可用，入口透传待适配，未GPU验收 |
| H 后续Harbor | 优先复用现成eval入口，必要时恢复严格DSH RL桥接 | 独立记录标准任务评估/训练证据 | 现有Docker资产保留，GPU训练暂停 |

按验收门排期，不承诺未经baseline估算的天数。N0完成后N1准备可与P1小实验交错，但不同时抢占单GPU。P1若未改善吞吐，记录结果并回到sync推进N2，不无界调优。能力效果不理想先检查任务/奖励/动作可达性，不单纯加训练步数。

## 7. 数据与效果实验

按family、memory chain与候选谱系分割后再渲染；禁止仅替换字符串作为独立泛化任务。训练集产生梯度，开发集用于选配置/候选，封存测试仅用于最终评估，不进入RSI适应回路。
先做各能力小样本baseline诊断，不将固定条数当效果保证。数据生产任务需返回manifest、schema、source、split与可执行verifier；不把SFT示范直接当在线RL轨迹。模型必须用当前policy现场采样。
效果对比固定解码、工具、信息、预算与任务身份；报告逐题结果、paired差值、区间及失败类型。基线满分的任务仅作回归，不作为提升证据。第一轮数值提升为探索性，基于baseline冻结目标阈值和评估方案后才做正式能力判定。
RSI采用四格：M0H0、M1H0、M0H1、M1H1。分别识别权重学习、Harness变化和交互；候选H1只用训练/开发集选，四格用相同封存任务。更大模型对照尚未授权调用，不是当前必要门。

## 8. 文件清单与实施约束

本次设计交付：native-capability-roadmap.md、uni-agent-system-plan-v3.html；更新active-engineering-goal.md、acceptance-tracker.md、handoff.md、tasks/todo.md与lessons.md；旧goal完整归档。
拟实施（审批后逐批确认实际改动）：复用examples/dsh/ops启动/audit/reload与examples/dsh/train_qwen3_4b_online_rl.sh；在examples/dsh/下增加版本化能力任务配方；在现有uni_agent/tasks/dsh/、agents/dsh/边界按真实缺口补最小适配；deployment/下复用预检/监督/锁文件，不复制trainer。
异步透传只允许sync/colocate_async白名单与正warmup，打印与实际argv一致，默认sync不变。不存在API前不在手册给出虚假的“一键四能力训练”命令。

## 9. 验证计划

CPU：非法动作、Session v2事件消费、动作前观测、防答案泄漏、chain隔离、候选复用/拒绝/回滚、证据错配/重放/篡改、异步argv边界。测试真实契约而非复制实现。
真实E2E：每能力正常/合法失败/取消，Gateway token→receipt→训练消费；记录有限非零梯度、逐张量变化、base冻结、optimizer进度、checkpoint独立reload；真实环境资源清理。
复建：GitHub精确commit拉取，新venv且记录artifact哈希，沿用下载缓存需明确；标准checkpoint=/workspace/uni-agent-g1/checkpoint/<run>，私有日志/root/runs，脱敏归档到持久卷。禁止将共享盘权限当私有凭据保护。
视觉：HTML离线可读、移动端无页面横向溢出、导航/链接有效；视觉通过不代替训练验收。每验收批次Ruff双门、相关测试、commit/push并更新handoff。

## 10. 现有证据与未完成事项

M1 v2-r4：2步真实RL，504 LoRA改变/399 base冻结，10/10组消费；独立reload两条新评估通过。两条公开题baseline已满分，不能声称提分。
Harbor：v2 Docker四类模式通过；cleanup截断负例→cancelled空产物→新job成功的真实Docker验证通过，尚未完成Harbor学生RL与reload。成果保留，非当前前置。
平台goal已于2026-09-09核实为新版原生四能力目标，状态active；本文件与active-engineering-goal为权威计划，未完成必要验收前不标完成。
