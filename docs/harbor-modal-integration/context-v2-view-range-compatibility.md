# Context v2：真实 view_range 准入兼容修复

2026-09-09。根因来自只读审计 GPU `/root/runs/context-v2-exploration-r2`，源码 `daa7073`。本修复已获主线程批准，限定本地 verifier 和反例测试；不修改旧结果或远程 checkout。

## 真实失败与设计

16 条会话全部正常 completed，16 份新鲜 verifier receipt 均生成，但 eligible=false，strict 拒绝 TQ 写入。不是模型未加载、超时或 verifier 进程错误。68 次真实 `str_replace_editor view` 全带 `view_range`：8 次 `[1,1]`、60 次 `[1,5]`。旧 v2 要求参数键恰为 command/path，因此将全部正常范围读取标为 `non_source_view`。

例：`artifacts/results/ac63af7ce6f3d53b7952796e/agent-result.json`，对应 trace `artifacts/traces/db85a08c5e7368f327e534c2/session.jsonl`。实际结果有六列行号，例如 `     1  selected_source=sources/current.txt`。运行时报告包含末尾空行的总行数；源字节通过 splitlines 产生的完整内容行仍须逐行匹配。

目标：允许 DSH 只读 API 的合法参数，评分仍以真实返回的完整文件内容为准。接口只增添可选 `view_range`，不修改权重、答案或引用规则。

- 允许 command/path，或 command/path/view_range；command 必须 view，源必须精确 allowlist。
- view_range 省略或 null 均为全文件。否则必须是两个整数的列表，不能 bool；start≥1 且不超过文件实际行数；end 不超过实际行数且 end≥start，或 end=-1 表示到文件末尾。错误长度、字符串、反向、非法负数、超出实际行数拒绝。
- 合法局部 view 本身安全，但缺任一源内容行不计完整读取分；语义分仍要求全裁决源已完整读取。
- 不根据 range 宣称“读过”，也不把多次局部读取拼成未经设计的新读取机制；必须至少一次成功结果包含该文件全部原始内容行。
- range 本身也须覆盖从首行到最后一个内容行；局部 range 即使出现不一致的“全文件”结果，也不能获得 fullread。文件末尾换行形成的额外空行不增加知识内容，但仍计入 API 合法范围上限。
- 文件外读取、写工具、额外参数、工具错误、事件身份不完整与 unfinished 沿用硬门。
- 不修改 v1；v2 新代码闭包摘要自然变化，prepare 生成新身份绑定。旧摘要和旧 r2 回执保持原样，新实验用新 run ID。该兼容修订必须记录在发布说明，不能将旧结果重标为成功。

## 反事实证据边界

只读 CPU 在内存副本移除 view_range 后，旧评分逻辑对 16 条轨迹均能确认完整源读取。诊断奖励：dev-D `[0.671875,0.1,0.671875,0.69375]`；dev-C 四条 0.1；dev-M 四条 0.1；dev-V 四条 0.72。全部严格准确率仍为 0。只有一个结构组有奖励差异，还不足以宣称 GRPO 多结构信号门通过。

上述为错误隔离实验，修改过的内存事件不具备原 trace hash，不是有效训练回执，不能送入优化器或覆盖真实失败。

原设计“两种结构有差异”的门槛是诊断建议，不是框架硬约束。下一最短路径是新摘要、新 run 的4个 dev fresh strict 验收准入，再做原生两步 RL 观察真正 n=4 组的方差与语义分，不必再花一轮16条 dev采样。原生两步可作为工程诊断；若实际 reward advantage 全零，不得给出有效任务学习通过结论。dev 反事实既不训练，也不替代这个真实判据。

引用分母是任务合同明确列出的必要行数：dev-D/dev-M 各16行（清单1＋三份配置各5），dev-C 25行，dev-V 20行；因此 dev-D 一条正确必要引用占1/16，dev-V四条占4/20。模型多只给最终值的一条或几条引用，完整引用要求未满足。这里仅解释分母，不临时减少证据义务或修改满分标准。

## 固定 API 源码依据

DSH commit `b2369692ea530007075ebcd18d39fdba0bbd3982`，`packages/fs/tool-str-replace-editor/src/index.ts`，完整文件 SHA256 `dba956fee3d85217b8a56cf8830a178e416ef6015a85b08086a4d2c289e6174a`，通过本地 `git show <commit>:<path>` 读取固定对象而非浮动工作区。

- 143 行 `content.split('\n')`：末尾换行产生一个空行；我们的5行配置文件在 runtime 共6行。
- 150–156 行要求两整数；160–168 行 start/end 不得超过实际总行数。
- 170–177 行 end=-1 到末尾，否则 end≥start；切片边界包括指定最终行。
- 459–464 行 schema 明确 array 或 null，描述 null 等同省略；474 行 `args.view_range ?? undefined` 落实这一语义。

因此 `[1,5]` 和 `[1,6]` 对本课程5行且末尾换行文件都合法；前者已覆盖所有内容行，后者还包含末尾空行。`[1,999]` 非法，不能因为返回文本伪含全文就接受。

## 测试与实施范围

先使用真实调用形状、行号格式及 [1,1]/[1,5] 范围编写 RED；修复后验收完整读正例、局部读不计fullread、合法范围但错误结果不计读取、非法范围、未知键、表外源与写操作拒绝。并回归原 v2 与完全不动的 v1。

变更：`examples/dsh/capabilities/context_verifier_v2.py` 参数验证；`tests/uni_agent/examples/test_context_training_v2.py` 真实参数形状与安全边界。保留 DSH 唯一 loop，不改 runtime 或 trainer。

结果：真实参数形状测试先 RED（5条失败）；局部range伪装全文件另有独立 RED；修复后 v2/v1 组合83 passed，Ruff check与format通过。未修改GPU文件、旧trace或回执，未commit。
