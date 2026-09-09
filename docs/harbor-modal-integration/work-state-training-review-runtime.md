# work_state 课程：最短运行时适配审阅

只读源码审阅，未改代码、未改当前远端实验。目标是模型生成 handoff/index 等工作状态，A结束后冻结，新B从固定入口恢复并用真实工具完成新任务；复用 NativeMemoryFramework、Gateway/TQ、固定VERL sync。不是完整context compact，也不另建trainer。

## 1. 为什么不能只加一个 family

现有 `memory_training_stage.py` 的 family只影响 `memory_tasks.writer_fixture` 中两个固定事实题。至少五处是硬合同：

1. `_prepare` 的权限是A读source+memory、只写一个memory文件；B只能读memory+question，**不能写结果**。`memory_closed/profile.py` 只有 `write_file`，policy只接收单一`writeFile`。
2. `freeze_and_prepare_reader` 冻结单文件到 `frozen/memory.bin`，问题固定为region/forbidden/source_version；reader expected_answer来自旧 expected_memory。
3. `memory_verifier.py` 要求A整个JSON等于expected_memory、B最终文本JSON等于expected_answer，无法评分handoff目录索引、后继工具工件或避免重复动作。
4. `validate_stage_execution` 明确A reward必须1；`memory_credit.validate_credit_group` 又单独要求A=1且A/B奖励为0/1。只去掉第一道门仍会在整组写TQ时拒绝低质量A。
5. Framework `_outcome`、crosswalk记录及auditor绑定的是单一frozen manifest/content digest。多文件不能仅多写几个路径却不纳入freeze/读回审计。

旧合同应保持可回归；新课程必须显式版本化，不放宽既有memory诊断规则。

## 2. 最小任务与真实工具边界

第一题用小型工程配置交接：A获只读目标、项目片段、已完成检查的原始回执；可选择写 `handoff.md`、`index.json`、少量按白名单限定的笔记。B获同一只读目标、一条新增任务，以及固定 `memory/index.json` 入口；自己检索handoff并通过 `str_replace_editor` 生成 `result/plan.json` 或修改明确白名单配置。独立verifier读取实际文件并验证新约束与状态，没有写文件只最终回答不算成功。

这是最短有真实副作用的文件任务；若要“跑测试/构建”，新增受控命令工具白名单、执行回执和退出码合同后再接，不能为了方便重新开启任意persistent-bash。B对结果目录有写权限，但目标、证据、freeze目录和verifier始终只读/不可见。

模型可见输入与控制端真值分开：A知道当前任务，不见B隐藏题解；B可读目标与新任务，能否访问原工程文件由具体任务固定。A真实调查得到的事实可以保存，不能把这种正常记忆误判为泄漏。B提示不直接给真实目标笔记路径，必须从固定入口索引发现。每个n4组用相同初始项目、同一B任务/外部变化；跨组变结构。

## 3. 多文件freeze最短复用

优先复用 `uni_agent/tasks/dsh/memory_artifacts.py` 的安全单文件冻结原语，而不复制一套有竞态的目录复制实现：

- controller只收集精确白名单下**实际存在**的模型文件，以安全regular-file/no-symlink读取，逐个校验大小、总字节和UTF-8/格式边界。
- 包成版本化canonical bundle：相对路径→原始bytes/base64、逐文件SHA/size，显式记录缺失文件。controller仅做字节包装，不补索引、修错事实或创造handoff。
- 将bundle字节作为单个输入交给现有freeze原语，仍生成manifest/content SHA。合法A没有写任何文件时可用显式空bundle，不凭空补内容；是否成功由B终局决定。
- B新私有目录仅展开bundle中真实存在的获准文件，byte-for-byte核对manifest；固定entry缺失就保留缺失，让B实际遇到可观察错误或执行获准恢复策略。
- B执行前后核冻结bundle、展开的只读文件和原始A文件库存摘要；可写结果输出独立。`FrozenBinding.content_sha256`继续绑定bundle整体，额外per-file inventory绑定在新stage fixture/回执中。

不能只检查memory.bin摘要然后允许B读取另一个未绑定目录。不可直接用不校验路径的tar解包。空bundle、部分文件和错误索引都是可学习状态，不应由controller语义修复。

## 4. 版本化低质量A准入与信用

新 `work_state/v1` 合同将安全/可审计完成与质量分离：合法读取/写入、完整真实trace和终止、可冻结文件库存满足即可eligible；遗忘关键事实、空索引、错误但合法的handoff可以A reward0。越权、目标/证据篡改、非regular/越界路径、基础设施异常仍拒绝。

首批可保持二元A/B原始奖励，最小化现有credit修改：新合同仅取消A必须1；终态B依据实际结果文件和约束取0/1，保持“最后B reward→固定VERL GRPO广播”不变，不修改原stage reward/receipt。需要分解奖励时再增加独立v2支持有限[0,1]，不能只在verifier返回小数而忘记credit的binary门。

新合同id必须来自controller固定recipe白名单，绑定StageSpec/receipt/chain receipt/crosswalk；不能让sample metadata选择“宽松准入”。旧contract默认A=1，新work_state明确允许A=0；仍强制同组完整n4、A/B独立session、实际version完整同policy、train调度k→weight k-1/val k→k、all trajectories和唯一实际消费。

允许低分不等于缺少证据：合法失败A仍需真实token、finished回执和可冻结状态；B也实际运行并形成终态。没有B证据不能给整链伪造0分塞进TQ。若A写入错误JSON，初批可将文件当原始文本安全保存，并由B发现；禁止解析器崩溃被误称模型失败。是否接受文件格式错误须在task schema明示。

## 5. 有界接口与文件清单

| 文件 | 建议最小变化 |
|---|---|
| 新 `capabilities/work_state_tasks.py` | 版本化任务包、A/B可见输入、只读目标/原始证据、输出/索引白名单、truth独立存放 |
| 新 `capabilities/work_state_verifier.py` | 实际工具调用/结果文件、目标未改、来源/事实/新约束，分开eligible与quality；返回既有fresh TaskResult形状 |
| 新 `capabilities/work_state_bundle.py` | 多文件安全inventory→canonical bundle→原freeze→B展开/重验；无模型语义加工 |
| `memory_closed/profile.py` / `policy.mjs` | 新版本只允许明确read_files/write_files集合，B指定result可写；默认单文件legacy路径不变 |
| `memory_training_stage.py` 或一个新work_state stage模块 | 复用StageSpec字段和真实TaskConfigResolver/runner；按controller contract选择prepare/freeze/validate/score，避免复制完整Agent loop |
| `memory_credit.py` | 明确contract参数并绑定outcome/assignment：legacy A=1，work_state A可0；其余strict不放宽 |
| `uni_agent/framework/memory_chain.py` | 最薄可信contract分派：使用同一StageSpec prepare/validate/freeze接口；_outcome/chain记录保留bundle inventory绑定；原_run_prompt_rollouts和TQ批写不复制 |
| `audit_memory_training.py` / crosswalk审计 | 识别新contract，要求新bundle/展开文件绑定，继续从trainer消费日志证明消费；默认旧模式不被新低质量准入覆盖 |
| `prepare_work_state_training.py`（或固定recipe扩展） | 真实多结构train/dev数据，不只改uid；固定contract/source/pin、budget、stage inputs；复用已有监督和ops |

接口优先保持 `prepare_writer_stage(...)→StageSpec`、`freeze_and_prepare_reader(spec,execution,reader_gateway_session_id)→StageSpec`、`validate_stage_execution(...)→receipt/envelope/score/fixture`。通过静态controller合同registry选择旧/新实现即可，不设计可动态加载任意函数的框架。FrozenBinding现有六字段可继续描述整体bundle；新inventory放版本化fixture/receipt，审计必须确实校验，而不只留下unused字段。

## 6. 最小测试与实际推进顺序

1. 先RED：A两文件合法写、B结果写入、A0→实际freeze→B0/1→完整group当前应被旧合同拒绝；明确新旧规则对照。
2. Node policy真实边界：精确多路径写、只读goal/evidence/frozen、跨组、symlink/traversal、动态index指向越界、混批view/create（执行先后不假定读结果已被模型看到）。
3. bundle CPU：部分/空文件、总预算、悬空index、坏格式、重复路径、目录/软链接、freeze后篡改、B展开字节替换；原A缺失不能被补全。
4. 真实TaskResolver+真实DSH工具canary+真实verifier子进程，A→freeze→B生成实际结果文件；工具合成轨迹只能标CPU合同，不冒充GPU模型动作。
5. Framework集成真实StageSpec（fake Gateway tokens仅CPU），新contract A0合法链可完整n4消费前准入、旧A0仍拒绝，stage原reward不改、实际version缺失/错版本仍拒，crosswalk无遗漏/重用，取消失败不遗留部分消费。
6. 先一条val fresh真实模型，再同题n4探索合法终态reward分布，再在线RL有限更新→实际消费审计→checkpoint/optimizer→独立reload。出现全同分只报告无学习信号，按下一版结构/难度扩充任务；不人为改本run奖励。

本增量验收的是跨会话工作恢复。自主选择“何时保存”还需多决策点、可见中断/预算信号和不必保存的对照；真实compact需下一模型请求确实收缩且旧历史不可旁路，不能借多文件handoff直接宣称context窗口管理已训练完成。
