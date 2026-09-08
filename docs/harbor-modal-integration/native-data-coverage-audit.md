# 原生四能力：数据与训练覆盖审计

审计日期：2026-09-09；源码快照 `d13bda976507aed8ee4722be38a36a332f8c898c`。
只读本仓代码和已归档报告，没有启动GPU、生成新数据或修改训练代码。
状态只覆盖此快照已归档证据；之后的运行结果应另追加，不能用准备器存在推断训练完成。

## 1. 计数口径

- **独立任务实例**：固定业务输入、环境/证据图和验收合同；相同题目新UID、新目录、新随机种子、
  不同回答或重复rollout都不增加任务实例数。输入变化也不自动等于新增结构模板或任务族。
- **采样尝试**：模型对实例的一次实际执行。12题×n=4若完整采样，是12题/48尝试，不是48题。
- **训练消费**：确实被准入、送入本次优化器的题目与token；数据集有12题不表示一次两步试训覆盖12题。
- **开发集**：用于选提示、预算、奖励设计或候选。公开dev和反复使用的holdout不能再称封存测试。
- **封存集**：未被训练/调参/RSI选候选消费，内容与评分由独立控制端隔离保管。
  本次没有发现已完成此类隔离交付的能力测试集，因此已验收封存实例数记为**0**。

## 2. 四能力现有覆盖

| 能力 | 当前可用实例与划分 | 结构覆盖与限制 | RL接线/实际训练状态 |
|---|---|---|---|
| DSH调度 | M1邮箱4 train / 2公开holdout；全量旧v2源资产16 train / 8公开holdout包含这4/2；T2日志工具4 train / 2公开dev；v3诊断8族各1条test | M1仅邮箱任务，已满分；旧24条覆盖trim/normalize/redact/mask四种操作；T2六份输入仍共用一个日志处理+生命周期任务模板 | M1已完成真实在线RL更新、参数/optimizer审计与reload；T2有原生准备/评分/训练入口，但可见新轮仅探索评估；其他资产不能当已完成训练 |
| 上下文/文件证据 | v1四题，2族×有值/缺证据，全为公开test；v2 **12 train / 4 dev**，四族每族3 train / 1 dev，dev写为validation | v2定向、冲突、缺证据、数值版本；direct/index/select共三种规则模式和不同组合图；仍是固定小型文件证据课程 | v1已真实推理，r2四题strict准入成功但业务reward全0；v2准备器→strict推理→原生online RL脚本已CPU接线，尚无本v2真实GPU更新归档证据 |
| 跨会话记忆 | constraints、updates两个固定诊断实例/模板；每实例分writer A和reader B，两阶段metadata均test | 换chain_id只增加执行身份，不增加任务。A/B两个session也不能算两个独立记忆问题 | 单阶段DSH任务和整链评估编排已实现；writer r1真实失败，未freeze、未生成reader；没有完整链RL消费/信用分配或新参数更新证据 |
| 受控RSI | 父/子/回滚的固定工具策略canary；2个synthetic比较case ID，仅测试选择合同 | 18次真实SDK工具请求＝3阶段×6调用；不是18个学生任务，synthetic case不计真实学习实例 | 候选冻结/晋升指针/新进程读取/回滚和真实Linux策略生效已通过；没有真实学生独立开发评估及RSI在线RL更新 |

没有把M1子集与旧24条相加，也没有把T2一次题目四次尝试相加成四个新任务。

### 具体资产与证据

DSH：

- [旧24行源资产](../../examples/dsh/evolution_scenarios_v2.jsonl)：16 train / 8 holdout。
- [M1 v2准备器](../../examples/dsh/prepare_redact_curriculum_v2.py)：明确要求redact4/2，
  固定新准入身份。其余18行没有被这个准备器自动发布为当前M1 v2训练课程。
- [M1 r4审计](redact-m1-v2-r4-audit-bundle.json)：exit0；504个adapter张量变化，399个base张量不变；
  optimizer step从2到4，moments有限且非零。
- [独立reload](redact-m1-v2-r4-reload-result.json)与[前后比较](redact-m1-v2-r4-eval-comparison.json)：
  两个公开holdout训练前后均1分，所以它证明工程闭环，不证明能力提升。
- [T2准备器](../../examples/dsh/capability_tasks/log_tool/prepare_training.py)、
  [任务合同](../../examples/dsh/capability_tasks/log_tool/task_bundle.py)：4 train / 2 validation，后者来源public dev。
  准备环境默认VAL_ONLY=True，不会因文件名prepare_training而自动训练。
- [T2最新探索](native-t2-exploration-r1-result.json)：independent_task_count=1、attempt_count=4、
  training=false、accepted_e2e=false；两个尝试max-tokens，其余完成但0分。不是四个任务或一次GRPO更新。
- 历史T2还有真实SFT checkpoint审计：[step1](t2-sft-step1-checkpoint-audit.json)、
  [step1→56](t2-sft-warm-checkpoint-audit.json)。这些记录不能否认，但**不属于本轮在线RL训练覆盖**；
  [后续公开dev评估](t2-registration-student-eval-r1-result.json)仍是两题0分，没有证明完整能力提升。
  本轮不继续SFT生产，也不把历史SFT示范当作当前policy rollout。
- [v3八族诊断](../../examples/dsh/evolution_v3_live_scenarios.jsonl)：8条全部test，不能直接改split冒充新训练集。

上下文：

- [v1课程](../../examples/dsh/capabilities/context_tasks.py)、[r1结果](native-context-baseline-r1-result.json)、
  [r2结果](native-context-baseline-r2-result.json)、[分解审计](context-r2-audit.md)。保留旧奖励失败，不追认。
- [v2 specifications](../../examples/dsh/capabilities/context_tasks_v2.py)：16个显式case ID，
  directed/conflict/missing/version各3 train+1 dev；全体模式为direct2、index3、select11。
- [v2评分器](../../examples/dsh/capabilities/context_verifier_v2.py)、
  [准备器](../../examples/dsh/capabilities/prepare_context_training_v2.py)、
  [入口说明](context-online-rl-v2-runbook.md)。prepare产生train.parquet/validation.parquet/task.yaml/
  training.env/ops manifest，接已有train_qwen3_4b_online_rl及reload流程；默认仍为评估态。
- v2与v1是不同合同和奖励版本，不把新增分解奖励回写v1。现有16个工程组合包含真实规则/证据义务差异，
  不只是复制采样；但共用max_attempts目标、文本字段语法和少量业务域，不能称广泛上下文泛化。
- 默认两步、batch1、n4只消费打乱课程的一小部分；应报告实际消费task ID、有效组、组内奖励方差、
  policy版本及拒绝原因，而不是宣传“已训练12题”。无优势信号的全同分组不能仅靠参数变化证明有效学习。

记忆：

- [两个固定实例](../../examples/dsh/capabilities/memory_tasks.py)：constraints保持当前区域/禁令，
  updates含废止区域与新事实；当前输入事实固定，chain ID变化不增加实例数。
- [整链评估编排](../../examples/dsh/capabilities/memory_chain.py)、[运行手册](native-memory-student-chain-runbook.md)。
- [writer r1失败](native-memory-writer-r1-failure.json)：读源成功后96次试图修改只读源，无memory create；
  freeze_exists=false、reader_exists=false、training=false。后续反馈/重复拒绝预算修复不能自动抹去该失败。
- 缺口是学生完整A→冻结→B执行与无记忆对照，再是跨session训练归属；不把B分数任意赋给A。

RSI：

- [候选生命周期](../../uni_agent/tasks/dsh/rsi_candidates.py)、[固定policy renderer](../../examples/dsh/rsi_closed/profile.py)。
- [固定Linux canary](native-rsi-policy-linux-c5acd30-r1.json)：fixed_runtime_verified=true；
  inspect_list deny→allow→deny，实际文件只读与越权拒绝通过。
- 同报告明确training=false、model_evaluation=false、synthetic_selection_comparison=true。
  因此真实学生RSI训练实例/封存任务均不能从这份canary计数。

## 3. 最近可实施的最小增量：先工程，后效果

| 能力 | 下一最小工程验收 | 后续效果pilot（建议预算，非行业标准） |
|---|---|---|
| DSH | 保留M1作快速回归；先把一个T2结构任务的合法完成/失败与探索信号诊断清楚，按独立新run做有界更新与reload | 2个以上结构族，先12–24 train / 4–8 dev；工具组合、依赖/故障机制需变化，不能只改日志字符串 |
| 文件证据 | 直接使用已有12/4 v2课程，先真实dev与有限train采样确认奖励有区分度，再2步更新+独立reload；不先追加大量行 | 若出现可复现改善，再扩到约40–80独立train / 12–20 dev；变化目标字段、来源拓扑、缺失/版本组合。另建24–40未使用的封存实例作初步效果估计 |
| 记忆 | 每个已实现族各完成1条真实A/B链，再做对应no-memory或错链负例；按chain计数，先不扩大固定事实模板 | 动作/信用合同通过后，约12 train chains / 4 dev chains起步；改变约束依赖、更新类型和B问题。另独立创建4–8封存chains只能作早期检查 |
| RSI | 1个真实学生候选实验：固定父、至少2个独立开发实例比较、实际加载新进程/回滚；不把synthetic比较复用为生产receipt | 两种候选改进机制；先4–8独立候选演化实验，每个开发比较使用独立业务实例，按候选谱系分组留出。四格M0H0/M1H0/M0H1/M1H1区分来源 |

这些数量是有限工程预算建议，不是保证收敛或统计显著的门槛。特别是4题dev/4个封存chain
仅能暴露大问题，不能支持稳定能力排名。正式效果评估需基于pilot的成功率、paired差值/方差、
目标改善幅度与可用预算确定样本量，必要时继续扩充；不因达到某个整数就宣布能力通过。

## 4. 数据量不足时应先补什么

1. **先查真实消费**：可用题数、实际独立消费题数、每题尝试数、有效/拒绝组数分别统计。
2. **先补结构再补行数**：按规则组合、证据依赖图、故障机制、chain或候选谱系分割；新名字/新UUID不算新结构。
3. **先确认信号**：全失败检查动作可达性、反馈和预算；全满分回归题不能产生效果提升证据；
   同组同分需记录GRPO信号不足，不无限重复同题。
4. **数据与方法分离**：现阶段输入是在线RL任务/环境/verifier，学生现场采样；不引入SFT生产或教师轨迹替代本策略token。
5. **冻结评估边界**：封存集不得参与提示修改、奖励调权或RSI候选选择；公开v1/M1与现有dev均不重新封存。
6. **分项报告**：reward增长、strict accuracy、事实正确、证据覆盖、长期记忆因果收益、RSI实际复用分开；
   文件取证不能替代实际context切换，SDK canary不能替代学生训练。

结论：当前数据足以继续分批检验工程可行性；不足以支持“四能力已经提升”的效果结论。
最近应使用已有context12/4和两个记忆模板完成真实验收，同时补可学习的DSH任务结构与真实RSI
比较合同；不需要先建设海量数据生产系统。
