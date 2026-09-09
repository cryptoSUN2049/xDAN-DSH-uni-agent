# 独立短课程：单一动态事实的跨会话恢复

状态：设计，尚未实现/训练。原work-state r4已完成8步工程执行，但奖励/梯度为0，模型4→8没有变化；本设计不替换、追认或覆盖这些事实。先完成当前工程reload验收，再按独立课程进入效果阶段。

## 目标与最短路径

模型A读取一个业务事实，真实写入handoff与入口；新会话B通过入口读取模型保存的内容，生成正确业务配置。只练“事实保存→新会话恢复→真实结果文件”这一项，而不同时叠加版本冲突、复杂计划、六种文件的选择及格式推断。

```mermaid
flowchart LR
  S[只向A提供动态业务源] --> A[原DSH A loop]
  A --> M[index.md与handoff.md原字节]
  M --> F[原bundle冻结与哈希]
  F --> B[原DSH新会话B loop]
  B --> O[config.json与plan.json]
  O --> V[业务正确与真实读取证据]
  V --> T[原A/B完整n4组与TQ]
  T --> R[原VERL GRPO终态B奖励]
```

不新增外层执行loop、trainer、自动记忆整理器或SFT。继续使用NativeWorkStateFramework、StageSpec、独立Gateway session、原始token/mask、冻结bundle、严格安全准入及原始阶段receipt。A低质量但合法允许进入B；A原reward0不改写，由终态B奖励计算并广播同链优势。

## 独立身份与数据合同

- 新 `course_id=work-state-short-fact-v1`；新任务family `WS07`，新task ID前缀 `work-state-short-fact-v1-…`。业务task schema仍用现 `dsh.work-state-task.v1`，新增course_id只存在新任务。
- **保留**传输/安全/credit的 `contract_id=work-state-v1`：它标识A/B接线，不充当课程名。operator.family也继续为work-state-v1，避免增加新的Framework分支。
- 数据清单仍为现 `dsh.work-state-dataset.v1`，行严格 `{family,variant,seed,split}`；通过新family/ID映射到独立生成器。不能让Parquet metadata携带真值或自由覆盖任务，仅保留work_state_task_id。
- prepare顶层清单记录course_id、新课程源码闭包与数据SHA；reload母身份必须匹配course_id，不能仅因operator.family相同而把旧r4称为新课程母实验。没有course_id的历史清单明确解释为原 `work-state-v1` 课程。

首批8train：一个训练模板、8个互不重复的动态整数，固定种子101–108、值域40–399；采用固定伪随机生成及碰撞拒绝，先固定实例再运行，不依据模型表现挑数字。**8个实例不等于8种结构**。每题同一n4组四个sibling使用相同外生输入。

开发holdout固定2题：variant1、独立种子901/902、值域1000–1999；源采用嵌套JSON及不同字段路径，B目标字段保持公开业务schema。数据ID、数值、源结构均与train分开；不只换路径。开发集公开、不是封存benchmark。只在训练方案冻结后运行，不用其结果挑prompt、温度、步数或挑checkpoint；若读取结果后修改方案，应承认该dev已用于开发，不能继续称未参与选择的证据。

## 精确任务实例格式

variant0：A源 `sources/service.json` 含 `service` 与整数 `capacity`；variant1：源改为 `sources/deployment.json`，含 `service` 和 `limits.capacity_units`。业务语义都是“恢复该服务应使用的容量”；所有实例正确值仅存在A源，不在B prompt、task ID、文件名或metadata明文中。

A仅可写memory/index.md与memory/handoff.md。A源与conversation不传给B；只传真实写出且被冻结的两文件原字节。A可以写错误/空内容并正常结束，此时不能控制器纠正、补文件或拒绝为基础设施错误。

B仅有一条公开任务说明：恢复指定服务容量，创建 `config.json` 为**仅含capacity整数**的JSON对象、`plan.json` 为 `[]`。这是输出协议，没有示范实例答案。B不获A源、原会话、oracle或秘密值；只拿现有绝对index入口和接收目录。绝对路径只用于工具调用，index对handoff使用相对引用。

短A prompt建议约80–120英文词：

> Preserve the service capacity from the read-only source for a fresh session. Read the source first. Create handoff.md containing the supported service/capacity facts, then create index.md pointing to handoff.md by its relative name. These destinations start empty; use command=create and file_text. Do not change the source. Only saved file bytes reach B; your final response does not. After saving the two files, finish. Re-reading unchanged files is unnecessary.

短B prompt建议约80–120英文词：

> Recover the service capacity through the memory index at the supplied path. Read the index, then the handoff it references, before producing results. Create config.json with exactly one integer field named capacity, using the recovered value, and plan.json as an empty JSON array. File contents are business JSON, not tool-call arguments. Do not guess missing facts or change memory. Finish after writing the two result files.

这里固定两文件导航协议，暂不声称训练“何时需要保存/选择任意记忆架构”。不需要记忆的对照课程与自主组织能力后续独立评估，避免把本短课程扩成原六文件任务。

## 奖励与真实读取约束

保持安全/finished准入：越权或未完成仍按原门拒绝；合法但内容差或未读取给业务reward0，不把低质量改成安全错误。终态奖励仍为二元1/0，没有读次数、文件个数、长度或格式存在的赠分。

新WS07 reward1要求同时成立：

1. 原通用score_task验证精确动态capacity、类型/键集合及合法空plan；现有非WS03分支即可复用，不改旧族评分。
2. B成功view真实冻结index，index包含指向允许handoff.md的相对引用；随后成功view该handoff，返回文本与冻结原字节匹配。允许DSH合法view_range，但不能把局部片段或伪结果认作完整事实读取。
3. 两次工具结果发生在生成最终结果写操作的模型调用之前；不能将同一模型响应预先生成的view+create串当作“看完工具结果后作答”。依据assistant/message与tool/result的原事件顺序、call ID和step绑定，不仅比较工具调用次序。

没有读取而碰巧猜对动态数，或者只在最终聊天声称已读，不得reward1。读了也不证明模型注意力因果，但能保证任务要求的实际操作路径。读取失败、内容缺失、index坏引用均保留reward0；不自动修复。额外读取不加分。

新读取规则是**新课程质量合同**，不施加到历史WS01/03/05/06。原r4、旧reload继续使用各自固定source/旧verifier bundle重审；当前审计器的bundle严格校验意味着不能拿新checkout直接重评旧回执并冒称兼容。

## 文件/API最小变更

| 文件 | 改动 |
|---|---|
| work_state/short_tasks.py（新） | `make_short_task(variant:int, seed:int)->dict`；独立生成动态值/两种源结构/短prompt/truth。控制器参考只供测试，不导出学生数据 |
| work_state/tasks.py | `make_task` 对WS07显式委托；原四family逻辑逐对象不变。不得从任意模块名动态加载生成器 |
| work_state/stage.py | 继续现StageSpec接口，只允许白名单WS07清单行；任务memory_paths变为两文件自然复用bundle/policy。原A/B路径、私有fixture、冻结与token流程不复制 |
| work_state/short_read_evidence.py（新） | `verify_reads(fixture, events)->dict`，只处理新课程成功读取/内容/时序证据；复用现tool成对事件及固定DSH行文本证明方式，不绕过现文件安全 |
| work_state/verifier.py | 仅WS07分支将原业务成功与读取证据AND，增加诊断checks并更新bundle闭包；receipt使用实际新代码digest，不重写旧回执 |
| capabilities/prepare_memory_training.py | 新 `course_id` 参数/CLI `--course`，默认原课程；`_dataset_for_course(course_id)`；8train/2dev；selection/check/source闭包据所选课程校验；reload比较母course_id。保留旧模式和版本pin |
| capabilities/audit_memory_training.py | 仍调用固定新verifier重评WS07；如task重建处有旧family限制则只加显式WS07。保留原crosswalk/消费规则，不接受未知课程/schema |

不修改memory_credit、NativeMemoryFramework、NativeWorkStateFramework、TQ或VERL trainer。新task字段沿用现fixture→source_version→hash绑定；现work_state目录源码闭包应确认覆盖两个新增模块。

## TDD与工程验收

- RED先验证新family/课程尚不可生成；实现后8train+2dev可真实prepare/check/Hydra/from_config，n4/val1、sync、原训练脚本、独立reload都能接入。
- 原四family×两个variant×多seed与旧提交逐对象对照：truth/source/prompt/任务输出保持不变。旧recipe所有回归通过；旧固定checkout仍能审原旧run。
- 明文/结构泄漏测试：B初始文件/prompt/metadata无动态值、无A源；同组四样本同实例，跨train/dev ID和值不交叠，seed数量与结构数量分开统计。
- 真TaskConfigResolver+DshArchitectureTask+verifier子进程CPU链测试：合法A0→freeze→B1；A空/错记忆→B0；冻结篡改/跨组/越权拒绝；两个真实session身份不同，不自动填index。
- 读取反例：只读index、只读handoff、假tool结果、部分view_range、同generation预发写操作、输出前未见工具结果、重复读刷分、猜对但未读均不能拿1；真实顺序与全文匹配才可通过。
- 原始token/mask、receipt、最终A后B TQ键与固定GRPO末B广播回归；train n4不完整/版本不同不得消费；新course误用旧母checkpoint身份须拒绝。

**学习信号门**：先用固定基座、固定采样设置，仅在train实例做有界真实n4诊断。要报告有效GRPO任务信号，至少一个已完整消费同题组应有真实B终态奖励方差、非零优势与有限非零梯度；不能人工混成功/失败、借oracle轨迹或改变兄弟输入造差异。若全0/全1，如实报告无组内信号；该门是学习结论要求，不阻止工程保存checkpoint或独立reload。

训练步数、保存点与dev运行时机预先固定；dev不得作为选择最佳checkpoint/温度的工具。独立reload使用新课程母run的真实checkpoint-origin及新run路径，保留更新delta、optimizer、token消费与业务效果各层结果。原W4无更新结论不被本课程未来成功替换。
