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

## 最小修复建议（仅设计，尚未实施）

最接近真实 token 的控制点是 **Uni-Agent Gateway session**，而不是用 adapter 返回后的文字重分词或离线 verifier 事后截断。

1. 由 operator 固定配置向 A/B 创建 session 时传递可信 `max_generated_tokens`（建议通过明确的 session 配置/metadata 字段，不能由模型请求或样本正文覆盖）。prepare、manifest/source closure/check 同步绑定这一新增合同。
2. Gateway 保存 session 生命周期的真实 backend completion token 计数，使用 backend 返回的 token_ids 数量；工具/context mask0 不扣该生成预算。每次请求上限取 `min(per_request_cap, remaining_generated_budget, remaining_sequence_capacity)`。
3. 计数独立于可回滚 trajectory buffer：重试/last-assistant rollback 不能退回已用生成预算，否则可绕过上限。并发请求须预留预算或串行原子扣减；超额 backend 返回必须保留异常证据并拒绝，不能静默截断。
4. 预算耗尽沿现有正常 `finish_reason=length → DSH max-tokens` 路径结束，继续产出 trace、result、receipt。不要杀进程导致缺失配对，不改成 completed，不放宽 unfinished/eligible 判断。业务已完成且未耗尽的零奖励轨迹仍按原合同处理。
5. 不改变策略版本、权重同步、A/B session 身份、TQ 完整组规则；新代码与配置固定后使用新 run。r4 原始证据按原预算解释，不能事后重标为违反已执行的 8192 上限。

文件预估：Gateway session 配置/管理与计数、framework/operator 的可信配置传递、准备器绑定与测试；DSH runtime 本体无需因此先升级。不能仅改 agent.py 的 max_tokens 赋值冒充累计限制实现。

## 新 run 验证项

- CPU：多轮生成与工具上下文混合，生成总量到上限；单次小于/等于剩余；mask0不计；rollback/retry不返还预算；并发/错误/未知值 fail closed；未配置预算保持旧行为。
- 合同：拒绝样本/请求覆盖预算，manifest 防篡改；记录 per-request、生成累计、sequence 三种独立指标，匹配实际 tokens。
- 真实 GPU 新 session：指定可重复长任务触发累计上限，trace/result/receipt 完整，finish_reason 正确；正常短任务继续完成。验证拒绝组补采样不退出整作业。
- 再检查完整组消费、非零有效梯度、参数变化、checkpoint 与独立 reload；预算修复通过不自动等于能力提升或整个训练验收通过。
