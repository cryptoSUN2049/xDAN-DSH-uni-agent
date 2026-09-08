# Uni-Agent / VERL 成对同步设计

日期2026-09-08；状态：fetch与merge-tree只读预演完成，尚未合并或checkout新VERL。

## 目标与精确版本

保持DSH已有运行能力和严格训练准入，同步Uni-Agent 89733ec81a69c3cc93ac90479de7ea7f01e51c1f及其gitlink VERL fefb080262e1c015a0ea05f958822a6a512dc795，不使用两仓各自浮动main。当前VERL483b8a009ba3a97563edee3a19887e4862b8094a；目标相差52提交。此次发现纠正“只需迁移5提交且保持旧VERL”的前一阶段建议。

基于768cdef进行预演；预演不会更新工作区/index，合成tree含冲突不能当可运行代码。

## 架构与API迁移

AgentRunner → TaskResult → Framework / RewardLoopWorker → strict admission → TransferQueue → VERL。
Gateway只保留会话、token及版本责任。采用上游typed结果与schema2方向；DSH独立verifier仍拥有奖励，finished未确认、超时、错配或不完整组不得训练。不得用默认scorer重算覆盖可信DSH奖励。

DSH TaskResult原有reward_info/receipt等扩展字段逐一映射到typed结果或独立证据上下文，不静默丢弃；移除旧HTTP reward posting的生产依赖，但保留历史schema1审计读兼容。postprocessor必须保护finished、奖励及谱系字段。同步模式保持不变，不同时启用全异步或OPD。

## 文件范围

直接文本冲突清单如下；此外需检查自动合并的Gateway、session、多chain测试与本地DSH strict admission、ops/audit/launcher接口。VERL只更新子模块pin，不自行改上游代码。

- `docs/source/concepts/gateway-and-trajectories.md`
- `examples/inference/parallel_infer_verl.py`
- `tests/uni_agent/framework/test_generate_sequences_on_cpu.py`
- `tests/uni_agent/framework/test_task_runner.py`
- `tests/uni_agent/gateway/test_message_codec_tool_dispatch.py`
- `uni_agent/framework/framework.py`
- `uni_agent/framework/task_runner.py`
- `uni_agent/tasks/base.py`

## 分批执行与验收

1. 当前文档提交保留为恢复点，在当前隔离worktree执行显式目标merge；按语义解决冲突，禁止整文件选ours/theirs覆盖DSH修复。
2. 先复用现有测试复现不兼容；补typed DSH结果、strict finished None/False、receipt重放/错配、group原子拒绝、custom scorer、多chain传播与历史schema读测试，再迁移生产逻辑。
3. checkout对应VERL，核查训练配置、checkpoint加载、TransferQueue/奖励API；恢复点保留旧版本身份，历史run不改写。
4. 编译、Ruff check/format、聚焦DSH/Gateway/framework/launcher/audit回归；记录环境缺失与未执行测试，不把skip算通过。
5. 保存同步manifest、差异review与回归证据后提交。CPU通过仅能称代码同步/CPU兼容，真实模型执行和optimizer/reload在后续固定环境验证。

## 边界与审批

无当前训练作业，因此不涉及运行中迁移；但仍不能用历史GPU结果背书新版本。未购买资源、未付费调用、未push。用户要求同步与避免冲突；此次新发现52提交VERL差异和8处冲突，按用户Development Preflight的Design First/Human Gate先呈现此具体迁移设计，再实施。
