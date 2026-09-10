# Core token 预算：已生效边界与累计输出缺口

2026-09-10，只读审计固定执行 checkout `/workspace/rebuild/uni-agent-core-511bd71`、现有 `core-train-r4` 已结束的首 writer。没有改变 r4 的提示、配置、采样、准入、运行或 SDK/adapter。

## 实际证据

首 writer：`memory-f5ebe4e661f44f899099e949a4dbb941`，Gateway session `memory-A-bd3ea42810274512a6974fb75380a9f1`。

- `writer/task.yaml` 的 agent.model：`max_total_tokens=8192`、`max_tokens_per_turn=4096`。
- DSH Session v2 `request/header.header.config.maxTokens=4096`；最终 `turn/end.data.reason.kind=max-tokens`。其 runtime `run/traces/436fad0045f9e35eadb5bf31/result.json` 同为 `finish_reason=max-tokens`。
- `/root/runs/core-train-r4/memory-launch-plan.json` environment：`MAX_PROMPT_LENGTH=8192`、`MAX_RESPONSE_LENGTH=8192`。
- 实际 NPZ：`/root/runs/core-train-r4/agent-logs/step_1/memory-A-bd3ea42810274512a6974fb75380a9f1/trajectory.npz`。
- NPZ SHA256：`3c5d8edfe3cff6a1c4398df70a752dedd557451594a4ae143068ca1312b97843`。
- `traj0_prompt_ids` 1637；`traj0_response_ids` 14747，其中 mask=1 的模型生成 9529、mask=0 的工具/续接上下文 5218。
- **1637 + 9529 + 5218 = 16384**，恰好命中 Gateway 总序列容量，而不是累计模型输出 8192。

## 接线根因

`uni_agent/agents/base.py:41` 将 max_total_tokens 定义为全 episode completion token 之和；但 `agents/dsh/agent.py:251` 优先读取 max_tokens_per_turn，仅在其为空时才回退 max_total_tokens，最后只传一个 `DSH_UA_MAX_TOKENS`。`agents/dsh/runner.py:88` 将其作为 `DeepSeekHarnessConfig.max_tokens`。因此当前配置的 8192 **不是软停止值，而是没有被作为累计预算执行**。

Gateway `session/session.py:197` 的容量是 prompt_length + response_length；`:489` 把工具增量加入 buffer；`:503` 构造总上下文；`:520` 按剩余总序列容量限制下一次生成。此文件运行哈希与 manifest sources 一致：`82f40a83aef76940e907b87caa84d1d3978e03ee2242cacbcf45ee6f17a9ed51`。

当前应记录：**每次请求最多 4096 个生成 token；每个 Gateway trajectory 总序列最多 16384 token，包含初始输入、模型输出及工具上下文。task 配置中的累计生成 8192 尚未兑现。** A 与 B 为独立 session，分别计容量；不能称整条 A/B 链合计 16384。

## 当前 SDK 是否已有累计预算 API

只读检查远端实际安装的 `/workspace/venvs/uni-agent-rebuild-cf2d3f5/lib/python3.12/site-packages/deepseek_harness/api.py`：`DeepSeekHarnessConfig` 仅公开 `max_tokens`，没有 max_total_tokens/completion_budget 字段。当前集成 runner 也只使用这一入口。本地 DSH 源码对应 Python client 的 initialize 映射为 `maxTokens`；SDK protocol/server 将其传入每次模型请求配置，未见该公开链路中的累计输出计数器。不能把 API 未暴露推断成整个 DSH 所有插件绝无相关能力；即便另有插件，也不是 r4 已接通能力。

## 最小修复设计（现已本地实现，尚未部署 r4）

最接近真实 token 的控制点是 **Uni-Agent Gateway session**，而不是用 adapter 返回后的文字重分词或离线 verifier 事后截断。

1. 由 operator 固定配置向 A/B 创建 session 时传递可信 `max_generated_tokens`（建议通过明确的 session 配置/metadata 字段，不能由模型请求或样本正文覆盖）。prepare、manifest/source closure/check 同步绑定这一新增合同。
2. Gateway 保存 session 生命周期的真实 backend completion token 计数，使用 backend 返回的 token_ids 数量；工具/context mask0 不扣该生成预算。每次请求上限取 `min(per_request_cap, remaining_generated_budget, remaining_sequence_capacity)`。
3. 计数独立于可回滚 trajectory buffer：重试/last-assistant rollback 不能退回已用生成预算，否则可绕过上限。并发请求须预留预算或串行原子扣减；超额 backend 返回必须保留异常证据并拒绝，不能静默截断。
4. 预算耗尽沿现有正常 `finish_reason=length → DSH max-tokens` 路径结束，继续产出 trace、result、receipt。不要杀进程导致缺失配对，不改成 completed，不放宽 unfinished/eligible 判断。业务已完成且未耗尽的零奖励轨迹仍按原合同处理。
5. 不改变策略版本、权重同步、A/B session 身份、TQ 完整组规则；新代码与配置固定后使用新 run。r4 原始证据按原预算解释，不能事后重标为违反已执行的 8192 上限。

文件预估：Gateway session 配置/管理与计数、framework/operator 的可信配置传递、准备器绑定与测试；DSH runtime 本体无需因此先升级。不能仅改 agent.py 的 max_tokens 赋值冒充累计限制实现。

### 已授权最小实现 API

- `GatewaySession(..., max_generated_tokens: int | None=None)`：独立正整数预算与累计backend输出计数；新增锁仅序列化启用预算的session。backend返回token_ids计数，rollback不退款；backend失败使计量未知时该预算session后续fail closed，不能继续重试取回预算。未配置旧路径不加锁/不变更行为。
- `_GatewayActor.create_session(..., max_generated_tokens=None)` 显式控制面参数传递；模型HTTP请求不能改变此参数。
- `GatewayAgentFramework._execute_gateway_stage(..., max_generated_tokens=None)` 只由框架调用参数传给真正的manager.create_session；不从sample_fields或request抽取预算。
- `NativeMemoryFramework._stage_generation_budget(spec)` 默认None；`NativeWorkStateFramework` 覆写，读取可信operator可选字段。A/B各自创建独立有预算session。
- `WorkStateOperator.max_generated_tokens=None` 校验正整数；prepare仅core写8192，check拒缺失/覆盖。已有源码closure含gateway/framework/work_state全路径，新增行为随源码hash与新manifest固定。
- 测试文件：新增Gateway预算测试；扩stage接线、workstate、prepare实际Hydra测试。覆盖耗尽正常length、工具不计、rollback、重试/异常、并发不超领、旧默认、控制面到真session和manifest篡改。远端r4仍用511bd71，不部署本修复。

### 本地实现与验证

新增 `test_session_generation_budget.py`。首轮10项测试先因缺少API失败，后通过；prepare两项删除/覆盖预算与真实stage创建Gateway session测试也先观察RED，再贯通。完整组合回归255项通过（69.50秒），覆盖准备器、原生memory/work-state、Gateway stage与旧多chain行为。

随后补实际 `trajectory.json` 的 `max_generated_tokens` 与 `session_generated_tokens_at_materialization` 字段；未配置预算不新增字段。累计耗尽的 materialization_reason 为 `max_generated_tokens`，序列容量耗尽仍为 `max_trajectory_length`，两者同时到限优先记录累计生成耗尽，协议finish_reason仍length。该批受影响113项通过；最后17项预算测试全部通过（含双限制同时到限），Ruff检查通过。

明确保守策略：配置预算的session发生任何请求异常（包括backend前本地校验异常）后都poison，必须新建session；这是故意fail-closed，不声称所有异常都已消耗生成token。已返回backend token_ids在后处理前累计，后续logprob/decode错误不退款；未知取消/错误不能以剩余预算重试。未配置预算保持旧并发与错误语义。

计数证据是session累计、截至trajectory materialization的快照，不是该trajectory独占增量，不能把多个trajectory快照相加。真实A/B分别由stage控制面创建session，测试覆盖真正actor.create_session并确认sample字段不能覆盖8192。旧版本/评分/receipt/TQ合同没有放宽，仍需新run完成以下GPU验收。

## 新 run 验证项

- CPU：多轮生成与工具上下文混合，生成总量到上限；单次小于/等于剩余；mask0不计；rollback/retry不返还预算；并发/错误/未知值 fail closed；未配置预算保持旧行为。
- 合同：拒绝样本/请求覆盖预算，manifest 防篡改；记录 per-request、生成累计、sequence 三种独立指标，匹配实际 tokens。
- 真实 GPU 新 session：指定可重复长任务触发累计上限，trace/result/receipt 完整，finish_reason 正确；正常短任务继续完成。验证拒绝组补采样不退出整作业。
- 再检查完整组消费、非零有效梯度、参数变化、checkpoint 与独立 reload；预算修复通过不自动等于能力提升或整个训练验收通过。

## 2026-09-10 14:50 SGT：隔离Linux部署与CPU复核

- 新目录 `/workspace/rebuild/uni-agent-core-4232df3` 固定 `4232df3fb47a67cb68c517811b972ddc9bfa2086`；经GitHub fetch取得，未使用scp覆盖代码。
- 独立VERL checkout固定 `fefb080262e1c015a0ea05f958822a6a512dc795`，既有 `preserve-finish-reason-v1` overlay显式应用并hash验证通过；根git仅预期` m verl`，无其他改动。
- 复用 `/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python`，没有重新安装Python/GPU依赖。新目录以 `CUDA_VISIBLE_DEVICES=`、`OMP_NUM_THREADS=1`、`MKL_NUM_THREADS=1`、`PYTHONPATH=.:verl` 执行 `python -m pytest tests/uni_agent/gateway/test_session_generation_budget.py -q -p no:cacheprovider`：17 passed，28.96秒。此为CPU fake-backend协议回归，不是模型GPU预算canary。
- 同时实查r4 PID21105/21295/24216仍存活，执行HEAD仍 `511bd71792c7a26af83cb0fe6362cd0f7d5aba96`，原Gateway session.py SHA256仍 `82f40a83aef76940e907b87caa84d1d3978e03ee2242cacbcf45ee6f17a9ed51`。
- 后续必须在当前训练及既定reload完成后，使用新目录/新run身份执行真实预算验收；当前不启动第二个GPU任务，不把新预算用于旧母run的reload。
