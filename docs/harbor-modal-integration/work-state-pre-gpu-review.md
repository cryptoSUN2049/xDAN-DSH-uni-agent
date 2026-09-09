# Work-state：GPU 前独立复核

2026-09-09。审查 tasks/scoring/stage/verifier/profile/policy，随后按批准范围修正两处合同；未启动模型。CPU Task/CLI 使用测试模型替身；真实 Linux SDK canary 与 GPU 学生评估必须另列证据。

## 结论与已修复契约差异

没有发现必须靠新增 shell、MemAgent loop、教师或升级 runtime 才能解决的结构阻断。四族 oracle 配置/计划能通过业务检查，A0→B0 已有 CPU Task/独立 verifier/freeze/复核证据。但实际编辑器参数、profile 加载、missing-file 错误行为仍需要固定 Linux runtime 验证，不能拿 Python fixture 测试替代。

**已修复：新可写文件 view。** stage 将可写路径加入 profile.readFiles，但 A 的 read_missing 为空；原 policy 将“先 view 确认合法新目标不存在”拒为越权。当前 [policy.mjs](../../examples/dsh/capabilities/work_state/policy.mjs) 对显式 writeFiles 的叶文件允许缺失，交由 native tool 返回 ENOENT；未知路径、符号链接、不安全父目录仍拒。A/B 两个新增 Node 测试先失败后通过，原四个权限测试保持通过；真实 Linux SDK 的错误形状仍需 canary。

**已修复：同分坏输出缺少字节绑定。** [verifier.py](../../examples/dsh/capabilities/work_state/verifier.py) 的 reader score 新增 `extra_info.output_snapshot_sha256`，绑定 `pack_bundle(output_root, task.result_paths, max_bytes)` 的 canonical 原字节与 missing inventory；不含答案或语义修复。评分前后快照不一致立即拒绝。reader fresh receipt 的 evidence 固定六项，索引5为该摘要；writer 不增加此字段。消费审计须重新计算并核对该位置，而非仅比较 reward。两个新增测试先因缺字段失败，随后证明 `{}`→另一个坏输出虽均0分，摘要不同；缺输出→坏输出也不同。业务评分合同保持二元。

**本机验证：** Node policy 6/6；Python verifier/bundle-profile/stage 共54项通过；包含真实 subprocess verifier CLI 回执，但 Task/model/Gateway 仍为 CPU 替身。独立消费审计的同分篡改测试由 framework 接线任务补齐，不将本模块摘要测试冒充最终训练消费验收。


## 数据、提示与可解性

- `make_task()` 的 truth 仅置于私有 fixture；模型输入只含 writer/reader goal、各自来源路径、获准工件位置。新 B 未获 A transcript、writer-data 或 oracle outputs；oracle_memory 的相对 `modules.md` 入口可在 B memory root 解析。
- 真实 B 不获得全部 memory 文件路径清单，须从固定 index 查找。若 A 写入指向 writer 绝对路径的失效索引，B 不应被允许读 A 私有目录；这是可观测失败，不能由 controller 重写索引来通过。B 可以停止并报告缺证据，合法终态0。
- WS01 用 DAG 检查重复/遗漏/依赖顺序，接受不同合法拓扑顺序；WS03 用真实组件属性判断兼容，选项名不提示答案；WS05 区分作用域/版本及 security authority；WS06 公共资料足以完成而无需 memory。它们是配置/计划工作流，尚非代码修复与模型自行运行测试。
- `create` 必须把内容放字符串 `file_text`；`str_replace`/`insert` 用于已存在文件。目标只告诉模型允许行为，没有把任务动作脚本直接塞给学生。A 先生成 view 与 create 同轮调用时，create 参数仍可能未依据实际 read 结果；提示已要求先看到读结果再写，但真正执行仍由模型决定，错误事实应保留低分。
- 当前 reader 必须实际成功写出 config.json 和 plan.json；自然语言声称完成不计分，preseed 文件且无成功写调用不计分。短任务不强迫写 memory；WS06 全同分导致零 GRPO 属真实诊断结果。

## A0 延迟评分、隔离与证据

A 无语义质量门，正常结束固定 reward0/eligible；空记忆、错误草稿、缺 index 按真实字节 pack，不修复。B 重新验原 memory_artifacts manifest/content/AB身份，canonical repack 展开文件比较 inventory 与缺失项。模型只能读授权输入、写角色对应的 memory 或 outputs，source/truth/verifier 不能被修改。

B 正常但错误/缺输出是质量0；越权、未完成、不完整 tool pair、immutable 输入或 frozen bundle 篡改拒绝。阶段原 reward 不改写；后续 Framework 必须使用 work-state 合同的终态 B credit，不能进入旧 writer 满分门。当前 CPU stage 审计不自行生成训练回执、不伪造 real token；stage helper 的少量 token 是显式测试替身。

## 最小真实 DSH 无模型 scripted canary

可复用已有接口，不新增训练循环：

1. 以新的私有 root 创建真实 sources、A memory 目录。调用 [build_work_state_patch](../../examples/dsh/capabilities/work_state/profile.py) 固定 role/chain/session/sourceVersion、精确读写路径；不要把探针加入训练 profile。
2. 参考 [deployment/checks/dsh_memory_policy_canary.py](../../deployment/checks/dsh_memory_policy_canary.py):37—88 的实际 `DeepSeekHarnessConfig`：`profile='sdk-minimal'`、`patches=(patch_path,)`、独立 cwd/runtime_cwd/dsh_home、`base_url='http://127.0.0.1:1'`、无模型请求。在 context manager 内等待固定 report；使用安装 runtime 而非可变源码 wrapper。
3. 复用 [memory_closed/probe.mjs](../../examples/dsh/memory_closed/probe.mjs):12 的真实 `ctx.tools.execute({callId,signal,name,arguments})`。calls 是 operator-only `{label,name,arguments,expectedText}`。A 顺序执行 view 来源、create modules.md、create index.md、view 验读；再检查 source 写入、未知工具/路径、链接被拒。view 不存在的授权 memory/output 应进入正常文件不存在错误而不是权限拒绝。
4. 原 probe 的 `policyDenied` 只识别 `MEMORY_POLICY_DENIED`，对新 `WORK_STATE_POLICY_DENIED` 无效；不可原样据此判新 policy 通过。新 canary 需识别新 marker，且检查实际 isError/结果、文件字节与未泄露来源目录。该改动限 operator probe，不改 agent-loop。
5. 关闭 A runtime 后，直接 `pack_bundle(A_memory, task.memory_paths)`→`freeze_memory_artifact()`→`unpack_bundle()`，新 B runtime 只给 B 来源、解包的只读 memory、可写 outputs。让探针实际 view index/modules，再 create oracle config/plan；控制端 `score_task()` 必须通过。追加空 A bundle→B失效 index 的合法读取错误、B错误输出0等真实动作反例。
6. 这些直接 `ctx.tools.execute` 调用只证明工具/runtime/文件隔离与业务可解性；它们**不经过真实学生采样和 Gateway token**，通常也不生成 Agent turn 对应的完整 Task trace。因此不能把该 canary report 填入 `freeze_and_prepare_reader(spec, execution)` 冒充正式 StageExecution。正式 stage 函数要求实际 typed TaskResult/trace/receipt；当前其 CPU 测试链与此 runtime canary 是互补证据，不可拼成虚假的 GPU 成功。

## 放行界限

固定 Linux 工具/权限/真实字节 canary 通过后，才进入有界 GPU 学生 baseline，观察A是否实际读后写、B是否经索引恢复、各题合法失败与n4组内差异。完整训练须再通过 real token/version、整组消费、有效梯度、参数/optimizer、checkpoint 与独立 reload。可解性canary成功不能代替任何学习节点，也不应因为学生失败修改当次任务标准。
