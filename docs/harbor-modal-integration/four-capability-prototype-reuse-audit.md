# 四类能力、十二种原型的实现复用审计

2026-09-09，只读检查当前工作树源码；仅新增此文档，未生成数据、未修改代码、未运行模型或训练。每类 3 结构、24 train / 6 dev / 6 sealed 是已批准的**预算**：合计 96/24/24、144 条计划实例，当前不能声明已生成或冻结。

首批目标是每类 3 个可执行原型和基线诊断。下面给出可对应总体设计的具体原型；“已有执行路径”不等于“新原型已通过真实 canary/学生基线”。旧数据、重复采样和已公开测试不能直接改标签充当新封存集。

## 共同底座与禁止重复实现的边界

- 所有模型动作继续走 `uni_agent/agents/dsh/runner.py` 与现有 `dsh_architecture` Task/Gateway；DSH 是唯一工具执行 loop。不要为四类分别做新 Agent Loop、模型客户端或 token 采集器。
- 文件跨会话复用 `work_state/stage.py`、`bundle.py`、`profile.py`、`policy.mjs`、`verifier.py`、`scoring.py` 与 `uni_agent/framework/work_state.py`。A 真实写→原始字节冻结→新 B 真实读，controller 不替学生补记忆。
- 文件证据评分复用 `context_tasks_v2.py:documents/oracle`、`context_verifier_v2.py:score` 的 source digest、路径/工具配对、真实引用与缺值合同；不要把它升级命名成已实现 context 切换。
- RSI 复用 `rsi_closed` 的 H0/P/登记/H1/比较和 `uni_agent/tasks/dsh/rsi_candidates.py:Registry`。Registry 负责可信晋升/回滚，模型生成候选；不要让模型直接写 active 指针或奖励回执。
- 新版本数据编译器应把冻结任务清单接到现有 runner/prepare，不从旧准备器复制一套训练栈。split、结构和身份的新增支持需版本化，不能去掉旧 schema 保护。

## A. DSH 操作与调度：三个原型

### DSH-1：从实际 inventory 发现并查询工具

**任务**：先读实时 provider inventory，再查询实际可见 Tool provider；存在和被拒绝分别有证据，不猜 API。

**源码证据**：`examples/dsh/prepare_capability_eval.py:prepare` 已选择 runtime-grounding 并编译原 runner 的评估配置；`examples/dsh/evolution_v3_live_scenarios.jsonl` 的 runtime-grounding 规定 4 tool calls/6 turns；`evolution_v3_live.py:build_live_task_rows` 负责身份绑定；`evolution_v3_live_verifier.py:_runtime_grounded/_runtime_grounding_observation` 核真实 listed provider/query。

**可执行状态**：已有单题准备器和真实执行接线；旧 verifier 明示主要检查真实查询动作，不等价于完整最终答案正确性。仅有一个旧 runtime-grounding 实例，不能算 24 train。

**最短下一步**：冻结一份新开发原型和实际 inventory oracle，复用原入口做 canary/学生基线，记录查询成功与正确结论分别得分。若需要最终答案测试，新增版本化分项而非覆写旧 rubric。

### DSH-2：定义、调用、更新并清理工具

**任务**：session 内定义一个受限工具，处理两组不同业务输入，更新后再运行，最终 undefine 并证明 inventory 清空。

**源码证据**：`evolution_v3_live_scenarios.jsonl` 的 lifecycle-composition；`evolution_v3_live_verifier.py:_lifecycle_observation/_terminal_plugin_count`；更有业务结果的现成路线是 `examples/dsh/capability_tasks/log_tool/task_bundle.py:build_rows`、`oracle.py`、`verifier.py` 和 `prepare_training.py`，已覆盖日志过滤/脱敏、两次调用、工具清理。

**可执行状态**：T2 log_tool 有 train-01…04/dev-01…02 的已有公开 fixture 和训练准备器。lifecycle 通用路径也存在，但全套 live bundle 仍写 `status=blocked/LIVE_FAMILY_SMOKE_PENDING`，不能把生成 bundle 视为新在线准入。

**最短下一步**：优先选择 T2 的一个业务型 fixture 做新原型基线，复用独立 oracle/verifier；覆盖结果与生命周期，避免再写 normalize 工具专用 runner。工具代码只在现有获准 session 环境执行。

### DSH-3：依赖错误诊断与同插件恢复

**任务**：观察故意缺失服务导致的 waiting 状态，在同 Plugin 上追加正确 package、update、执行 recovery_probe、清理。正常、修复失败和重复副作用分别可判。

**源码证据**：`evolution_v3_live_scenarios.jsonl` 的 diagnostic-recovery；`evolution_v3_live.py:_render_prompt` 生成现有 API 合同；`evolution_v3_live_verifier.py:_waiting_for/_defined_plugin_ids/_diagnostic_recovery_observation` 已核等待/修复/调用事实。

**可执行状态**：合同和 trace projector 已有；当前 `prepare_capability_eval.py` 只选择 runtime-grounding，不能直接用其 CLI 选择本族。`evolution_v3_live.py:load_live_scenarios` 又限定旧 rows 的 split=test，不能直接改成 train。

**最短下一步**：给现有 eval 编译路径加显式、版本化的 scenario 选择，先 Linux canary 核 oracle 修复可行、反例拒绝，再学生基线。后续 train/dev/sealed 发布用新数据合同，不删除旧 test-only 守卫。无需新错误恢复 loop。

## B. 文件记忆：三个原型

### MEM-1：交接后继续依赖计划，不重复已完成动作

**任务**：A 读取工作流并写必要 handoff；B 新会话恢复配置和剩余计划，保留 completed。线性和分叉汇合是不同依赖结构。

**源码证据**：`work_state/tasks.py:make_task` 的 WS01（约77行起，linear-migration/parallel-join-migration）；`stage.py:prepare_writer_stage/freeze_and_prepare_reader`；`scoring.py:score_task` 校验配置、依赖顺序、重复动作与完整计划；`prepare_memory_training.py` 已接原四族。

**可执行状态**：原 WS01 可实际运行；它验证配置与计划工件，不是真实外部迁移执行，不能把 `plan_execution` 字段名解释成已执行数据库副作用。r4 原四族零更新不变。

**最短下一步**：复用 WS01 生成一个新冻结实例及错误依赖/重复动作反例，明确验收对象是工件计划；先比较 A 写入质量与 B 恢复失败点。真正执行副作用属于后续 runner 权限/任务扩展。

### MEM-2：索引定位多文件证据再完成配置

**任务**：B 只得入口，利用 A 保存的索引找到数据库/缓存等不同来源，选择兼容配置。

**源码证据**：`work_state/tasks.py:make_task` WS03（约109行起）；`bundle.py` 冻结真实多文件；`profile.py/policy.mjs` 精确读写边界；`scoring.py:_configuration` 的 WS03 专有业务约束。

**可执行状态**：已有任务与真实 A/B/评分。固定准备器仅内置有限 seed/variant，不是任意数据清单入口。目录映射变化或新索引图需生成新 task identity，不能手改输出 manifest 绕过校验。

**最短下一步**：基于已有 WS03 的一个结构编译原型；增加失效入口/错误来源的 verifier 反例验证。读索引→读目标→写配置必须来自模型真实轨迹，controller 不透传目标路径消解检索任务。

### MEM-3：新约束取代旧事实并恢复工作

**任务**：A 保存旧工作结论，B 获得新通知/可信更新后修正配置，不能盲信最新时间或旧 handoff。

**源码证据**：`work_state/tasks.py:make_task` WS05（约153行起）；同一 `stage.py` A/B 与 `scoring.py`；事实来源判断可参考 `context_tasks_v2.py:oracle` 的 project/component/state/version 规则，但不把静态问答 runner 套在 A/B 外。

**可执行状态**：WS05 已实现并真实执行过；动态任意更新链仍非现成生成器。WS06 “无需保存”已有实现，适合作为三族共同负例/回归，不应因为只保留三个主结构就删除。

**最短下一步**：选现有 WS05 做新冻结原型，分别记关键事实、恢复和业务分；保留 WS06 无需保存对照。短课程→四族显式初始化设计仍是单独待实现项，不阻断原 base 基线或 CPU 原型构建。

## C. Context 管理：三个原型

### CTX-1：外置大证据、按索引取回并继续任务

**任务**：大日志原件留在获准文件，模型保存足够定位的摘要/索引，后续请求不携带全原件，仍能取回关键引用并完成任务。

**可复用源码**：`context_tasks_v2.py:documents/oracle/specifications` 的 index 证据图；`context_verifier_v2.py:score` 的真实 view/引用核验；`work_state/bundle.py` 的真实工件冻结和 `stage.py` 的恢复链。当前 context v2 在 `score` 返回中明确 `capability_scope=file-evidence-only`、`context_switch_verified=False`。

**真正缺口/状态**：目前静态文件证据题不是“模型自主 offload”。缺大输出→持久原件→模型可见引用的真实动作回执，以及下一 request 的上下文大小/证据可达性观测。若用 A→B 断开长上下文，只能称跨会话外置恢复，不能称同会话 offload 已通过。

**最短下一步**：先用原文件证据 canary 验可达性；在 DSH 固定 runtime 内审计实际 spill/ref 设施是否暴露为获准动作，捕获前后 request。仅补 task/stage 观测与必要 DSH 适配，不新增 Python context loop。没有实际收缩证据时该原型只报告准备/诊断通过。

### CTX-2：真实 compact 后保留关键约束

**任务**：工作推进导致预算压力，执行真正 compact；下一模型请求必须改变，保留目标、约束、未决和来源，恢复后完成同一任务。

**可复用源码**：`context_verifier.py`、`context_verifier_v2.py` 提供引用/事实判定；原 `DshArchitectureTask` 和 runner 继续执行。完整方案 `dsh-memory-context-skills-plan.md` 已列 DSH command-compact/compaction-basic 来源及人工命令 idle 限制。

**真正缺口/状态**：`examples/dsh/capabilities` 没有模型可调用 compact executor，也没有 before/after request 身份、摘要与关键证据保真验收。写 summary.md、减少输入 max_tokens、模型自报 context ID 均不能替代。固定 DSH 是否需要最小受控适配必须实查，不能因为 Python 层有 context 命名就宣称可运行。

**最短下一步**：第一项是固定 runtime 接口 canary；先做控制端获准、清楚标注 forced-compaction 的因果试验，再实现模型选择动作。若 runtime 没有入口，标明需要 DSH 侧受控动作合同和新 pin，不在 Uni-Agent 另造 loop，也不拿文件证据题充当本原型完成。

### CTX-3：缺失/失效索引后的证据恢复或可信弃答

**任务**：索引失效、目标事实缺失或新旧来源冲突；模型识别证据不足，检索获准替代来源或明确不足，不能用旧值补答案。

**可复用源码**：`context_tasks_v2.py:specifications` 的 train-M1/M2/M3 与 dev-M、index/select 规则；`oracle` 的 no-authority/missing-value→insufficient_evidence；`context_verifier_v2.py:score`；`prepare_context_training_v2.py` 与 `launch_context_inference.py` 已接现有 runner/训练。

**可执行状态**：静态缺值/权威缺失可直接诊断；目前 oracle 对索引指到 allowlist 外直接报错，不能把真实失效路径修复称为已有任务。索引重建、部分写入修复与下一请求变化还缺版本化任务/动作证据。

**最短下一步**：先使用现有 missing 结构完成一个诚实标为 file-evidence-only 的子基线，再扩“允许修复入口+可信替代源”合同及负例。CTX-1/2 的请求收缩验收复用同一观测层；CTX-3 不另写会话调度器。

## D. 受控 RSI：三个原型

### RSI-1：缺能力诊断→合法最小扩权→业务复验

**任务**：父策略缺 inspection 权限；P 读取白名单诊断生成合法 allowed_tools；登记后隔离 H1 重跑，与真实 H0 组合比较。

**源码证据**：`rsi_closed/worker_tasks.py:prepare` 的 inspect-discovery/file-constraint；`worker_verifier.py`；`proposal.py:messages/score`；`proposal_registration.py:prepare_proposal/register_verified_proposal`；`prepare_worker_eval.py`、`launch_worker_eval.py`；`compare_workers.py:compare`；`rsi_candidates.py:Registry.promote`。

**可执行状态**：这条已有真实 H0/P/H1 分阶段结果和源码入口，后续比较/晋升状态以新原始报告为准。两个 worker 是一个候选的业务比较维度，不是两个独立 RSI 训练结构。尚无 RSI 延迟业务收益→P token 的在线训练接线证据。

**最短下一步**：把既有实验作为原型1，完整复用登记/比较链，冻结另一权限缺口实例时同步生成新的 pins/case manifest。不得扩大 renderer 不支持的工具集合。

### RSI-2：无收益候选不晋升，允许保持父策略

**任务**：诊断是输出格式/业务理解错误，权限变化并不能帮助；合法保持原策略，或对合法但无收益候选保留父 active。

**源码证据**：现有 file-constraint 真失败适合诊断；`proposal.py:parse_response` 返回 changed，`score` 当前奖励为 eligible 且 changed；`rsi_candidates.py:_comparison` 拒绝 sum(gains)<=0；Registry CAS 和不可变 archive 可复用。

**真正缺口/状态**：保留父 active 的控制门已存在；但**当前 P 奖励鼓励 changed，合法不变输出为0，登记又要求原 P reward1**。因此不能直接用原 P 合同训练“知道何时不改”。缺 no-change/no-op 作为合法终局的版本化声明/学习合同及新的无收益业务实例。

**最短下一步**：先运行无收益候选的控制器原型证明拒绝晋升、active 不变；再发布新版 no-change 决策合同，业务收益和 P 格式分分开，不改旧42-token提议的reward或回执。不能为制造差异奖励无意义工具增删。

### RSI-3：局部增益伴随回归→拒绝候选，已晋升状态可回滚

**任务**：候选修好一项却破坏另一必要能力；组合测试拒绝平均分掩盖回归。独立控制演练覆盖合法晋升后的回滚恢复和新进程实际选择。

**源码证据**：`rsi_candidates.py:_comparison` 对任一 gain<0 即拒绝；`Registry.rollback` 以 expected active CAS 恢复 parent；`rsi_closed/profile.py:build_patch/build_evaluation_patch` 分离 active 与候选；`probe.mjs` 和 policy 测试可检查真实加载。

**可执行状态**：控制机制可复用，学生生成回归候选/真实检测回归的数据结构尚缺。当前 worker fixture 固定 max_attempts=3，`prepare_worker_eval.py:frozen_cases` 硬要求恰好两题和指定 ID；不能在目录塞新题后声称准备器支持任意三族。RSI 的候选空间仅两个工具的 allowed_tools，不能伪称任意代码自改进。

**最短下一步**：基于允许工具子集冻结一个“新增inspection但删除必要file权限”的隔离候选，真实配对核回归并拒绝晋升；单独在测试 Registry 演练已有 rollback，不强行晋升已知回归候选。后续扩 worker schema/manifest 时保留旧两题兼容与严格完整集合校验。

## 数据预算落地的共同缺口

1. **任意清单入口尚不统一**：work-state 内置四族 variant/seed schedule；context-v2 固定12 train/4 dev；RSI 固定两dev worker；v3 live 固定 test-only；T2 固定公开 train/dev。需要薄的版本化清单编译入口，把新结构映射到这些现有执行器，不能粗暴拼接后改 split。
2. **结构覆盖不是换名字**：每类3种结构的成功、合法失败、边界反例先各有 oracle/canary；正式每结构预算8train/2dev/2sealed，生成前按依赖图/来源布局/权限故障类别拆分，不能同图只换seed就叫独立泛化。
3. **封存隔离**：旧 live test 已公开并读过，旧 dev 用于诊断；都不能重命名 sealed。新 sealed 在生成/冻结阶段绑定摘要，模型开发和候选选择不读答案，消费权限由明确评估阶段开放。
4. **原型排序**：DSH 与 memory 主要复用现有文件/任务；RSI 先复用一条真链并补no-op/回归结构；context 先核真实接口与request观测。不要等所有144条生成才跑第一个可解性canary，也不要跳过真实compact缺口来凑齐12个“完成”勾选。
5. **统计分账**：分别记录计划行、已生成行、独立结构/实例、真实尝试、完整组消费、有效梯度和结果。12原型通过仍不等于144实例已经生成，更不等于四类能力提升。

## 最小交付建议

先交付每原型一份 source-bound fixture、oracle正例、可信低分和安全拒绝反例、一个原runner命令及结果manifest。复用已有哈希/回执/完整组审计。真正需要新实现的是版本化数据清单入口、CTX请求/动作证据、RSI no-change终局合同与扩worker集合；不需要新Agent Loop、新trainer或新通用工作流平台。
