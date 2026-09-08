# 独立会话委托：DSH能力课程与评估数据 v1

> 分工更新：用户已安排另一会话负责数据生成。优先复用DSH-Exp/feat-sft-campaign现有generator，由Uni-Agent提供任务与验收契约。本文件原建议新建Uni-Agent数据worktree不再作为默认执行路径；不要重复搭建生成器。最新操作指南：../../docs/harbor-modal-integration/data-expansion-runbook.md。

## 目标与职责

为4B模型下一阶段能力实验准备**可执行、可评分、可复现**的数据任务，回答“模型是否更懂DSH调度、恢复与记忆使用”。当前邮箱脱敏4train/2public holdout只做工程验收，不够证明能力提升。

本委托是独立数据工作包，不改变当前G1，不启动GPU训练、不购买资源、不调用付费teacher。训练集成主仓为xDAN-DSH-uni-agent；DSH-Exp只承担DSH本体和历史研究。不要同时在两个仓库实现同一训练集成。

## 开始顺序与分支

1. 先读本仓AGENTS.md、tasks/harbor-modal-integration/handoff.md、active-engineering-goal.md、acceptance-tracker.md和tasks/lessons.md。
2. 参考基线为本仓commit `64af156`（完整SHA由git rev-parse确认），其已包含Harbor v2薄adapter；当前GPU仍固定2df91d7，不改GPU。若接手时需要更新基线，先比较差异并记录精确SHA，不能盲目从main开始。
3. 建议独立worktree名`dsh-capability-curriculum`。沿用用户此前允许的git worktree add，但先检查目标是否已存在，禁止覆盖或reset其他会话。
4. 文档放docs/dsh-capability-curriculum/，交接放tasks/dsh-capability-curriculum/。本任务先输出设计、任务示例、契约与CPU验收方案；按Human Gate呈现设计并取得明确实现批准后再写生成器/verifier代码。委托本身不替代尚未呈现的设计批准。

## 阅读入口

- docs/harbor-modal-integration/4b-harness-capability-plan.md
- docs/harbor-modal-integration/dsh-capability-training-strategy.md
- docs/harbor-modal-integration/training-task-matrix.md、experiment-matrix.html、capability-milestones.html
- deployment/versions/g1-deployment-lock.json
- examples/dsh/evolution_scenarios_v2.jsonl、prepare_redact_curriculum_v2.py、evolution_verifier_v2.py
- examples/harbor/prepare_evolution_task.py、uni_agent/tasks/harbor_dsh/evolution_scoring_v2.py（仅参考接口，当前Harbor v2全链路仍待完成）
- /Users/gumpm5/Documents/Code/xDAN-DSH-Exp/docs/architecture-entry/index.html
- /Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/feat-contextpilot-capability-sft/docs/feat-contextpilot-capability-sft/design.html
- /Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/dsh-official-training/docs/dsh-official-training/Harness自进化与DSH训练-翁荔博客论文研读.html

外部本地参考只读；路径缺失记录，不臆测已集成能力。固定DSH0.1.3a2，runtime/source/SDK以锁文件为准，不自行升级。

## D0：先交付24个任务设计样本

四类各6例，覆盖至少3种结构不同的变体。样本数量是设计审查额度，不是已生成数据。

| 类别 | 实际任务例子 | 必须验证的结果 |
| --- | --- | --- |
| A 工具选择与调用 | 多个可用工具中选择合适能力，处理带噪日志生成结构化报告 | 输出符合fixture真值，真实调用正确工具；不靠回答声称已执行 |
| B 生命周期与恢复 | 动态注册工具、处理可恢复报错、引用真实返回ID、清理临时能力 | 调用证据、恢复后结果、必要清理；允许不同合法路径，不硬编码完整动作序列 |
| C 上下文事实保真 | 长日志含时间/版本冲突，维护事实与来源，回答后续问题 | 事实与来源正确、旧值更新、关键约束保留；压缩token数量不作为成功指标 |
| D 跨会话记忆 | A写入用户约束或环境事实，B全新会话检索后完成任务 | A/B身份不同、只通过允许的持久记忆连接，B输入不泄露答案，有污染/旧记忆负例 |

每个例子标记runtime支持：可立即执行 / 需要现有插件配置 / 缺接口待集成。C/D如果当前runtime/profile不支持，交付契约与fixture，明确blocked-by-interface；禁止模拟成功或在DSH外补第二套Agent Loop。

另给RSI小规模设计附录：候选harness提出→冻结候选版本→隔离验证→与固定基线比较→晋升/拒绝/回滚。不能把单次define工具称为RSI；不允许候选修改评分器或测试答案。此附录不阻塞A/B数据首批。

## D1：通过设计后的数据实现范围

先做A/B中已支持的场景，每类12train/4dev/4test，共40个独立实例；不是把同一题换字符串算不同能力。该规模仅用于课程pilot，不承诺足以训练。C/D单独里程碑，接口通过后再扩。

pilot基线暴露有意义的失败后，再提议扩至100—300train、30—50dev、50—100test；必须报告模板数、场景数和难度分布，不能只报行数。不要为达到数量门槛生成低质量变体。

## 正交标签与数据契约（先与主会话确认，不宣称已有API）

每条至少定义：task_id、task_version、family、template_id、split、difficulty、instruction、fixture_ref及sha256、expected_outcome_ref、required_capabilities、runtime/profile/patch身份、verifier身份、seed、source/provenance、token/turn/time预算。记忆任务另外定义episode_id、session_A/session_B、memory_namespace及隔离规则；RSI另有candidate_id、parent_id和evaluation_id。

标签分开：学习方式SFT/RL/OPD；任务场景；harness配置；执行后端local/Docker/Harbor；数据来源teacher/student；参数更新LoRA/full。Harbor是环境/评估基础设施，不是第三种学习算法。

- RL任务包：instruction+环境fixture+独立verifier，学生在线生成轨迹；静态示例JSON不是on-policy rollout。
- SFT：只有真实合法执行并独立验证的示范才成为训练候选，保留工具schema、动作/观测和来源。手写示例标记design-only，不冒充教师轨迹。
- OPD：仅预留student轨迹与teacher信号接口；本任务不启动付费teacher、不伪造logprobs。

## 划分与验收

- train/dev/test按模板或场景结构分组划分，不只随机按行切。按规范化内容去重，报告跨split相似性与答案泄漏检查。
- test在设计冻结后单独保管；未真正做到访问隔离时只能称公开留出，不能称封存测试。训练和调参不消费test。
- 每类verifier测试包含成功、可信正常失败、错误答案、缺必需动作、伪造trace、旧receipt重放、超时/未完成。业务0分与基础设施错误分别记录。
- 同seed两次生成字节一致，manifest绑定全部文件sha256、源码revision和生成命令。
- 至少每个实际支持模板执行一次真实DSH CPU脚本策略oracle、一次负例，证明fixture/verifier可运行；无模型执行只能证明环境与评分，不证明学生能力。
- 保留分项reward，别让“未完成任务”与“证据不可信”混淆，导致只留下成功组。新verifier单独版本，不修改当前v1/v2源码/hash。
- 暂不运行学生GPU基线：交付精确命令和预算，由主会话排期使用GPU。

## 交付清单

- [ ] design.html或design.md：目标、架构、文件清单、契约、测试、依赖缺口。
- [ ] 24个设计样本与场景矩阵，清楚标注可执行状态。
- [ ] 设计获批后：独立版本生成器、fixtures、manifest、verifier与CPU测试。
- [ ] split与泄漏审计报告、真实oracle正反例结果。
- [ ] README：生成→检查→oracle→准备训练输入的命令；不自动调用GPU。
- [ ] handoff.md：固定分支/commit、交付路径、已验收范围、待主链集成项。
- [ ] ruff check .、ruff format --check .及相关测试通过后commit/push，供主会话review；不merge主分支。

## 不可改动

禁止修改当前G1 active goal、当前训练数据/固定verifier、部署锁、GPUcheckout与进程；不得将新数据接入正在运行的实验。主会话接收版本化数据契约和测试报告后另建实验，明确区分课程pilot、工程验收和能力提升。
