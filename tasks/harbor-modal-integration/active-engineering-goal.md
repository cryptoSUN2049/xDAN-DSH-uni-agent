# 当前主线：用真实记忆与上下文任务验收原生 RL

更新：2026-09-10。最新目标按下述P1→P2→P3推进；原生优先，Harbor与异步后置。

权威设计：[系统方案v3](../../docs/harbor-modal-integration/uni-agent-system-plan-v3.html)；[任务与合同](../../docs/harbor-modal-integration/native-capability-roadmap.md)。用户已批准v3实施，按有界作业与分阶段验收推进。旧G1完整保存于engineering-goal-before-native-redesign-20260909.md，不删除失败或通过证据。

## 最新总goal：先工程闭环，再验证任务驱动的记忆/context能力

> 在固定DSH、Uni-Agent、VERL、模型与数据版本下，先完成work-state-memory-core-v1的真实GPU在线RL、可归因有效更新、checkpoint与独立reload；再通过同预算训练前后对照、记忆消融和独立封存测试，验证保存、索引检索、事实更新与克制保存对后续任务的帮助；随后以独立里程碑扩展真实offload/compact和调试/研究等跨场景任务。各阶段留下原始证据、可手动复跑指南及commit/push，明确区分执行成功、有效学习和能力提升。以任务恢复成功与事实保真衡量，不以文件数量、压缩率或GPU占用替代效果。

### P1：当前必须先完成——新版课程原生RL闭环

沿用G0—G6。520训练/160公开开发资产已落盘。固定511源码的core-train-r4已完成16步，16组/64条A-B链/128唯一轨迹实际消费审计通过；全程优势与梯度为0，最终LoRA B全0，有效更新门未通过。母step16独立reload：WS01/03/05正式审计通过、业务reward0；WS06 writer达到max-tokens，B未执行、该val退出1，失败证据已保存。预算r1已证实真实生成上限8192，发现精确触顶原因漏记；修复5e6b326已通过Linux22测试。core-budget-val-r2真实触顶8192及原因字段校验通过，原未完成拒绝保留；正常路径core-budget-normal-r1已exit0，A1037/B302 token、1组2条消费及after_run通过，业务reward0。关机归档7025文件已验证；不启动新GPU任务，reader诊断已获用户明确批准，CLI/CPU实现完成，GPU canary待恢复后执行。初始16步是诊断，不代表全课程已消费或充分训练。下一步按reader操作指南执行公开配对诊断，定位工具/写入/检索瓶颈；不盲目追加全零训练，不追认有效学习。

### P2：工程通过后——已有能力的独立效果验证

- [ ] 固定训练前base与训练后checkpoint、提示/工具/上下文/token预算；记录逐题paired结果及抽样不确定性。
- [ ] 在训练前冻结独立测试场景/结构变体与实例；当前160公开dev不能改名充当封存测试，不能用封存结果调整提示/奖励/挑checkpoint。
- [ ] 训练前后对照：任务成功率、必要事实保真、权威/作用域冲突处理、约束违规、恢复成本与重复劳动；按任务族分项报告。
- [ ] 记忆消融：仅在确实依赖记忆的题移除必要记忆，与正常链同预算比较；WS06无需记忆负例单列，不拿其下降作期望。
- [ ] 根据开发集失败与学习曲线确定后续训练预算；预先记录实验假设和改善/回归判据。无收益仍完成实验报告，但不得宣称能力提升。

### P3：独立增量——管理决策与跨场景能力

- [ ] 实际上下文压力、offload与compact操作接入后再测；静态文件问答不算真实compact。
- [ ] 冻结压缩前后目标/约束/证据/未决事项检查，检验多次中断恢复；选择性检索与不必要写入成本分开。
- [ ] 新增调试任务（假设/实验/避免重复试错）与研究任务（来源/冲突/不确定性），建立独立环境与verifier，测试跨场景迁移。
- [ ] 各增量先设计与适用审批，再canary/学生基线/训练/独立评估。不提前将未实现机制列为通过。

P1通过不等待P2/P3；P2实验结束但无收益不等于效果目标达成。长期DSH调度/RSI目标仍保留，但不得阻塞当前记忆主线。异步、Harbor、SFT、新云服务与额外GPU不作为本轮前置。GPU停机按gpu-reconnect-runbook恢复，资产存/workspace及GitHub，不虚构持续后台运行。

## 当前执行目标：新版核心课程原生RL闭环（2026-09-10）

> 用固定版本的work-state-memory-core-v1（520训练/160公开开发实例）完成数据保存与校验、真实DSH canary、GPU在线采样、原奖励与完整组消费、训练更新、checkpoint、独立reload与新鲜评估；按阶段commit/push并保存可恢复handoff。第一优先工程跑通，不等待能力提升或全量数据消费；有效更新单独核实，不能由exit0推断。异步、Harbor、SFT、从零复建和专家级效果对照均不是本轮前置。

本节是最新执行优先级。下方旧E/W/N节点及旧课程通过状态保留为历史，不自动计入新课程。

- [x] G0 新生成器与680任务资产落盘：520/160不同可见输入，分阶段可见性、controller truth隔离和文件hash。
- [x] G1 统一回归、自review、Ruff双门、commit/push固定部署SHA。
- [x] G2 新GPU checkout、固定DSH/VERL与原venv核验、真实Linux canary；检查GPU占用后启动。
- [x] G3 新课程16步诊断运行：core-train-r4 exit0/6665.148秒；原511正式消费审计通过，16完整组/64链/128唯一A-B，16独立task（WS01/03/05/06=4/7/4/1），10拒绝组不消费。520是可用数，不是已消费数。
- [x] G4 同run审计完成：16步adv/grad全0；8→16的504adapter/399base变化0，最终252 LoRA B全0，optimizer内部step16→32但1008moments全0。有效更新门未通过，原passed=false保留，P1有效学习要求仍未完成；见core-r4-parameter-audit.md。
- [x] G5 checkpoint8/16保存，母step16四族首条公开dev独立reload及逐题母文件核验完成：WS01/03/05执行与消费审计通过但reward0；WS06预算耗尽，B未执行，正式消费审计false/0条。此节点记录真实结果，不代表四题成功或有效学习；见四份core-r4-reload结果及WS06消费原件。
- [x] G6 现有诊断运行证据归档、恢复指南/结果报告/goal/handoff及commit/push已完成；三份云盘证据tar另有本机SHA匹配备份，见gpu-shutdown-checkpoint-20260910.md。此项是现有失败/成功结果的可复核交付，不豁免P1有效更新失败，也不代表P2/P3完成。

退出标准分开报告：执行闭环、有效学习闭环、任务效果。首次诊断无有效更新时不篡改奖励、不盲目追加相同数据，按真实失败/奖励分布明确后续动作。GPU失联时保留已完成资产与新SSH恢复步骤，不标记未运行步骤通过。

用户已通过持续goal指令恢复P1→P2→P3推进；文件中的历史暂停状态不代表当前运行状态。

## 目标

长期目标仍是固定版本原生 DSH → Uni-Agent → VERL 在线 RL 工程体系，覆盖 DSH 调度、跨会话记忆、上下文管理与受控 RSI。当前收敛到一个可验收的工作包：用有实际恢复目标的记忆/context任务推动真实训练闭环。环境从零安装、Harbor及性能优化均后置。

### 当前可执行 goal（2026-09-09 用户确认）

> 按本文件与 dsh-memory-context-skills-plan.md，完成首批 WS01/WS03/WS05/WS06 文件工作状态任务的原生在线 RL 验收。固定 DSH、Uni-Agent、VERL、模型与任务/verifier版本；模型在 DSH 中维护交接、索引和事实状态，在新会话恢复后完成真实配置与计划任务。验证实际在线轨迹、奖励绑定、完整组唯一消费、有限非零任务梯度、参数与 optimizer 更新、checkpoint 保存，以及独立进程 reload 后的新鲜评估与结果复跑。交付可手动执行的脚本、指南、原始证据索引及分阶段 commit/push。任务质量与工程闭环分别验收，能力提升幅度另做对照实验；不得用历史其他任务的更新替代本课程证据。

### 两个目标与共同验收

**2026-09-09用户再次明确执行优先级：先工程链路，再训练信号，最后任务效果。** r3因内联周期评估的单条任务拒绝退出，后续训练关闭初始/周期评估并在保存后独立reload评估；不因合法全零奖励主动中止，也不为追求四族任务成功反复调提示阻塞保存/reload验收。分三层报告：①执行/采样/评分/实际消费/训练计算/checkpoint/独立reload完整；②至少一次真实任务优势→有限非零梯度→参数更新；③独立评估能力改善。①可以先通过，但不能冒称②或③；本工作包原W4有效更新条件保留，另行补齐，不把任务满分或奖励提高加入工程前置。安全违规、证据不可信与基础设施异常仍按原合同处理，禁止伪造reward差异。

| 目标 | 首阶段完成标准 | 不能据此宣称 |
| --- | --- | --- |
| 任务有价值 | 新会话必须利用模型实际保存的状态继续配置/计划工作；目标、真值与模型可见信息分离；正例可解、错误事实/失效索引/重复步骤等反例可判；WS06覆盖无需额外保存也能完成的场景 | 已学会自主选择compact时机、长周期记忆泛化或完整RSI |
| 链路完整 | 本课程真实 DSH 执行 → Gateway 在线 token/logprob/策略版本 → 原奖励 → 完整组消费 → 有效更新 → checkpoint → 独立 reload/fresh评估均有同一实验谱系证据 | 退出码0即有效训练、参数变化即能力提升 |

### 工程首阶段检查清单（W0—W6的执行层摘录）

本清单用于加快确认完整流程，不另设一套目标，也不替代下面W0—W6。当前r4已8/8步退出并通过最终消费/工件审计；独立四题隔离补验已全部收尾：3题真实消费通过，WS06 max-tokens未完成，原失败保留。工程执行层E1—E4完成，严格四题全部准入(all_verified)仍false，不等于工作包或有效学习完成。

- [x] E1 固定部署核验：DSH SDK/runtime 0.1.3a2与二进制hash匹配，集成源码、有效VERL基线及显式补丁、模型/任务/配置身份绑定已核验，复用现有环境。
- [x] E2 本课程既定8步执行完成：按n4完整组实际采样、评分和训练计算，审计完整组唯一消费，无未知/重复消费；合法零奖励不主动停止，安全与证据拒绝仍按原合同处理。
- [x] E3 Checkpoint完整保存：核step4/8工件完整性及源码、模型、任务/verifier、配置、实际策略版本与母实验谱系绑定；文件存在不等于有效学习。
- [x] E4 独立reload与fresh评估：新进程加载本课程母checkpoint，核加载身份与母checkpoint未改；覆盖固定评估任务，逐题如实记录成功、合法低分或拒绝/失败，保留原回执、实际消费与审计结果，不用启动或尝试评估冒称严格验收通过。 2026-09-09四题suite全部有终态（all_attempted=true）：WS01/03/05共3组6条唯一A/B真实消费，WS06 A因max-tokens拒绝并保留原回执、未计消费；每题母checkpoint复核及GPU清理通过，stop_reason=null。收尾完成不冒称4/4准入或业务成功。

**E1—E4只确认执行层。** 非零优势、有限非零任务梯度及有效参数/optimizer更新仍按原W4独立验收；工程首阶段通过不能将整个工作包标为完成，也不能宣称能力提升。

### 当前工作包节点（W0—W6）

- [x] W0 设计与独立review：任务目标、信息边界、奖励、A/B与训练身份及验收标准已落盘并获准实施。
- [x] W1 可执行任务合同：四族结构变体、原始多文件冻结、精确权限、独立verifier、合法低分样本、框架接线完成回归；Linux真实DSH canary已8种结构/106次工具请求通过。报告work-state-runtime-canary-r1-result.md；此节点不含学生推理或训练。
- [x] W2 数据与真实基线：发布固定摘要的训练/公开开发清单，分别统计结构族、独立实例、采样与实际消费；真实学生在同预算下逐族执行。全零/全满分时先诊断奖励可辨性，不伪造差异。固定四族已逐题记录结果；r4全部32条B独立重评分与原回执一致，配置正确0/32；控制器参考32/32可评分，见零奖励根因报告。
- [x] W3 本课程在线RL：同策略n4完整组、A/B及sibling隔离、真实token/logprob/version与原回执匹配；无未知/重复消费，拒绝组不进入更新，合法低分组不因低分被筛掉。r4最终8完整组/64唯一消费、6独立任务已核，无未知或重复；不代表全部8训练实例均消费。
- [ ] W4 有效更新与保存：至少存在可归因于本课程非零优势的有限非零梯度及实际参数更新，冻结base正确，optimizer推进，checkpoint完整保存并绑定版本/数据/配置摘要；报告零梯度步和实际覆盖。
- [x] W5 独立reload与结果复跑：新进程加载该母实验checkpoint，新session完成固定开发任务并产出可复核评分；核对加载身份、无意外更新/改写母checkpoint、消费与评分一致。逐族记录成功与失败，不要求训练后必然提分。四个独立新run已结束，母状态加载/不变、前三族fresh消费和第四族原始max-tokens失败记录均已证明。按用户“任务失败正常记录，不阻断工程收尾”的标准完成本节点；all_verified=false照实保留，不新增“四题必须全部准入/业务成功”的工程门槛。
- [x] W6 交付：可手动重跑的prepare/train/audit/reload命令、运行顺序与故障处理.md、证据清单/摘要、goal/handoff更新，Ruff双门与相关测试通过后commit/push。

**当前工作包完成 = W0—W6全部有证据。** 四能力终局、能力增益、封存泛化与性能目标继续保留，不能随本工作包一起自动勾选。C1的跨会话状态恢复不等于C2模型自主compact；后者须先验证固定runtime的真实动作接口。

## W4 后续短课程执行包（2026-09-09，用户已批准继续）

旧 WS01/03/05/06 的 r4 结论保持：执行闭环完成，有效更新未通过。为诊断并补齐真实学习信号，新增独立 `work-state-short-fact-v1` / WS07 课程与新母实验；不能用它追认旧 r4 已更新，也不能将单事实恢复等同于四类能力完成。设计见 [短课程设计](../../docs/harbor-modal-integration/work-state-short-course-design.md)。

- [x] S1 任务与因果读取合同：8 个独立训练实例、2 个公开开发实例；A 实际保存，B 新会话读取后完成配置；正反例、旧任务回归通过。核心111、recipe62、audit/canary37、credit7，共217项CPU通过；未据此宣称Linux或GPU通过。
- [x] S2 固定源码与课程身份：prepare/check/audit/reload 绑定 course、数据、runtime 与有效 VERL；Ruff 双门后 commit/push，GitHub 固定部署，真实 Linux DSH canary。b47521d已推送/固定部署，217项CPU与8例Linux canary通过，ws-short-train-r1训练及更新已验收，见S3/S4。
- [x] S3 新母实验真实 GPU 在线 RL：既定 8 步、每组 n4、无内联评估；核实际消费、奖励分布和有限非零优势/梯度。合法零奖励不停止或人为改分。ws-short-train-r1已8/8 exit0；最终8组64唯一消费、6独立任务，step2/4非零梯度均与原B奖励绑定。
- [x] S4 更新与保存：新课程 checkpoint/optimizer 与冻结 base 审计，给出实际参数变化；无变化则如实保留并定位，不以运行结束判完成。实测4→8共504个adapter变化、399base不变、全finite；fresh LoRA_B保存后非零与step2/4梯度联合支持新课程有效更新，后四步零梯度不称新学习。
- [x] S5 新课程独立 reload 与公开开发评估：加载新母 checkpoint，原始失败照实记录，验证新鲜轨迹、消费及母工件不变；不给旧 r4 换课程身份。901/902均exit0、原B1，各1组2唯一A/B；d4401d3离线审计均passed，母11文件after_run不变；旧901审计false保留，见work-state-short-reload-final-result.md。
- [x] S6 操作指南、证据归档、goal/handoff 与必要 HTML 视觉检查，分阶段commit/push。证据归档18,197,593字节、173,735源文件逐项回读通过；1440/390视觉检查通过，详work-state-short-r1-archive.md。

任务得分与工程验收分开；公开开发题不用于调提示、选择温度或挑 checkpoint。当前课程只有一个训练结构、一个开发结构，8 次采样不算 8 个新任务。

## N3最新语义（用户2026-09-09澄清）

记忆/context目标是适时保存goal/tasks/handoff/memory、维护索引、offload、获准compact及中断后继续工作；恢复结果、事实保真与总成本分别评估。完整[训练任务与设计](../../docs/harbor-modal-integration/dsh-memory-context-skills-plan.md)细化为C1文件工作状态→C2真实上下文操作→C3联合长任务，含WS01—WS12开发规格。当前规格不是已运行数据；不以固定A/B诊断或共有训练底座冒称完整MemAgent/ContextPilot集成。

## 节点

- [x] M1原生最小RL：真实更新、消费审计、独立reload与公开留出评估通过。
- [x] Harbor Docker资产/清理恢复验证保留；后续学生RL暂停。
- [ ] N0-R 结果复现：四类任务真实完成后，以独立新run重跑任务/评分/reload，记录确定性与采样波动。
- [ ] N0-E 环境复建：后续工程交付，非四能力前置；已有新venv保留。
- [ ] N1 四能力动作/数据/奖励合同与真实基线。
- [ ] N2 DSH调度独立任务能力实验。
- [ ] N3 记忆与上下文分别验收，再组合。
- [ ] N4 受控候选生成/验证/晋升/回滚及RSI学习。
- [ ] N5 四类封存评估与可复建模型发布。
- [ ] P1 能力任务可运行后单卡colocate_async有界对照；不阻塞N2，不新增GPU。

## 固定约束

Uni-Agent 89733ec81a69c3cc93ac90479de7ea7f01e51c1f；VERL fefb080262e1c015a0ea05f958822a6a512dc795；DSH b2369692ea530007075ebcd18d39fdba0bbd3982 / 0.1.3a2。每run另固定完整集成commit、模型、任务/verifier/Harness摘要与实际安装清单。保持DSH唯一Agent Loop。

2026-09-09协议修复：后续memory/work-state运行的有效VERL身份为上述官方基线加`preserve-finish-reason-v1`源码补丁（`deployment/versions/verl-runtime-patches.json`）；显式绑定patch与目标文件SHA，拒绝其他修改，复用原依赖环境。原始length不能再被合并为completed，截断/中止不得执行工具。旧裸fef实验保留原回执；新候选必须独立部署并重验，不能靠换版本文字追认通过。

SFT/数据生产由其他会话承担；本仓拥有在线RL消费与验收，不新增teacher调用、GPU或Modal。任务必须有步数/token/wall-clock预算。checkpoint继续/workspace/uni-agent-g1/checkpoint/<run>；私有凭据/root/runs。每通过一环节commit/push前Ruff双检查和相应测试。

## 现状与下一步

M1 v2-r4及reload报告为当前通过证据，公开两题baseline已满分不证明提分。Harbor r1失败已停止，cleanup修复04c26ee已推送，Docker恢复负例通过但不代表学生RL通过。已准备的Harbor r2不得继续启动，私有临时spec会到期。
下一步按W1→W6完成首批真实工作状态任务的原生RL验收，再推进C2/C3及其他四能力实验；N0-R结果复跑贯穿其中。原生训练使用已验收venv，不等待N0-E新环境安装。

## 平台goal状态

2026-09-09本次 get_goal 仍返回引用本文件的原生四能力 objective，平台 status=usageLimited。本文已按用户最新确认细化当前工作包；平台objective文本未被改写，目标尚未完成。现有工具只支持创建新goal或将既有goal标记complete/blocked，不支持修改未完成goal的objective或恢复状态；不假报已激活，不为替换文本而假报旧目标完成。当前可继续执行已授权工作，执行范围以本文为准。

## 2026-09-09 较早实测增量（历史，现状见下）

- DSH runtime-grounding：8k失败；24k容量对照完整执行/轨迹回读，但reward0，模型仍未正确查询Tool。
- 文件证据context r2：4/4严格执行通过，奖励全0，真实引用/读取覆盖不满足合同。仅文件证据基线，非真实context切换或RL训练。
- Linux记忆封闭策略：14真实工具调用正反例通过；学生A/B链CPU接线完成；writer r1失败，反馈修复后r2真实验证中，credit尚未实现。
- RSI候选持久化：27新增测试通过，晋升/回滚及新进程选择已验证；固定Linux runtime实际加载/回滚18工具调用已通过；学生候选效果与训练未验收。
- T2日志工具：一个公开开发题4次采样已结束，未观察到成功，严格评估exit1；不是4任务/GRPO训练组。接下来优先真实记忆链与分级RL课程，不重复全零原配置。

上述报告位于docs/harbor-modal-integration/native-*-result.json与native-memory-policy-linux-canary-r1.json。N1—N5均未因此标完成。

## 当前数据与训练准入

- 任务量、独立场景数与采样次数分别记账；重复行或n次rollout不增加独立任务数。没有可直接套用的“行业统一最小数量”。
- context v2现有12 train/4公开dev，仅工程课程；两步更新不等于消费全部12题。必须报告实际消费任务、有效组、奖励分布与更新。
- 2026-09-09 v2探索r2：4 dev×4独立采样，340.01秒exit1。统一失败源于verifier错误拒绝合法view_range，修复前不据此否定学生能力或直接扩大运行。旧回执保留。
- memory旧writer r2已确认一次越权而拒绝，保留失败，不追认；后续prompt revision2的两族完整A/B已通过，见当前快照。
- 后续扩大数据优先增加能力规则/难度/任务模板覆盖；封存测试不用于调提示或挑样本。工程跑通与能力增益分别验收。

## 当前验收快照（不修改N0—N5/P1退出条件）

- context-v2-train-r1：两步真实RL，实际消费2题/8尝试；仅首步有非零任务梯度。14组消费审计、252 LoRA变化/399 base冻结及optimizer审计通过；独立reload四组通过，严格准确率0。
- constraints-r3与updates-r1：两族真实A写入→冻结→新B读取均reward1，身份/回执/事实及云盘归档通过；training=false，尚非memory RL或能力提升。
- context-v2-curriculum-r1：12有效batch、48消费、11唯一题，6步非零梯度；step6→12全部504 LoRA变化、399 base冻结，optimizer6→12和1008 moments审计通过。严格原audit=false保留，D3被拒且未消费、D2补采。独立step12 reload已470.012秒exit0、4/4 fresh评估消费通过，无再训练；dev strict0/4，工程结果不宣称能力提升。
- RSI配对worker准备器/监督入口已7c37cb2推送，仍未真实学生H0/H1比较或晋升。memory实际策略版本完整性2f1995a仅CPU通过，未部署当前GPU。
- memory resident verifier、Gateway单stage、可信A/B/整链TQ及消费审计已实现并CPU回归通过。r1真实运行因误拒VERL默认reward handles构造失败，零A/B、零消费，已保留并停止；修复c5dacdc已push，r2新run已385.009秒exit0，真实A/B reward1、1完整val链/2键实际消费且版本完整，专用审计passed=true；无更新。train-r2已在initial val因A写错事实被拒，exit1，尚无B/n4/消费/更新/CK，GPU释放；报告memory-resident-train-r2-result.md。旧eval回执不能改split冒充train。继续保留DSH唯一Agent Loop与固定resident backend。

当前即时进程与后续命令以handoff.md为准；上述新增证据不等于四能力训练和封存泛化验收完成。

## RSI 真实父基线增量（2026-09-09）

`rsi-student-h0-r1` / b1c568b：H0两类开发任务真实GPU执行、2条唯一TQ读回及raw-token/receipt/trace重审通过，均finished/eligible=true、reward0。inspection被父策略拒绝；文件题读取成功但value格式错误。exit0、314.622秒，GPU已释放。207项CPU回归并固定VERL overlay适配完成；下一步真实学生P，不追认N4或RSI RL完成。证据rsi-student-h0-r1-result.md/json。

RSI P r1：真实学生生成声明式候选（增加inspect_list），42模型token、1条唯一消费及raw审计通过，格式reward1、exit0；尚未注册/晋升/训练，不代表开发收益。下一节点H1配对评估。

RSI H1 r1：同模型/任务/预算真实执行，2条独立原始审计通过、exit0（266.021秒）；inspect0→1，file0→0，无观测回归。未晋升/回滚，组合比较入口正在补齐，不标记N4完成。

## 最新能力目标澄清

优先工程续作场景中的专家级记忆/context管理：选择、保存、检索、冲突更新、卸载/压缩及克制停止；参考expert-memory-context-training-plan.md。从已有r4真实事实矩阵定位瓶颈，再定向课程训练，不把配置小题或文件数量当终局。异步实施暂停。当前只读诊断不占GPU，不标记训练增益完成。

## 2026-09-10 已批准 reader 诊断执行节点

用户明确批准后已实施同一真实A产物的原/新reader提示包比较。执行入口 `examples/dsh/capabilities/diagnose_core_reader.py`，操作指南 `docs/harbor-modal-integration/core-reader-role-diagnostic-runbook.md`。该节点不改变P1/P2/P3目标，不提交TQ、不声称参数学习。当前完成CPU工程包；新GPU未接入，本诊断真实执行仍待验收。
