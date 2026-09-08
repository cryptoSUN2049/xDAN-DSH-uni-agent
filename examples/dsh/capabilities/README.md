# N1 上下文文件证据诊断 v1

目标：两族各两个实例；定向取证（存在/缺值）、冲突裁决（当前权威存在/缺值）。
这只是 `file-evidence-only`，不是实际 context 切换、跨会话记忆、SFT 或大规模数据。

## 合同与文件

`context_tasks.py` 生成固定 source 文件、contract.json、tasks.jsonl。
contract 包含 schema、case_id、family、target_key、authoritative_source、sources(path/sha256)、
required_evidence(source/line)。源文件使用独立行 key=value；期望值由 verifier 重新解析当前权威文件。
完整答案 JSON：`status`（answer/insufficient_evidence）、`value`（字符串/null）、
`citations`（source/line/quote 三字段数组）。缺值必须弃答，禁止用被取代的旧值填补。

`context_verifier.py` 接收现有 DSH task-result envelope 和 canonical trace；验证 artifact/trace/
fixture/source/code bundle 哈希以及现有 task/session/verifier 身份。工具必须为对指定 source 的
完整 str_replace_editor view，结果必须非错误且包含被引用的真实原文。只猜对最终答案无分。

奖励合同：完整安全完成 + 正确答案/弃答 + 精确必需引用 + 所有 source 的真实读取证据 = 1；
普通错误 = 0 且 eligible=true；越权工具/路径/修改 = 0 且 eligible=false；
哈希、身份、工具配对损坏直接失败。未完成不能准入。输出标准 fresh verifier 结果，
由现有 DshArchitectureTask 创建回执；此模块不制造 RL token 或准入回执。

验证：2族4例正分；错误/旧值/伪造引用/未读到内容为0；路径逃逸与写操作拒绝；
源文件、trace、身份篡改失败；现有 receipt parser 接收合法结果。

后续真实 context 切换接口必须额外提供执行器捕获的 before_context_id、after_context_id、
外部 snapshot digest 和动作前观测证据。当前结果明确 context_switch_verified=false，
不能把模型自报 ID 或压缩 token 数量直接当成功指标。

## 手动生成与接线

在固定 Git checkout 的 CPU Python 环境运行（目标目录必须不存在）：

```bash
python -m examples.dsh.capabilities.context_tasks --output /tmp/n1-context-r1
```

产物为 4 个 case 的 `sources/*.txt`、`contract.json` 和 `tasks.jsonl`；JSONL 包含
messages 与 metadata，路径绑定本次输出目录，不能不重建就迁到另一台机器。
这是诊断输入，不自动转换为训练 Parquet，不声明 train/heldout 独立性。

现有 `dsh_architecture` 任务配置使用：

```yaml
verifier_command: [python, -m, examples.dsh.capabilities.context_verifier]
require_trace: true
workdir: /tmp/n1-context-r1
```

其余 agent/model/runner/result_root 使用主线已验证配置，保持 DSH 为唯一执行循环。
以现有准备器填入环境 digest，使用每行 metadata 的独立 task/verifier identity 与
bundle digest；生成后不要覆盖 metadata 为 M1 evolution 身份。执行器须保留原始 canonical
trace，并提供标准 DSH_* 环境变量，不能直接把学生 JSON 当 verifier 结果。
若更改 checkout 源码，重生成课程以更新 code bundle，不能静默沿用旧 hash。

独立 verifier CLI（由 Task 调用，调用者必须设置完整 DSH_* 身份和路径）：

```bash
python -m examples.dsh.capabilities.context_verifier
```

成功输出单个 JSON 对象；证据/身份损坏退出 2，不输出可供准入的成功回执。
真实 runtime 的 `formatFileView()` 使用六列行号 + 两个空格，评分兼容该精确格式及原文行；
`max_attempts=30` 不能证明读取了 `max_attempts=3`。

## 本地验证状态

新增 15 项 CPU 测试及原有 verifier/Task 回归合计 36 项通过。
覆盖标准 `_task_result` 消费并生成现有格式回执；这只是协议单测，不是 Gateway token 采样、
GPU 参数更新或新模型能力验收。原生模型实际运行由主线执行器负责，当前尚未在本模块验证。
