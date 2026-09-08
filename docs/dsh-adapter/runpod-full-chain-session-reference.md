# RunPod 全链路工程会话参考：本轮成果、当前缺口与接续建议

更新日期：2026-09-08（Asia/Singapore）。
目标会话工作区：`/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/.Codex/worktrees/harbor-modal-integration`。
本文件维护位置：根仓库 `dsh-adapter` 分支的 `docs/dsh-adapter/`；不是对目标会话 active goal 的替换。

## 第一部分：直接执行

### 1. 给接续会话的结论

**继续完成已有 G1：M1 DSH 训练闭环 + M2 Harbor 训练增量 + 可复建交付。当前最有价值的工作，是让真实学生请求、独立评分、训练准入和优化器消费贯穿现有 M2 服务。**

- M1 已有真实更新、消费审计和独立 reload 的新记录，不应继续按早期“reload 待完成”文档重复执行。
- M2 不是从零开始：bridge、隔离评分、协议、持久化账本已提交；worker/executor/HTTP 服务在当前工作区已有实现，但本次读取时尚未提交部署。
- 模型方向 HTTP 探针、oracle 成功、单元测试通过，均不能替代真实 Gateway 学生采样与 M2 训练。
- 当前 G1 沿用固定 Qwen3-4B、DSH `7840bced`、verl `fefb080`；本参考提出的 Qwen3.5/GKD/OPD/记忆专项不自动成为 G1 新前置。
- 先读你工作区最新 handoff、active goal、Git diff 和运行记录；如果与本文件快照不同，重新核验并使用更新的证据。

### 2. 证据优先级与快照

优先级：**当前真实运行/产物与实际代码 → 当前 scoped handoff/结果报告 → active goal 的最新补充 → 本参考 → 历史 HTML/旧计划。** 已完成项应以对应结果为准；不要仅因 active goal 早期清单仍有未勾选项就判定未完成。

| 对象 | 本次读取时点的事实 | 使用边界 |
| --- | --- | --- |
| 目标工作区 HEAD | `bf742c960ae9d35126c125e107e26b151e994074` | 另有正在编辑的源码、测试和文档，HEAD 不包含所有可见文件 |
| 本次已同步 main | `d723b5fbeb382a5094cd634f29455ebe48ef3ffd` | 上一次已验证本地/远端一致；不包含之后所有 M2 提交，不要把 main 当目标会话最新开发树 |
| 官方 Uni-Agent 同步基线 | `89733ec81a69c3cc93ac90479de7ea7f01e51c1f` | 已包含于已同步 main 和集成线；不是本文件再次查询上游实时 HEAD |
| 配对 verl | `fefb080262e1c015a0ea05f958822a6a512dc795` | 保持 Uni-Agent 配对，不独立追逐 verl main |
| M1 实际训练代码 | `dcbd323`；审计工具另有独立 revision | 训练代码、审计代码和最新开发 HEAD 分别记录 |
| 当前训练 DSH | `7840bced35ee07ebefbdce0106b56dbc00bdc3ef`，0.1.2a1 | 已有该 lane 的 runtime/update/reload 证据 |
| 最新 DSH 研究 lane | `b2369692ea530007075ebcd18d39fdba0bbd3982`；Session v2 | 新版源码/兼容测试进展不等于新 Linux 训练 lane 已验收 |
| 本参考的远端观察 | 本轮未 SSH、未启动模型/训练/服务 | 下述 GPU 状态依据目标会话保存的报告，不是本轮独立远端复跑 |

最先读取：

1. [当前工程目标](../../.Codex/worktrees/harbor-modal-integration/tasks/harbor-modal-integration/active-engineering-goal.md)。
2. [目标工作区 handoff](../../.Codex/worktrees/harbor-modal-integration/tasks/harbor-modal-integration/handoff.md)，尤其最后的 M2 worker 与 DSH 再审计段。
3. [M1 更新及 reload 结果](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/m1-v3-results.md)。
4. [当前 worker 部署说明](../../.Codex/worktrees/harbor-modal-integration/deployment/services/README.md)。

### 3. 本条研究会话已经提供了什么

| 交付 | 对当前工程会话的直接帮助 |
| --- | --- |
| [真实代码系统架构 HTML](uni-agent系统架构.html) | DSH/Gateway/Framework/TQ/verl 职责与证据边界；版本较早，不能覆盖你的后续 M2 实现 |
| [Qwen3.5-4B 能力与训练分析](qwen3.5-4b-capability-and-training-analysis.md) | 后续目标模型选型、适配与任务方向；当前工程 Qwen3-4B 不静默替换 |
| [记忆与 Context 专项方案](DSH专家小模型-记忆与Context专项整改方案.html) | MemAgent/ContextPilot 实际能力、12 项整改、SP0—SP7、MiniCPM5-2B 发布对标 |
| [数据层与完整训练路线](DSH数据层与完整训练路线.html) | Task/Attempt/Decision/Memory/Teacher/TrainingUse 身份、SFT/GKD/OPD/RL 分工及长循环数据合同 |
| [main 同步回执](main-sync-result.json) | main 已由 6e00d83 快进至 d723b5f；本地 471 项测试通过，未纳入目标工作区未提交文件 |

main 的 Python 3.11/3.12 CI 后续已经成功，连同 pre-commit、docs、secrets scan 均通过；[CPU CI 回执](https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/actions/runs/34191317299)。`main-sync-result.json` 中先前的 in_progress 是历史查询快照，不能据此判断当前仍未完成；这些 checks 也不替代 bf742c9 或当前 dirty tree 的检查。

上述研究文件位于本机根仓库的 `dsh-adapter`，不一定存在于目标 worktree 或 GitHub main。目标会话可直接读取本文件及其链接；若需远端 GitHub 分发，应择需纳入目标分支，避免整批合并根分支历史而重新引入冲突。

### 4. 当前工程进展：哪些应直接复用

| 环节 | 最新可见证据 | 仍不能推出什么 |
| --- | --- | --- |
| 原生 MemAgent 诊断 | Qwen3-4B 有界两步运行；两组奖励分别全0/全1，梯度0、504个LoRA张量无变化 | 退出0不等于有效学习；不继续无界增加步数 |
| DSH 安装/SDK | 固定7840 Linux runtime、双wheel，独立安装 minimal/restart 通过 | 不自动证明新 Session v2 runtime 或 Harbor 学生链兼容 |
| M1 真实更新 | 两步非零梯度；step1→step2有504个LoRA张量变化、399个base张量冻结；10/10组合格且被消费 | 不冒充初始→最终逐张量比较；不证明能力提升 |
| M1 独立 reload | exit0，明确加载step2，仅val、无新checkpoint；2/2组审计通过 | 两题accuracy仍为0；不能宣布提分 |
| Harbor 运行容器 | 固定amd64镜像、keyless SDK/bridge.setup、borrowed环境实测 | Mac ARM仿真下安装/启动不等于实际学生采样 |
| 模型方向网络 | Docker→Mac loopback SSH→RunPod探针，session path/nonce保持 | 报告明确 actual_gateway_used=false、model_called=false |
| 独立评分/文件边界 | oracle=1、nop=0、tamper=0；异常产物拒绝；宿主archive有界传输已有记录 | 不夸称并发写入时事务快照，或任意任务均受同等保护 |
| Worker服务 | executor/worker/HTTP/bearer/SQLite/产物seal实现可见；组合198项测试报告通过 | 本次读取时未提交部署；替身测试不是实际学生经过worker |

来源：[native/DSH报告](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/native-v1-and-dsh-runtime-results.md)、[M1报告](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/m1-v3-results.md)、[网络探针](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/harbor-model-route-result.json)、[隔离评分](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/harbor-isolation-v3-result.json)、[宿主archive结果](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/harbor-host-archive-result.json)。

### 5. 最短接续路线：先把一条真实 M2 路径做完

以下是基于现有实现的建议顺序，保留当前 G1 范围；不是要求重做已有模块。

#### A. 收拢正在进行的 worker 实现

- [ ] 先核对 agents/其他会话和当前 diff，保留其 worker、executor、isolated_trial 等工作；不要 reset/stash/覆盖。
- [ ] 完成现有 worker/executor/HTTP 的自检并形成固定提交，登记源码、依赖、镜像、任务包、worker配置身份。
- [ ] 使用现有 loopback/bearer/SQLite 服务入口，部署一个有总截止时间的 worker；token 文件在仓库和学生环境之外。
- [ ] 确认服务可接受、查询、取消、seal和返回产物；网络可达只是这一层的验收。

#### B. 绑定真实 Gateway，而不是复用探针地址

- [ ] 从实际 Gateway actor 获取节点 IP、动态端口、model与session信息；由控制端独立登记批准策略，不能从提交的 JobRequest 反推 policy。
- [ ] 把经过验证的SSH通路绑定到实际Gateway；保留精确 `/sessions/{gateway_session_id}/v1` 路径。
- [ ] 由Framework实际拥有者传递 `group_uid / sample_index / partition_id`；不得从prompt猜测、由worker随机补造或混用任务行号。
- [ ] 从Harbor容器发起一个真实学生请求，验证Gateway账本有非空input/generated token、logprob、mask及真实policy版本。

#### C. 补训练侧 Task 与结果回传

- [ ] 复用已有协议的JobRequest、manifest和artifact校验，新增/完成训练侧Task client：提交→有界轮询→必要时取消→取seal结果→校验产物。
- [ ] 对齐 `run_id/group_uid/sample_index/partition_id/job_id/request_sha256/nonce/Gateway session/Harbor trial`；同一个字段全链含义一致。
- [ ] 可信评分来自独立Harbor verifier；校验worker身份、请求绑定、task/verifier版本与原始产物，不把一个哈希或HTTP200单独当可信reward。
- [ ] 将结果接回 typed TaskResult 与现有严格准入；新Harbor证据需要明确验证合同，不把它随意塞进旧DSH receipt字段冒充兼容。
- [ ] 任务合法失败保留reward0；基础设施失败/取消/清理未确认不得装成正常完成。没有证据的失败attempt仍留日志，但训练资格单独判断。
- [ ] 保留完整审计信息，只向数值指标聚合器提供兼容标量，复用M1已修的metrics投影。

代码接续入口（行号随开发变化，以符号为准）：

| 位置 | 当前行为与建议 |
| --- | --- |
| `uni_agent/tasks/harbor_dsh/{executor,worker,worker_http}.py`、`deployment/services/harbor_worker.py` | 已有在途实现，先固定版本，不重写服务 |
| `uni_agent/tasks/harbor_dsh/__init__.py`、`uni_agent/tasks/registry.py` | 尚无新Harbor训练Task注册；旧`tasks/harbor/task.py`是本地CLI评估入口，不能直接视作远程训练入口 |
| `uni_agent/framework/framework.py`、`uni_agent/gateway/manager.py` | 已有真实session创建和路由管理；缺的是远程worker所需的路由生命周期接入，而不是重新实现Gateway注册器 |
| `uni_agent/framework/task_runner.py` | 核查实际runner路径及参数注入，把Framework已有训练group身份传给新Task；不得在worker补造 |
| `uni_agent/tasks/dsh/task.py` | 参考既有typed reward/receipt合同；适配Harbor证据，不照抄旧receipt语义 |
| `uni_agent/framework/framework.py` | 复用Gateway finalize、reward投影及group/session/chain到TQ的绑定；不另建Worker→TQ旁路 |

其中manifest校验只证明协议和产物约束满足，**不等于training eligibility**；必须由训练侧完成准入与真实token绑定。

#### D. 一个小而真实的 M2 训练批次

- [ ] 先实际学生baseline；再生成足够完整的candidate group，确认终奖确有学习信号。
- [ ] 采用当前已验收的Qwen3-4B/verl配置起步，低并发、少量step、完整预算；不把更换Qwen3.5或大teacher变成这一步前置。
- [ ] 保存真实更新、可训练张量变化、base冻结、TQ实际消费crosswalk；发现零方差/零梯度先诊断，不能靠加步数掩盖。
- [ ] 新进程reload明确checkpoint，完成同任务/同预算复评，证明没有回退基座或继续optimizer。
- [ ] 收集容器、隧道、worker与GPU作业的结束证据；未确认清理的job保留unconfirmed，不能直接清账本重试。

#### E. 复建与服务交付

- [ ] 把已通过流程固化为固定GitHub commit的安装/预检/启动/运行/审计/reload/停止入口。
- [ ] 在独立checkout/venv重新运行关键流程，注明复用了哪些缓存、wheel、镜像和宿主服务。
- [ ] 分别报告“可重建”“服务就绪”“真实训练闭环”“效果变化”，不要用一张passed替代全部。

### 6. 目标链路和必须保留的身份

```text
RunPod: Uni-Agent Framework
  ├─ 发布真实Gateway session与独立批准路由
  ├─ 为candidate分配run/group/sample/partition身份
  └─ Harbor训练Task → 已验证控制隧道 → Mac worker
                                      ├─ SQLite任务账本与deadline
                                      ├─ Harbor trial / DSH bridge
                                      │    └─ 容器DSH → 模型隧道 → 实际Gateway → 学生模型
                                      └─ 独立verifier → 有界产物 → sealed manifest

回程：Task校验原始结果 → typed TaskResult → 完整group准入
      → Gateway真实token关联 → TQ实际消费 → verl更新
      → 独立checkpoint reload → 同预算评估 → 全链证据包
```

职责：DSH拥有唯一产品执行循环；Harbor拥有任务容器与独立评分环境；worker负责有界远程执行与产物；Uni-Agent拥有任务/训练编排和准入；verl拥有模型优化。不要在worker再复制Agent循环，或再建一套token账本。

[现有协议源码](../../.Codex/worktrees/harbor-modal-integration/uni_agent/tasks/harbor_dsh/protocol.py) 已定义上述大部分请求字段；优先接通，不重复发明平行协议。

| 身份/事实 | 可信来源 | 拒绝条件示例 |
| --- | --- | --- |
| group/sample/partition | Framework/controller | prompt猜测、跨split、重复sample绑定 |
| Gateway route/session | 实际actor + 独立批准登记 | 仅探针地址、路径被代理改写、过期/错session |
| policy版本/token/logprob | 实际模型生成/Gateway账本 | 只用dataloader step回填冒充真实权重版本 |
| task/verifier/reward | 固定任务包、独立评分、绑定原始产物 | candidate可改评分文件、score伪造、hash或身份不符 |
| 终态/清理 | executor及资源查询的实际证据 | 仅收到cancel ACK即宣布资源已消失 |
| optimizer消费 | TQ/训练审计 | eligible却未消费、消费了未知/不合格轨迹 |

### 7. 把本轮数据设计嵌入接口，不扩大本轮算法范围

现在就需要保留的最小字段：

- Task：任务版本、family/source/split、环境和verifier身份。
- Attempt：run/group/candidate、phase/session、policy版本、预算、终态、准入原因。
- Decision：真实request/event、工具调用与settlement、token span、projection/state引用。
- TrainingUse：TQ key、实际消费step、mask与候选权重，关联原decision。

为后续MemoryArtifact/TeacherSignal留可扩展引用即可，不要求G1先搭完整数据平台。`next_request`允许为空并记录终态原因；只有宣称context编辑影响后续推理时才强制提供真实next-request。

**SFT和RL要分清用途资格。** 历史语义source可重新tokenize用于SFT，但不能伪造on-policy token；SFT纠错应显式屏蔽错误历史目标，RL则保留合法失败动作通过reward/advantage学习。当前verl默认多轮SFT学习全部assistant消息，新增mask字段必须真正被dataset读取。

### 8. G1之后如何衔接目标模型与长循环能力

| 后续方向 | 可复用成果 | 应另行验收的部分 |
| --- | --- | --- |
| Qwen3.5-4B | 当前工程pipeline、verifier、部署和张量审计 | 模型/template/parser、训练配置、实际更新/reload，不能用Qwen3结果替代 |
| DSH SFT | verl现成SFTTrainer与真实DSH语义source | source→目标模型token/mask→release→update；不是再写trainer |
| 学生错态纠正 | 当前真实失败轨迹与环境 | teacher面对学生真实状态给修复动作；改变动作后重新执行，不沿用旧observation |
| GKD / OPD | verl蒸馏基础与teacher manager | Uni-Agent entry当前仍拒绝teacher_client；补评分/词表/prefix/多chain接线 |
| 文件记忆 / A→B | DSH专题ActorFS、fresh Session、CP transfer | 全链同candidate/policy、writer→artifact→reader→outcome，奖励能作用于A |
| Agent long-loop RL | 当前顺序环境执行与可信终奖 | 逐步增加决策跨度、多context、跨Session；动作前fork是CP分支的额外条件 |
| ContextPilot / token critic | 固定上游参考和当前verl组件 | 两种不同credit单独消融，不能混名或同时改变所有机制 |
| MiniCPM对标 | 已有公开结果研究和三轨设计 | 同DSH模型比较、公开Harness迁移、同设备成本；没有实测不得宣称超越 |

GKD与on-policy distillation有重叠；text-only教师可先用于示范/纠错，不能冒充精确token分布蒸馏。G1应先完成真实任务RL，不以新增teacher资源、64卡配方或更换Meshy为前置。

### 9. DSH新版与ContextPilot：避免被旧报告带偏

最新审计已经确认旧Session转换器问题有修复；DSH新lane还有388项源码测试、1项built worker测试、SDK built CLI初始化和84项Uni-Agent适配回归的记录。**不要继续称“最新版DSH整体不可用”，也不要把这些测试升级成新版GPU训练已通过。**

- 当前在线M2固定7840 lane，并不调用TypeScript离线转换器；先完成该lane是合理路径。
- Session v2升级单独固定source/wheel/image，验证真实模型事件、原始trace/hash、receipt、update/reload后再晋升。
- 原始trace字节、迁移后的事件seq、Gateway token位置不是同一种坐标；不重写历史trace后沿用旧receipt。
- ContextPilot三包位于独立DSH专题71ca762，并未随新版DSH主线转换器修复自动合入；snapshotEvents/flush/自定义事件迁移与工具因果seq需要独立适配。

优先来源：[最新架构影响审计](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/dsh-latest-architecture-impact-audit.md)、[Session v2实测结果](../../.Codex/worktrees/harbor-modal-integration/docs/harbor-modal-integration/dsh-session-v2-test-results.md)。这些文件本次读取时部分尚未提交；使用前核查当前diff和最终归档。

### 10. G1最终证据包最小清单

- [ ] resolved run manifest：完整Git/verl/DSH/model/tokenizer/template/镜像/task/verifier版本与预算。
- [ ] 真实运行日志与exit code；失败attempt、重试和取消完整保留。
- [ ] DSH原始trace、Harbor结果、独立verifier产物、manifest/receipt及摘要。
- [ ] Gateway真实token/logprob/mask/policy版本与session映射。
- [ ] group/candidate/decision→TQ→optimizer消费审计。
- [ ] 数值有限、adapter实际变化与base冻结；标明比较的是哪两个checkpoint。
- [ ] 新进程reload证据、无基座回退/无额外optimizer、同预算评估。
- [ ] 清理、deadline与复建说明；停止训练不等于停止云资源计费。

目前用户既有授权范围、GPU预算与停止约定以目标会话为准。本文件不创建资源、开启作业、切换运行中的checkout，也不扩大其授权。

## 第二部分：深度交互

### 11. 我认为最应该避免的三个绕路

**继续扩大边界单测，却不连接真实学生。** 现有隔离、账本与文件边界已经有实质进展；必要问题应修，但接下来每批工作应推动一个真实链路节点。HTTP服务启动后，优先证明“学生生成→独立评分→TaskResult→TQ消费”，而非再次泛化为通用平台。

**把工程目标改成模型能力竞赛。** G1可以在没有显著提分的情况下通过工程验收；目标Qwen3.5的能力专项需独立数据与评测。与此同时，常量奖励/零梯度不能算有效训练工程通过。这两条边界要同时保留。

**因新版本发布同时替换所有组件。** 当前M1已经形成可用基线；M2、Session v2、Qwen3.5、OPD分别有不同风险。一次只改变可归因的层次，保留旧lane和可回退产物，能更快定位真正断点。

### 12. 可直接粘贴给目标会话的启动说明

> 请先读取 `/Users/gumpm5/Documents/Code/xDAN-DSH-uni-agent/docs/dsh-adapter/runpod-full-chain-session-reference.md`，再结合你当前 `tasks/harbor-modal-integration/handoff.md`、`active-engineering-goal.md`、Git diff和远端运行证据继续既有G1。参考文档不覆盖你的最新进度：M1 reload已有通过记录，worker/executor/HTTP已有在途实现，避免重做。优先完成真实Gateway登记、Framework身份到远程Job传递、训练Task/可信结果回传、M2真实更新与独立reload及复建。保持已有资源/预算约束，不把Qwen3.5、OPD、Session v2升级或完整记忆能力变成当前G1新增前置；这些方案用于后续能力阶段。

### 13. 本参考的核验范围

本轮只读了目标工作区的实际源码、未提交文件与最新结果报告，并在根分支生成本MD。没有向其他会话发送控制消息、修改其handoff/goal/源码、SSH远端、调用模型、运行测试或启动服务。测试/GPU数字均明确来自已有报告；执行会话应核验原始文件和最新状态后使用。
