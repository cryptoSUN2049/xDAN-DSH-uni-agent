# 原生 A→B memory：真实 token 与延迟奖励接线设计

状态：**只读源码调研与拟实施设计，尚未实现，也不是训练验收**。审计本仓 HEAD `208dfcbc164ba5dcf16b02dd903fa7843131690e`。上游固定 Uni-Agent `89733ec81a69c3cc93ac90479de7ea7f01e51c1f`、VERL gitlink `fefb080262e1c015a0ea05f958822a6a512dc795`；DSH source `b2369692ea530007075ebcd18d39fdba0bbd3982`，runtime 0.1.3-alpha.2。以 deployment/versions/g1-source-lock.json 和实际每 run 部署清单为准。本轮未运行模型、GPU、SFT 或远程命令。

## 结论与最短路径

现有 VERL v1 **已经支持一个采样 episode 的多个真实 trajectory，共享末段 GRPO advantage**。无需新 trainer，也不应把 MemAgent 的逐 chunk 模型循环套在 DSH 外面。缺的是本项目将两个独立 DSH/Gateway session 组成一个可信训练 episode 的控制端接线。

最短可靠路径：新增 memory 专用 Framework subclass，复用已有每 stage 执行/审计、Gateway finalize、组级 TQ 提交；A→freeze→B 是固定任务阶段状态机，每阶段仍只有 DSH runtime 自己的 Agent Loop。将 A、B 各自 Gateway 返回的 Trajectory **对象列表按阶段排序**，作为同一个 `{uid}_{sample_index}` 下的多个输出交给现有 VERL。绝不拼接两段 token 数组，绝不从文本重建生成 token/logprob，绝不把 B 当第五个 GRPO sibling。

## 已有能力与实际边界

| 源码 | 已支持 | 尚不能推断为已支持 |
|---|---|---|
| `uni_agent/agents/mem_agent/agent.py`，`examples/mem_agent/train_native_smoke.sh` | 更新独立 context、最终回答、同 episode 多段；原生 recipe 使用 v1 sync、GRPO、n=4、trajectory_selection=all | MemAgent 是它自己的模型调用策略；其 ContextManagerResult/transcript 不是本 DSH 的真实 token 数据源，也不是文件隔离机制 |
| `uni_agent/gateway/session/session.py`、`types.py` | 保存真实 prompt/response IDs、模型 token mask、对齐 logprobs；context 分支/容量 materialization；版本 min/max | Trajectory.chain_id 是 Gateway 内部整数分支号，不能冒充业务 memory chain_id；版本缺失时框架会 fallback，不能当实际策略版本证据 |
| `uni_agent/framework/framework.py:_run_agent_episode` | 创建一个 Gateway session，运行一个 runner，finalize 后赋 TaskResult reward，逐 trajectory 审计/导出；strict n 组原子提交 | 当前 runner 只拿一个 SessionHandle，结果只有 TaskResult；不能安全交回两个 stage 的 session 对象与 lifecycle。postprocessor 还强制保持 finalized reward fields，不适合偷换 A reward |
| `verl/verl/trainer/ppo/v1/utils.py:compute_advantage_for_multi_trajectories` | GRPO 取每 `{uid}_{session_id}` 最大 index 的末段，仅末段参与 sibling 组统计；将结果广播到同 episode 全部段的 response_mask=1 token | 非 GRPO 不走上述广播；直接改用 GAE 没有等价保证 |
| `verl/verl/trainer/ppo/v1/replay_buffer.py` | TQ `{uid}_{session_id}_{index}`、组终态、sync/async策略；支持多输出 | 默认 sync failure 可留下缺失样本由后端 padding；本路线不能把 padding 当真实 n=4 |
| `examples/dsh/capabilities/memory_chain.py` | A 真调用→独立回执核验→白名单冻结→新 B；身份/hash；当前只 eval、credit_assignment=none | 当前分两次 inference invocation，不能据 checkpoint label 声称两段同一线上策略版本，也没有跨 stage 训练 credit |
| `uni_agent/agents/dsh/agent.py`、`tasks/dsh/trajectory_audit.py` | DSH session 固定 `dsh-{gateway_session_id}`，对应独立 home/artifact，严格核实回执与 Gateway | 同一个 Gateway 地址启动 A/B 会复用身份/home；不能只改 prompt 伪装新会话，也不应放松已验收单 session 审计 |

## 四种循环身份必须分开

1. 任务内长循环：`stage_role=A/B + gateway_session_id + dsh_session_id + turn/step/request_id`，由 DSH 执行动作。
2. 跨会话记忆链：业务 `memory_chain_id + writer_session_id + reader_session_id + frozen_manifest_sha256`。B 无 A 会话历史，仅受控文件输入。
3. 采样/参数更新循环：`training_run_id + partition_id + group_uid + session_index(0..3) + weight_version + global_steps`。global_steps 是调度标记，不代替后端实际版本。
4. 候选演化循环：未来 `evolution_cycle_id + candidate_id + parent_candidate_id + promotion_receipt`；此次 memory 不产生 RSI 候选，不用 source_version 代替晋升版本。

ContextPilot 树分支 partial rollout 是上下文候选机制；异步训练 partial rollout 是权重更新/调度机制；均不是此处 A→B 固定阶段链。

## 拟新增控制端合同

新增 `NativeMemoryFramework(GatewayAgentFramework)`，通过现有 framework_class_fqn 注入。抽取现有 `_run_agent_episode` 的单 stage 执行/审核逻辑为内部 helper，默认 runner 路线行为不变。memory subclass 在**一个逻辑 sampling episode** 内依次调用两个 stage helper，每个 helper 创建独立 Gateway session 并复用 `run_task`、DSH Task 与原单 session审计。

```text
sample uid, sibling j, policy version v
  → stage A: Gateway GA ↔ DSH A（已有原生动作）
  → finalize GA + stage receipt/真实tokens校验
  → 冻结文件与身份，准备 B 的独立 home/profile/allowlist
  → stage B: Gateway GB ↔ DSH B（仅 frozen memory + question）
  → finalize GB + stage receipt/真实tokens校验
  → chain receipt + 同版本/无重用检查
  → ordered [A trajectories..., B trajectories...]
  → uid_j_0 ... uid_j_k → 4 sibling 全部完成后 strict TQ batch
  → 现有 GRPO 末段 B 计算 advantage → 广播 A/B → VERL 更新
```

helper 返回一个内部 typed StageOutcome：stage identity、原始 TaskResult/receipt、真实 trajectories、审计结果、实际 weight span。它不是模型可返回的字典；控制端从可信对象构造。无需将 GatewayManager 暴露给模型/工具；Framework 持有并管理两阶段生命周期。

新 chain receipt 单独记录 `credit_rule=terminal-reader-grpo-v1`、末段奖励与 A/B 原始回执摘要；**不改写 A 原始回执为 B 分数**。阶段审计先验证原始字段，再由显式 chain admission 产生训练注解。在 chain 最终对象中另存 stage_original_reward/receipt，chain-level reward_score=R_B，并绑定新 issuer/code hash；不能通过通用 trajectory_postprocessor 绕过 reward 保真检查。

每个阶段独立保留 DSH audit context.gateway_session_id；最终 group/sample身份相同。`parent_stage_receipt_sha256`：A=null，B=A回执摘要；B再绑定 writer actual session、source_version、冻结 manifest/content hash。顶层绑定代码/recipe/fixture/prompt_revision/runtime/model checkpoint和 tokenizer/template hash。每条 trajectory 保留 role、原 stage trajectory index、Gateway内部chain_id、业务memory_chain_id；TQ index只作扁平输出顺序，不能当 lineage。

## 真实 token、训练 mask 与策略版本

- Gateway response_mask：模型生成=1，插入工具结果/上下文=0；原 prompt 不算生成。B 读到 A 文件内容是 B 的 observation，不能再次作为 A 的生成 token 收费/训练；A 原始模型 token 仍只出现于 A 段。
- Framework 将 source response_mask 同时写为 response_mask/loss_mask，extra_fields 不能覆盖。角色字符串或 Worker返回mask不应能扩大训练范围。worker/scorer仅给终态事实与奖励，不能生成训练 token 或自行决定 train mask。
- 使用 trajectory_selection=all，不能 longest，否则可能丢 A 或 B。每段 response_ids/mask/logprobs长度、真实mask=1计数、token数组摘要全部做跨 stage/TQ消费 crosswalk；不复制历史段去构造 B。
- 第一版仅 v1 trainer_mode=sync；`rollout.mode=async`是推理调用方式，不意味着 fullyasync trainer。固定同组四条 A→B全部完成后才更新权重。训练前验证所有A/B实际 backend min_global_steps=max_global_steps=v且同组一致；字段缺失明确拒绝或先补后端版本证据，禁止偷偷以调度global_steps fallback通过。
- LoRA base revision、adapter checkpoint/更新版本、tokenizer/chat-template 与 sampler pins均绑定。父模型版本可记录为 parent_checkpoint_identity；它与 B 的 parent_stage_receipt 不混用。
- 沿用 MemAgent 的 GRPO多输出计算，末段必须是真 B末段且含至少一个生成token。现有 rm_scores 放 response 最后位置，须负例测试末尾为工具context时的得分消费；训练链要求 B正常最终assistant回答，不能拿工具结果当最终评分输出。

## 同组 n=4、奖励和质量限制

一个 source/question实例是一个 uid；独立生成四个 memory_chain_id、四个 A 和四个 B，每 sibling的A产物只给自己B。即便文本一样也要保留独立采样请求/身份，不能做内容级去重；反之同一次采样复用identity必须拒绝。

使用 R_B∈{0,1}（或后续显式版本化 rubric）作为完整链终态reward。GRPO只对四个B终态作相对比较，再广播到对应A/B全部生成位置。因此不同段数不会把长链计成更多组样本；但loss按token/序列聚合仍会有长度权重，须记录recipe中的loss_agg_mode，不宣称每链梯度等权或精确因果归因。这是可复用的稀疏终态credit起点，不是已经证明模型学会了记忆。

**已有真实缺口：当前 admit_writer_and_freeze 要求 A reward=1。**第一步工程验证可保持此门，明确它只覆盖“正确A记忆→B回答”的受限闭环，不能证明学会纠正差记忆。如果四个B也全对，则GRPO advantage为0，没有效果证据。

下一独立设计阶段才考虑训练专用门：把A安全/身份/文件格式合格与内容质量分开，允许合法但错误的记忆以R_B=0得到负向credit；仍拒绝越权、未完成、缺回执。**这不是本设计自动授权的现有门放宽**，不得修改或重打分旧eval回执。初始开发/验收先复用严格A门；增加缺事实、更新冲突等训练课程前另版本化训练准入并审阅。

## 取消、重试与消费边界

- A失败/取消：不freeze、不B；B失败/取消：保留A证据但不提前提交A到TQ。任何一条链基础设施异常或不合格，使该strict n=4组失败；合法低分且finished是可训练负例，不能与infra失败混淆。
- phase state必须单调、持久回执含attempt_id。只对owned runner Ray任务/子进程组取消；对GA/GB分别记录finalize/abort结果。无法确认清理则阻塞新阶段，不能宣称资源已释放。
- 组内所有字段预验证后一次batch提交，复用现有strict失败清除逻辑；status=finished只能在完整写入后发布。ReplayBuffer需配置/校验失败组剔除或有界refill；严禁把默认padding计成四条真实成功。已有padding仍用于张量对齐时必须loss_mask=0且不计验收样本。
- 幂等账本以run/partition/uid/sibling/attempt绑定，TQ key映射固定；重试用新attempt和新链，不覆盖旧run，不重放旧A充当本轮新on-policy样本。记录每key被消费的step，防重复进入同轮optimizer；现有TQ存储键并不等于完整exactly-once执行保证。

## 变更与逐步验收（未实施）

1. CPU合同：新增 `uni_agent/framework/memory_chain.py`（拟）、`examples/dsh/capabilities/memory_chain_credit.py`（拟），仅从真实StageOutcome聚合；适度抽取framework单stage helper，不复制整份framework。不改DSH Agent Loop/SDK版本。
2. CPU回归：A/B不同真实session、hash或parent错误、版本缺失/跨版本、越权、不完整B、TQ部分失败、重复attempt、取消后未清理均拒；原单session训练仍通过。
3. 用已有v1 `compute_advantage_for_multi_trajectories` 的小CPU张量例：四条链R=[0,1,0,1]、A/B不同段数；只4个终态参与组统计，同链广播一致、toolcontext mask0、padding0。这只验证数学与接线，不当模型效果证据。
4. 无更新fresh A→B实际模型评估先通过，再单prompt n4/1~2 optimizer steps同步RL：实际版本一致、A/B真实token与TQ交叉一致、fresh chainreceipt、无异常/重复消费、真实非零advantage与有限loss/grad、checkpoint数值变化。
5. 独立reload新进程，留出source_version/事实/问题/chain身份；报告事实保真、写入→新会话检索、干扰/陈旧事实拒绝、任务成功和token/时延。不以压缩更多token为成功指标。训练集两个诊断族不能当heldout能力基准。

本路线复用原生多context与GRPO结构，同时保留两个独立DSH会话的可信边界。无需Modal/Docker、ContextPilot安装、SFT、teacher服务或全异步性能改造作为先决条件。

## 已批准 CPU 合同子任务（不接训练入口）

新增 `examples/dsh/capabilities/memory_credit.py`：可信控制端 `StageOutcome`、`FrozenBinding`、`ChainOutcome` 及 `validate_credit_group(chains, expected_version, expected_group_uid, expected_run_id, expected_partition)`。输入仅允许已通过原单session审计/冻结验证的控制端对象；本模块不从模型字典解析“可信”回执、不替代磁盘hash/回执签发与消费账本。

每组固定四个 sibling；验证A/B独立身份、source/checkpoint/同组实际版本、A成功与B合法终态、parent和冻结hash、不同链不共享会话/冻结身份、Trajectory token-mask-logprob对齐。输出独立 CreditAssignment 记录末B reward、TQ keys与原Trajectory对象引用；**不改变原对象或A回执**。版本由每段Gateway实际min/max字段提供，缺失拒绝。对象返回后不得跨不可信边界再修改；接入阶段仍须在TQ写入前复核。

新增 `tests/uni_agent/examples/test_memory_credit.py` 覆盖合同正负例；`test_memory_credit_grpo.py` 使用固定本地VERL源码中的真实多trajectory函数（不仿写算法）验证四链不同段数、末B奖励广播、工具mask0、顺序重排。源码锁与被测函数哈希记录在测试失败信息中。先运行红测试再实现；此交付不包含执行器、TQ写入、训练、GPU或旧eval门修改。

### CPU 子任务交付结果

合同模块已实现，训练Framework接线仍未实现。新增合同测试先因模块缺失失败；实现后28项合同测试与4项固定VERL数学测试通过，连同原chain/denial回归共89项通过。最后全仓Ruff check/format-check通过。

数学测试的准确范围：本地CPU环境不能直接导入VERL v1包（缺transfer_queue），因此从锁定git tree原样编译两个函数AST，调用真实DataProto/torch/core_algos，另核core GRPO函数AST与锁定源码一致；没有模拟或重写GRPO算法。测试通过record_property记录pin/函数AST哈希。它验证数学函数，不验证完整trainer依赖导入或TQ运行。测试用非末段99分与末段[0,1,0,1]验证末段选择，同时覆盖不同段数、逆序行、标准化开关和工具context mask0。

CreditAssignment只是新的控制端训练注解：保留原Trajectory对象/原stage奖励，输出R_B、keys、FrozenBinding及run/partition/checkpoint；不自动修改训练奖励、不创建chain签发回执。调用方必须先验证真实receipt/文件，再调用此合同，写入TQ前防止对象被改动并复核；取消、重复消费账本、完整stage执行与读写隔离仍属于下一接线阶段。没有把本次CPU测试宣称为训练闭环通过。

## Resident backend 精确接线审计（下一实施批次，设计未实现）

本节按当前源码进一步收敛。单个 `AgentFrameworkRolloutAdapter.create()` 创建resident backend client对应的GatewayManager/FrameworkWorker；四个逻辑sibling各运行A/B，共八个独立Gateway sessions即可。阶段只启动CPU DSH SDK runner，禁止调用 `memory_chain.run_stage` 或 `parallel_infer_verl` 重启模型后端。复用same sampling params与同一个manager，A/B仍通过runtime内部loop处理工具。

### 两个必须先解决的实际兼容缺口

1. **训练split不可借用eval回执。** `memory_verifier.verify` 当前明确只接受 metadata.split=test；`trajectory_audit._validate_partition` 又要求partition=train对应split=train。因此新训练stage必须有独立 verifier入口/ID/bundle，如拟新增 `memory_training_verifier.py`，复用现 `score()` 内容判定、保留unsafe与A质量门，但签发明确train阶段回执及 `credit_assignment=stage-only`；最终chain verifier才签发终态B信用。不可把原test回执改标签后放入train，旧eval门与文件不变。新入口要完整校验env/envelope/fixture/trace身份，不能只包一层score绕过现签发检查。
2. **操作配置不能从sample注入。** `DshArchitectureTaskConfig.task_config_only_fields` 保护 agent/sandbox/workdir/verifier/roots等；TaskConfigResolver明确拒绝sample同名覆盖。Framework控制端应为每stage生成私有YAML，使用 `dataclasses.replace(runner_config, runner_kwargs={...旧参数, task_config_path:私有YAML,...})`。sample侧只给受控任务名/metadata，raw_prompt从stage准备结果派生；不把配置塞进 `tools_kwargs.task`，不放宽Resolver。

### 建议方法与最小抽取点

`uni_agent/framework/framework.py`：把当前 `_run_agent_episode` 的完整单session主体（创建session、Ray/inline runner、finalize、TaskResult注解、postprocess审计、score、日志）移动为内部 `_execute_gateway_stage`，返回值从原tuple提升为内部对象；原 `_run_agent_episode` 保留签名，调用helper并还原原tuple。主要新增接口：

```python
@dataclass(frozen=True)
class GatewayStageExecution:
    session_id: str
    context: dict[str, object]
    task_result: TaskResult
    trajectories: list[Trajectory]  # 原单stage注解+审计后对象
    sample_fields: dict[str, object]
    run_dir: Path | None

async def _execute_gateway_stage(
    self, *, sample_fields, sample_index, session_index, global_steps,
    partition_id, group_size, runner_name, runner_config, sampling_params,
    stage_session_id: str | None = None,
    dump_consumption_crosswalk: bool = True,
) -> GatewayStageExecution: ...
```

`stage_session_id`仅由Framework subclass分配，不能由sample提供。默认None使用原uuid策略，保持原行为。memory预先生成GA/GB，便于B frozen绑定；Gateway create仍由helper唯一负责。原 `_run_agent_episode_with_concurrency_limit` 外层信号量无需移动，memory覆盖 `_run_agent_episode` 即可让每个slot覆盖整条A→B，最多并发4条链，不会无意同时放出8个stage。

新增 `uni_agent/framework/memory_chain.py:NativeMemoryFramework`（名称与CPU合同分开）：

```python
async def _run_agent_episode(self, **原显式关键字参数):
    # 分配chain/GA/GB；operator模板+固定数据prepare A
    # execute A -> 原回执核验 -> freeze实际memory -> prepare B
    # execute B -> 原回执核验 -> 构造ChainOutcome
    # 暂存在此Framework私有按partition/uid/sibling索引的pending表
    # 返回原类型(ordered_trajectories, 原sample_fields)，尚不更改奖励

async def _write_prompt_trajectories_to_tq(
    self, *, uid, session_outcomes, global_steps, partition_id
):
    # 原strict组成功后才进此处；取出完整4个ChainOutcome
    # validate_credit_group -> 签发chain receipt -> 训练注解副本
    # 唯一一次原super()._write_prompt_trajectories_to_tq(...)

async def _run_prompt_rollouts(self, **原显式关键字参数):
    try: return await super()._run_prompt_rollouts(...)
    finally: ...  # 清掉本uid所有pending引用（失败也清），保留磁盘证据
```

这是最小扩展策略：复用原strict组 `failure/status/clear` 和TQ批量逻辑，不复制整份 `_run_prompt_rollouts`；constructor/from_config中强制 strict/finished/verifier/all/GRPO/sync，禁用permissive路径。pending表只存可信内存对象，禁止从sample反序列化ChainOutcome；每stage完成记录身份，异常路径清理并释放引用。group_uid在finally从传入sample_fields提取；不可清其他组。

新版stage准备代码拟 `examples/dsh/capabilities/memory_training_stage.py`：

```python
prepare_writer_stage(*, operator_spec, group_context, chain_id, gateway_session_id) -> StageSpec
freeze_and_prepare_reader(*, writer_execution, operator_spec, reader_gateway_session_id) -> StageSpec
```

StageSpec含私有config path/hash、fixture/hash、raw_prompt、metadata、trace/result根。复用 `writer_fixture/writer_prompt`、`build_memory_patch`、`freeze_memory_artifact/load_memory_artifact`，不要复用依赖CLI inference-evidence/process-exit的 `_stage_result`。resident路径需从TaskResult及stage审计后的磁盘receipt重新核对，而不是伪造inference-evidence文件。A→B相同source版本与实际写文件hash来自A回执；reader role名字在旧fixture为writer/reader，在CPU合同为A/B，显式转换并测试。

task runner可完全保留 `uni_agent.framework.task_runner.run_task`：私有runner_config指向stage YAML；它使用session.base_url覆盖runtime model，且raw_prompt覆盖serialized Task prompt。若设置dsh_trace_root/result_root必须传stage同一组根，否则后置注入会覆盖YAML；不启用通用episode文件复制选项，避免重新复制A私有来源到B。sandbox继续local，限制由closed profile工具policy提供，不能称OS安全沙盒。

### finalize、奖励与审计顺序

阶段helper中按现顺序 `TaskResult返回→Gateway.finalize_session→单stage原奖励→原trajectory_audit`。finalize仅关闭session route，不销毁共享backend。memory任务不安装会重写reward的custom RewardLoopWorker；同stage多个context均保留。stage审计完成后，才读文件freeze或拼合**对象列表**；不修改原token/mask/logprob数组。

组级commit前签发新chainreceipt：原A/B receipt摘要+token摘要+role索引映射+policy版本+FrozenBinding+R_B。训练注解副本使用 `replace(trajectory, reward_score=R_B, ...)`，原stage对象/回执保持原reward。新增 `chain_reward_info`，原 `dsh_reward_info` 应改存 `stage_reward_info`或明确命名嵌套，不能留下“当前reward与原dsh_reward_info矛盾”却假称仍满足单stage审计。新增chain-specific audit校验上述映射；不让老单session postprocessor处理已重注解对象，也不放宽其一致性检查。

现 `_dump_trajectories` 会预生成 `{uid}_{sibling}_{index}` crosswalk；若A/B各stage都从0开始，会出现误导性的重复TQ key。新增helper参数必须让memory阶段日志只标 `stage-evidence/not-consumed`，保留原数组与stage身份；组级注解后统一导出最终index与TQ key。最终TQ arrays摘要与原stage相同才接受，且TQ提交异常走原清除keys逻辑。

### CPU合同字段实查

- Gateway `run_generation` 使用 `[1] * len(response_ids)`，工具context续写用 `[0] * ...`，finalize输出Python `list[int]`，与当前contract `type(x) is int`兼容。不要先经numpy转换（np.int64/bool会被拒），也不要为了通过强制cast可疑mask。
- response_logprobs来自backend output.log_probs，context为0.0；recipe必须calculate_log_probs=True。未请求/缺失不能用teacher值或重算“假采样logprob”补齐。prompt/response IDs由backend/tokenizer链原样列表产生。
- 版本传播源码可达：vllm_async_server初始self.global_steps=None，经set_global_steps更新，generate写extra_fields.global_steps；llm_server.generate将其映射min/max；Gateway记录每次generation mark并finalize为版本跨度。因此**训练backend正确完成update_weights/version设置后有真实版本通路，但源码不能证明每个现存run都取得非None**。standalone inference没有trainer同步钩子时可能缺失，不能拿已成功eval推出能通过credit_contract。
- 现Gateway materialization只汇总min不为None的marks，混合“某次缺版本、其他有版本”可能被遮蔽。接线需新增 `versioned_generation_count/total_generation_count` 或等价complete标记，由Gateway按实际marks输出；chain审计要求全部generation都报告完整int跨度。同组min=max不足以发现部分缺失。默认单session行为不变，memory contract新增完整性字段需同步测试。
- CPU合同StageOutcome只存receipt_sha，没有eligible字段自动来源；构造函数必须从已验证receipt读取eligible/finished/reward、从实际execution读取sessions，不从response文本读取。FrozenBinding content hash可以跨siblings相同（生成相同内容合法），manifest identity不能跨链复用。
- 当前validate_credit_group固定4，仅供train n4。val n1不能直接使用同函数：另独立 `validate_credit_chain` 验证单链身份/版本并直接记录R_B，或明确第一批val也用n4；不能用复制同一链四次凑数量。

### 下一批精确测试与实施顺序

1. helper机械抽取：原Framework全部测试，返回TaskResult/上下文未丢失；Ray timeout/CancelledError仍abort，不多finalize。新增真实mock manager计数：一次framework创建、8次session create/finalize、0次backend重建，A/B地址不同。
2. stage准备CPU：task_config_only_fields不能sample覆盖；A/B独立roots/privateYAML哈希；B工具policy不含A来源；原test verifier拒train、新训练verifier拒test混用；新入口保留unsafe/A质量规则与bundle绑定。
3. 版本完整性：每请求都有v/缺一/全缺/跨v分别通过或拒绝，token masks Pythonint保真；不使用TQ tag fallback作为版本证据。
4. 组级CPU：四条实际不同ChainOutcome才commit；8stage receipts→末B credit；mixed成功/失败/取消整组不写；TQ partial失败清理；pending引用finally清空、其他并发组不受影响；stage evidence无虚假TQ key，finalcrosswalk唯一。
5. CPU真实固定VERL数学测试继续通过；训练副本B credit改变但原stage数组/奖励不变。postprocessor不能绕过chain审计；无生成token的末B拒绝。
6. 单residentbackend fresh run先做n1 A/B无更新dry eval（版本事实记录）；再开启n4 one-step sync，要求实际版本完整、四条B终态有可用reward差异、TQ全部一次消费、非零advantage/参数变化。仍不引入DSH外模型控制loop。

额外取消限制：现 `_cancel_runner_task` force cancel后没有等待确认退出，且异常日志可能只记录后返回；新memory阶段不能因此自动启动B或新尝试。第一批可在取消时将链硬失败、不自动retry，保留owned task清理未确认状态；需要继续调度同资源前补确认等待，而非假称原helper已有完整清理证明。

### 下一阶段奖励信号建议（本轮不改合同）

constraints/updates两个简单诊断可能使所有A/B满分。严格A reward1门下，若四个B同分，GRPO advantage=0：这可作为可执行链路结果，不能作为能力训练或有效参数更新验收；不得人为改分制造梯度。

建议下一独立版本的training admission分两轴：安全/身份/完整性/文件格式必须全通过；语义质量单独计分。合法但遗漏或错误的memory允许冻结，交给B用真实内容回答，并由独立终态测试判R_B=0，以产生有意义负向credit。该设计需同步定义B的不可回答/错误事实奖励与训练数据难度，避免模型靠猜测绕过memory。越权、未完成、混链、损坏格式或不可信回执仍拒绝。旧eval与当前contract继续要求A reward1，不追认旧失败，不把语义错的训练接纳称为安全门放宽。先完成严格版本工程链路，再批准新准入版本及更有区分度的训练/留出任务。

### 实際版本完整性增量（已批准）

修改 `uni_agent/gateway/session/session.py:_build_materialized_trajectory`，从当前buffer保留的generation_versions计算 `generation_count`、`versioned_generation_count`、`version_evidence_complete`。计数单位是实际backend生成请求完成后留下的mark，不是context/prefix token数；rollback已删除的mark不再计，独立context/materialization各自计算。完整mark要求min/max都是非负Python int且min≤max；complete要求至少1次且全部完整。保持原合法min/max跨度行为，缺失不拿调度步数填充。新增字段为Gateway拥有，materialization extra_fields不得覆盖。

修改memory_credit `_trajectory`，严格要求complete=true、两个正整数count一致；仍要求min=max=expected实际版本。默认其他任务不改变准入。测试先验证混合缺失被旧min/max遮蔽的红例，再覆盖全缺失/全同版/跨版/独立context/容量materialization/rollback，明确context追加不新增generation计数；更新既有extra_fields精确字典断言以容纳观测字段。此批不改Framework或TQ。

该增量已实现：4项新增Gateway用例先因字段缺失失败；完成后Gateway完整文件、memory credit和固定GRPO数学测试合计108项CPU通过。额外覆盖容量已满的未发送请求不计数、独立context不互相补齐、rollback删除缺版本旧响应后计数正确。全仓Ruff check/format-check通过。Gateway types文档同步；现有合法min/max行为保留，缺失/非法mark不伪造版本。未运行GPU或调整Framework/TQ。

### 独立训练 stage verifier 增量（已批准）

新增 `examples/dsh/capabilities/memory_training_verifier.py`，ID=dsh-memory-file-chain-training-stage、version=1，独立bundle摘要包含旧memory verifier bundle与新入口源码。新fixture附 `training_stage`（schema=dsh.memory-training-stage.v1、split=train/validation、run_id/group_uid/sibling/checkpoint_identity），与metadata逐项一致；task_id为dsh/memory-training/<chain>/<role>。仅新入口接受train/validation，test一律拒绝；原eval入口不变。

verify完整验证env身份、envelope摘要、fixture摘要、trace与session，再复用原score。输出scope=training-stage、credit_assignment=stage-only（不含跨会话信用）；eligible/finished/unsafe/reward不变。训练身份写入回执extra_info与evidence供控制端审核；训练split和validation split不互换。新CPU测试用真实DshArchitectureTask处理新入口subprocess回执，再接真实trajectory_audit训练/验证partition，agent轨迹明确为合成fixture，不冒充模型运行。负例覆盖旧test回执/fixture身份混用、hash/代码版本/未完成/越权；不改A reward1冻结门或Framework。

此增量已实现，新增13项CPU入口测试，与旧DSH Task/audit及memory chain回归共91项通过；全仓Ruff通过。实际CPU接线路径为合成writer动作→真实DSH Task→真实新verifier子进程→新回执文件→真实trajectory_audit(train/val)，没有伪造verifier stdout。测试还覆盖validation回执不可进train、test被新入口拒绝、fixture split与metadata不一致、进程版本/digest/trace/split篡改、未完成和越权。旧memory_verifier文件未改。

接线注意：DSH Task不把verifier extra_info平铺在TaskResult.extra_info；具体位置为 `result.extra_info['verifier']['extra_info']`，其中含training_stage与credit_assignment。原reward_info.dsh仍承载标准session/receipt身份。元数据中的environment_digest/verifier_id/verifier_version/verifier_code_digest必须显式与operator配置一致；仅在config设置而metadata遗漏，会被独立入口的身份核验拒绝。chain/runtime字段身份来源与回执核验仍由下一控制端完成，本入口不接受仅凭policy版本标签便宣称on-policy。
