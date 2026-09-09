# 原生 DSH 异步兼容性审计与最短性能对照

2026-09-09。只读审计本地固定源码并写本文；未改代码、未启动 GPU。用户最新优先系统性能与异步；[已有授权](async-followup.md)允许现有单卡上独立、有界 colocate_async，不需要重复确认，不扩 GPU，也不继续数据扩展。

**结论：先用已有单阶段 context-v2 做系统性能对照，比直接改 work-state A/B 更短。** 固定 VERL 已有 colocate_async、partial rollout 和 ReplayBufferAsync；不需要新 trainer。work-state 当前有两处 sync-only 启动门和同步单版本信用合同，不能仅改环境变量运行。context-v2 没有这些门，但旧消费审计按“提交步=消费步”关联，需要最小异步证据适配，不能直接将旧 audit 的 false 当运行失败或简单忽略。

## 1. work-state 的确定阻断

| 位置 | 源码事实 | 必须处理的边界 |
| --- | --- | --- |
| `uni_agent/framework/work_state.py:7` | NativeWorkStateFramework 继承 NativeMemoryFramework，仅替换 stage 行为 | memory 的所有 mode/信用约束仍生效 |
| `uni_agent/framework/memory_chain.py:281–287` | from_config 强制 trainer_mode=sync | 仅开 colocate_async 会初始化失败 |
| `uni_agent/framework/entry.py:179–180` | StrictSyncValidationRolloutAdapter 强制 sync | 准备器 `prepare_memory_training.py:435–440` 固定使用它，另有独立启动门 |
| `memory_chain.py:35–42,311,565` | expected_sync_policy_version=train提交步−1，val提交步 | 异步提交标签不保证对应整个 A/B 的实际生成版本 |
| `examples/dsh/capabilities/memory_credit.py:96–107,170` | 所有 trajectory 的 min=max=同一 expected_version；要求实际版本完整 | A/B 或兄弟组跨更新会被严格拒绝，不能删除检查后冒称仍同策略 |
| `memory_chain.py:68–69,143–158,531–540` | crosswalk 写入并重审同一 expected version | 在线改门而不改版本化离线合同仍不兼容 |
| `examples/dsh/capabilities/audit_memory_training.py:18,269` | 复用上述 crosswalk 审计 | 必须独立新增异步版本语义，不能改旧实验的版本结论 |

固定 `verl/verl/workers/rollout/llm_server.py:404–460` 的 FullyAsyncLLMServerClient 在 abort 后使用已生成 token 继续推理，保留原 log_probs，版本跨度以首次/末次 backend version 表示。`:421` 明确写出 partial resume 可使用不同模型版本。colocate trainer 在 `trainer_colocate_async.py:53–58` 采样后 abort/sleep、`:47–51` 更新权重并 resume；这是正常机制，不是业务失败。

因此“去掉两处 sync 门，保留其余代码”仍会把正常跨版本完整链拒绝；ReplayBuffer 随后补采，可能不断重试至外层墙钟终止。反过来把 min/max 改成提交步或只取末版本会破坏真实证据，不能做。

如果后续必须在 work-state 测 async，需要版本化合同分开记录 group 提交步、各 trajectory 实际版本跨度、消费更新步；确认此实验允许的 off-policy 语义及对应策略校正配置。原同步同策略 n4 合同与旧报告保留。新合同仍要求真实完整 n4×A/B、完整 logprob、原始终局业务信号和唯一消费，不接受任意缺版本的轨迹。

## 2. 可复用完整组与 refill，不需要新实现

- `framework.py:694–710` 等待所有 sibling；`:751–787` 一条失败整组拒绝、零轨迹准入，批量写失败则清理候选键并标记 failure。`memory_chain.py:323–324` finally 清理 pending；原 A写→冻结→B 及 receipt/工件检查不受异步调度替换。
- `trainer_base.py:158` 为非 sync 选择 ReplayBufferAsync，`:166` 提供 `_add_prompts_to_generate` refill callback。
- `replay_buffer.py:515–522` async 对训练的 stale、DAPO、failure 计算淘汰；`:547–570` 整 prompt 淘汰并补采。`trainer_base.py:676–688` 强制 gen_batch_size=1，`:1383` 每次新 uid，`:1421–1424` 重取真实 prompt，不复用已消费键。
- `sync_refill_failed_groups` 名字不是 async refill 开关；async 自身已淘汰失败组。不要再写一层补采循环。合法同分/零奖励也不能当 failure 人为丢掉来凑梯度。
- `replay_buffer.py:503–512` 的 stale 是以 **prompt提交步** 算 age，不是逐 token 的真实 version 跨度。报告两种量，不把一个冒称另一个。`:531–537` 的 wait 策略会等陈旧在途组；先有界冻结策略再对照，不现场改参数挑吞吐。

## 3. 暂停、超时与有效并发

`replay_buffer.py:547–573` 轮询没有自身总 deadline；`agent.py:53,266–269` 的 helper run_timeout 默认1800秒，work-state stage sandbox也为1800秒（`work_state/stage.py:97`）。暂停训练占用的墙钟仍会计入 helper，不应把因长暂停导致的超时写成合法低业务分。保留外层 owned-process supervisor、健康检查和终止后子进程/GPU释放验证，分别记推理、暂停、工具与初始化时间。

`prepare_memory_training.py:394` 当前 CONCURRENCY=1，单个 semaphore 横跨完整 A/B（`framework.py:888–904`）。提高 warmup 只增加排队 prompt，未必产生真正并行或 partial；若实际没有暂停恢复，不能仅凭 trainer_mode 宣称 async 性能通过。

partial client 是在**一次模型生成内续接**，不是重跑整个 DSH 工具任务。应在真实 canary 核对工具 call ID、顺序、唯一结果，避免把模型请求重试误解成应重放已执行工具。

## 4. 最短可复用单阶段：context-v2

### 4.1 已有任务、入口与准备状态

`examples/dsh/capabilities/context_tasks_v2.py` 已有12 train/4公开dev：定向/索引取证、权威冲突、缺值和版本判断；`context_verifier_v2.py:score` 基于实际只读 view、引用和业务结果评分。它明确 scope=file-evidence-only、context_switch_verified=False。作为系统吞吐对照合适，但不能叫真实compact或记忆能力实验。

`prepare_context_training_v2.py:22–207` 已编译 Parquet、task.yaml、manifest、training.env；`:96–98` 固定 helper/sandbox 900秒、8192总token/2048每轮；`:103–107` 只是输出 VAL_ONLY=True、RESUME_MODE=disable、TRAINER_MODE=sync **默认环境值**，无禁止 async 的参数校验。其 operator_required 原本就允许 source 环境后覆盖实际训练参数。

`examples/dsh/train_qwen3_4b_online_rl.sh:89–107` 已接受 sync/colocate_async 和正整数 warmup；ops wrapper 也解析/传递该值。默认 `:294` 使用普通 AgentFrameworkRolloutAdapter，未选择 StrictSyncValidationRolloutAdapter，也未注入 NativeMemoryFramework。

**因此现有运行组件已具备入口；无需新增单阶段 runner 或改准备器任务规则。** 但原准备 manifest 没有完整绑定所有 launch overrides 和 effective VERL source，必须另存不可变实际 command/environment/source 身份 sidecar，使用现有监督/版本核验，不悄改原 prepared 文件后声称 hash 没变。

### 4.2 是否还有同步版本准入门

`uni_agent/tasks/dsh/trajectory_audit.py:223–250` 校验 token/logprob、finished、split、Gateway/DSH 身份、trace、独立 verifier receipt；没有 memory 的 min=max=step−1 门。普通 `GatewayAgentFramework` 不锁 trainer_mode。

这表示**没有同步版本拒绝，但不等于已经严格审计了异步版本**。Gateway `session.py:829–849` 输出实际 min/max、generation_count/versioned_generation_count；framework `:1593–1598` 在缺值时仍可能以 scheduler fallback 填 tag。async 结果必须独立要求 version_evidence_complete=true、有效整数span和完整生成计数；不能仅用TQ tag默认值充当真实版本证据。

普通 trajectory audit 可复用，但需要加独立 async版本/消费审计，或小型版本化postprocessor组合（若作为准入门），不能复用 memory 的单版本断言。需要何种在线阻断由首轮实验计划明确，不得把事后缺证据的作业称为通过。

### 4.3 旧通用消费审计有真实异步兼容缺口

`examples/dsh/ops/audit_qwen3_4b_online_rl.py:314–324` 将 dump 提交步与TQ键构成 `(group_step, key)` 后与实际消费记录比对。异步时 step1提交的组可能 step2消费，原审计会同时报 missing_consumed 和 unexpected_consumed；这不是实际重复或丢失。

`:349–366` 总通过条件又要求所有记录组都 eligible-and-consumed，不允许合法 stale 淘汰或真实拒绝组留证。旧 sync 报告已经保留部分拒绝状态；新 async 不能靠改成恒true绕过。

最小适配：以 **partition+TQ key** 唯一关联，保留 submitted_step、实际version span、consumed_step；检测跨step重复消费，核整组所有sibling在同一消费batch。未消费组分别归入失败/过期/剩余在途，绑定真实日志或TQ淘汰证据；未知和重复消费继续阻断。旧 audit 与 schema 保留，新独立报告可以引用它的原始false并解释已识别的语义差异。

## 5. 已有 sync 基线与公平比较

- [两步原生runbook](context-online-rl-v2-runbook.md)：已有真实更新和独立reload；只覆盖部分train。
- [12步课程结果](context-v2-curriculum-r1-result.md)：固定d3084f2，1000.024秒exit0，12有效batch/48消费/11唯一题，6步非零任务梯度；D3越权整组拒绝、D2补采，旧audit不伪装全通过。
- [step12独立reload](context-v2-curriculum-r1-reload-result.md)：470.012秒、四dev真实fresh消费通过；strict0/4，无提分。504 LoRA变化/399 base冻结和optimizer推进有独立证据。

这些证明课程有可用信号、现存基线和保存/reload路径，**不是当前固定集成源码的严格性能对照**。历史源码、结束原因补丁、初始化/JIT、保存次数及dev频率不同；不可拿旧总秒数直接除新run秒数就报加速倍数。

最短公平实验是在当前同一固定checkout/base/runtime/verifier上分别新建sync和colocate_async短run，使用同任务预算、相同冻结顺序/seed、n4及相同batch/保存/评估频率。两侧统一关闭初始/周期dev，保存后独立reload；首次初始化单列，训练稳态有效组/分钟、生成token/秒、暂停/工具等待、失败/过期比例、peak显存分别报告。不同完成速度可能导致异步消费实例集合不同，须记录并限制解释，不能只比成功样本吞吐。

## 6. 现成命令骨架与未完成事项

以下是现有工具的组合入口定位，**本轮未执行，不代表预检和异步审计已完成**。先按context runbook在固定GPU主机准备全新private data/run，source新training.env；分别为每一侧绑定实际配置sidecar和现有owned supervisor。

```bash
# source 新准备的 training.env 后；每侧新 run/data/checkpoint 路径
export VAL_ONLY=False
export TRAINER_MODE=colocate_async  # 对照侧为 sync
export NUM_WARMUP_BATCHES=1
export TOTAL_TRAINING_STEPS=4
export SAVE_FREQ=4
export TEST_FREQ=0
export DATA_SHUFFLE=False
# CONCURRENCY、max_num_seqs 与 off-policy阈值由同预算实验计划预先固定
bash examples/dsh/ops/launch_qwen3_4b_online_rl.sh --foreground \
  trainer.val_before_train=False trainer.test_freq=0
```

4步只是有界建议，不修改用户任务预算要求；当前脚本默认 concurrency=1/max_num_seqs=1，初轮计划必须明确是否提高二者以实测partial。选择后sync/async两侧相同，只有mode及必要warmup差异。不新增GPU、不原样运行多卡separate_async。

启动前最小待完成项：

1. 冻结当前模式/采样/预算、模型与effective VERL源码，补实际配置sidecar；dry-run用独立scratch，旧ops PRINT_COMMAND会产生run工件。
2. 为异步消费步/版本span提供上节独立审计，并覆盖跨步正常消费、重复消费、缺版本、整组失败/stale淘汰负例。
3. 验证单阶段partial续接下finished/token/logprob/工具调用完整，保留900秒helper和外层墙钟边界；不可把abort直接当已完成输出。
4. 同源码短sync→async运行后分别保存/独立reload；比较系统指标与实际覆盖。非零梯度是否出现如实记录，不为性能测试伪造奖励差异。

完成此单阶段系统对照后，再决定将同一async证据合同延伸到work-state A/B。性能主线不需要先完成144条新数据、跨课adapter初始化或第二套trainer；多阶段的同策略/跨版本信用语义也不能因此被静默绕过。
