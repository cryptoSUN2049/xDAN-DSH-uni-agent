# 工作状态课程：失败传播与终态信用的消费侧审查

2026-09-09。只读设计审查；未改代码、VERL pin、旧训练门或远程运行。依据当前 NativeMemoryFramework、固定 VERL V1 sync 与真实 train-r2 失败产物。

## 结论

存在不修改 VERL pin 的短路径：在本项目 rollout adapter 对 **strict sync validation** 等待 framework 完成并传播原错误，让失败在进入 ReplayBuffer 前退出；训练仍保持现有异步提交、同步策略更新与完整组补采。合法 A0+B0 的新工作状态链可复用固定 VERL 末 B GRPO，无需新 trainer，但不能直接通过旧 memory 的 A=1 冻结合同；必须新建明确版本的任务/准入合同。

## 1. 为什么原异常变成 empty keys

真实 train-r2 首先在 initial validation 的 A 写错事实，A finished/fresh/eligible 但 reward0；旧 StageSpec 的 writer quality gate 正确拒绝冻结，未产生 B 或 TQ 轨迹。后面的基础设施表现由四个环节构成：

| 位置 | 实际行为 | 影响 |
|---|---|---|
| `uni_agent/framework/framework.py::_run_prompt_rollouts` | `gather(return_exceptions=True)` 收集异常；`_short_failure_reason` 保留最多512字符；标记 prompt `status=failure`，不写 sibling 轨迹 | 准入正确，但第一错误只在返回的 failure_reasons |
| `GatewayAgentFramework.generate_sequences` | 在记录 summary 前先抛仅含失败数量的 RuntimeError | 具体 `Writer failed quality gate` 未出现在顶层异常，阶段原因丢失 |
| `uni_agent/framework/entry.py::AgentFrameworkRolloutAdapter.generate_sequences` | fire-and-forget `.remote()`，丢弃 ObjectRef | actor 原异常不能同步传给 trainer，只在 Ray unhandled 日志出现 |
| 固定 VERL `ReplayBuffer` | val 不做 failure eviction；sampleable 是 finished∪failure；val 被排除在“无可物化轨迹”检查之外 | 全失败 val prompt 被选中，`_materialize_batch` 最后请求空 TQ keys |

源码锚点：`trainer_base.py::_validate` 在 `generate_sequences(batch)` 后立即 `replay_buffer.sample`；`replay_buffer.py::_terminal_eviction_reasons` 对 val 返回空集合、`_sampleable_terminal_keys` 包含 failure，`sample` 尾部只为非 val 检查空轨迹。当前并不存在独立 `_apply_verifier_reward` 方法。

## 2. 推荐最小 integration 改动（待实施）

### 2.1 validation await，只作用于明确选择的 sync 配方

推荐新增本项目 `StrictSyncValidationRolloutAdapter(AgentFrameworkRolloutAdapter)`，例如 `uni_agent/framework/strict_validation.py`，由新工作状态配方的 `agent_loop_manager_class` 明确选择，原有默认 adapter 保持原语义。

- `create(...)` 检查 `trainer.v1.trainer_mode == "sync"` 和严格失败标志；沿用父类 `create`（内部使用 `cls()`，可保留 subclass）。
- `generate_sequences(prompts)` 读取与 framework 相同的可信 `tu.get(prompts, "validate", False)`。
- validation 时提交一次 `.remote(prompts)` 并 `ray.get` 同一个 ObjectRef；失败就向同步 `_validate` 抛出，**不返回成功、更不继续 ReplayBuffer.sample**。复用已有 `generate_sequences_and_wait` 的等待语义，禁止意外提交两次。
- train 时继续调用父类 fire-and-forget。不能对 train 也一律 `ray.get` 并遇错退出，否则会改变 `sync_refill_failed_groups=True` 的既有训练补采行为。
- 保留 run 级 owned supervisor 的 wall-clock 上限；若新增 RPC 超时，应将其报告为独立 timeout 并交给已有 owned lifecycle 清理，不能默认 ray.cancel 已证明所有 DSH 子进程退出。

这个变化是等待 validation 的完成回执，不新增 DSH 外循环，不把训练切换成 fullyasync；validation 本来就会阻塞等待样本，等待点前移可保留失败因果。

另一条可行路径是固定 VERL 已支持的 `trainer.v1.sampler.custom_sampler`：本地 ReplayBuffer subclass 对 val 全失败空轨迹抛清楚错误。但它需要复制或介入 sampler 内部逻辑，仍拿不到 actor 原始原因，首选成本更高。无需直接改 vendor ReplayBuffer 或改变其 commit。

### 2.2 framework 保留第一错误

对本项目 `framework.py` 做一处小改：抛 strict rollout 错误时包含已有有界 `stats['failure_reasons']`，或在抛前写结构化失败摘要。保留 partition、trainer step、uid/sibling、异常类型/短原因；不要拼接整段模型输出或 token。原异常为 StageSpec quality 还是版本/冻结/权限问题必须可区分。

无需把 stage 失败转成 reward0 来消除异常。普通合法低质量链能否训练，交给下面的新课程合同；基础设施错误、缺实际 token、未完成/越权仍失败。

### 2.3 必要 CPU 测试

1. fake Ray ObjectRef 真实抛 StageSpec 错误，strict val adapter 将错误传出，固定 `_validate` 的 replay sample/TQ 调用计数为0；无第二次远程提交。
2. val 成功等待完成，后续仍有完整 n1 keys，原消费审计通过。
3. train 保持非阻塞与失败标记，固定 sync refill 仍可补齐完整 n4；不因新 adapter 遇失败强制停止可补采训练。
4. 原具体失败短原因从 `_run_prompt_rollouts` 一直出现在 driver 异常，非法 token/版本与 A质量失败可区分。
5. timeout 与取消保留已有监督清理边界，不能把异常返回当成功消费。

## 3. 新工作状态 A0+B0 如何进入末 B GRPO

固定 VERL 已支持一个 sibling 中多个连续 trajectory：`v1/utils.py::compute_advantage_for_multi_trajectories` 按 `{uid}_{sibling}_{index}` 找最后一段，用末段 B reward 计算组相对优势，再将 advantage/return 广播给同 sibling 的全部 A/B 真实生成 token。此处没有改写各阶段原 `rm_scores`。

因此对四条同题、同源、同事件种子和实际 policy 的 sibling：

- A0+B0 可以是**合法但语义质量差**的完整链；保留 A/B 原 stage reward0，末 B0 进入组比较。
- A0+B1 也应可表达：A质量代理指标差但 B最终成功，终态信用是1；不应由代理 A 分数提前否定最终任务成果。
- A1+B0 仍是终态失败，不能靠漂亮的 A 工件拿到链成功。
- 四条 B 全0或全1没有组间 GRPO信号；要报告全同分比例和实际梯度，不能人工改分或把 n4当四个独立训练任务。

末B reward 用于 credit；A/B stage score 与事实保真/成本指标留作独立诊断。首版继续二值终态 reward，暂不增加未经验证的分段塑形或蒸馏。

## 4. 不能直接复用的旧门与新合同边界

当前至少两处明确禁止 A0：

1. `examples/dsh/capabilities/memory_training_stage.py::validate_stage_execution` 在 writer reward!=1 时抛 `Writer failed quality gate`，freeze 调用它。
2. `examples/dsh/capabilities/memory_credit.py::validate_credit_group` 要求 `a.reward==1`，并严格关联 FrozenBinding、A/B receipt 与真实 trajectory 对象。

旧 eval `memory_chain.py` 也有 A=1 门，但不应为了新训练课程修改旧 eval。不能仅绕过第一处就宣称完成 A0接线，也不能将 A0旧 receipt 事后改成1。

建议新建 `work-state-stage.v1`、对应 verifier ID/version 和受控 credit admission 标识，由 operator/配方选择；样本不能配置放宽门。新 verifier 输出独立的 `finished`、安全/身份/格式准入、`freeze_eligible` 与语义 quality；合法低质量工件可原样冻结，交给独立 B 尝试。缺少可选索引可通过“工件集合缺项”清单表达，B据实际允许原件降级搜索；未完成、越权、伪造来源或无法确认的基础设施失败仍不可冻结/训练。

延续原工程资产：原 Task/唯一 DSH loop/Gateway 原 token、StageSpec operator 路径控制、A→B冻结 hash 与身份、实际版本完整性、完整 n4/n1、TQ 连续 key、独立消费 audit。新 admission 合同需在 StageSpec、credit validator、crosswalk checker/auditor同步显式分派；数学 credit 规则仍可复用 `terminal-reader-grpo-v1`，但旧合同不能默默接受新 A0。

新课程最短路径：一个完整工作状态任务族 → 合法低质量与越权负例 → resident val 的合法 A0+B0 可产完整链 → 同题 n4 → 消费与参数/optimizer审计 → 独立 reload。不要先引入 Harbor、Modal、SFT、fullyasync或新训练框架。

## 5. 四种循环与身份保持分离

- **任务内部循环**：DSH 内的模型观察/动作/工具反馈；A和B分别拥有独立 session。view/create同一模型消息的依赖错误属于这一层。
- **跨会话链**：控制端 A验证→原样冻结→B新会话，绑定 chain/run/source/manifest/parent receipt；不增加模型执行 loop。
- **采样/参数更新循环**：固定 VERL sync；四sibling同实际版本，train调度step与actual policy version按已验证规则分开，val同当前实际版本。Ray并行任务不代表 fullyasync训练。
- **候选演化循环**：当前未启用；不得把一次记忆修订/文件覆盖称为 RSI 候选晋升。

## 审查结果

结论可直接支持后续小设计实施，但本报告不是修复完成或新课程训练成功证明。旧 r1/r2、train-r2 原结果与门保持不变；本轮没有 GPU 操作。
