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
