<!-- 当前恢复目标以active-engineering-goal.md顶部P1→P2→P3为准；立即执行仍为P1的G0—G6。用户已恢复P1→P2→P3 goal，继续推进。 -->
# Harbor / Modal 工程交接

## 当前推进：修复core-train-r2的CPU资源等待

r1未进入训练：MIG权限误判已由5030662修复。r2真实进入Ray并通过MIG门，但TQ要求8个CPU1 placement槽，新Pod Ray total6/available5，永久pending；没有模型加载、首步或checkpoint。2026-09-10只停止owned PG11802后监督exit-15，elapsed1120.028s，PID11555/11937/13481/13631与专属Ray残留均已消失。证据/workspace/reports/core-train-r2-cpu-admission，含operator-stop，不将generic training-exited当成功。

正在给新core课程固定SimpleStorage.num_data_storage_units=2并TDD；修复发布后新core-train-r3，禁止复用r2。模型/DSH/VERL/任务奖励与16步预算不变。SSH216.243.220.120:13918，48GB MIG，venv已恢复。真实DSH canary8场景passed。当前没有训练作业在运行。

## 新Pod恢复状态（2026-09-10）

SSH `root@216.243.220.120 -p 13918 -i ~/.ssh/id_ed25519`。原workspace模型、代码、venv、checkpoint与归档都在。新Ubuntu22.04系统Python3.11.10，旧venv指向缺失/usr/local/bin/python（原3.12.3）；正恢复固定解释器至/workspace/tools/uv-python，不能盲目用3.11替代。GPU是MIG 2g.48gb（48512MiB），不是原96GB整卡，需CUDA实际分配/前后向检查及显存预算重验，不改宿主MIG。

新版core生成器/路由/canary已完成；680任务资产已保存examples/dsh/data/work-state-memory-core-v1，520train/160公开dev正文无重复，仍四族结构。统一857项CPU通过，Ruff双门通过；真实新Pod canary/GPU尚未运行。初始16步仅诊断，checkpoint保存8/16，原奖励/严格同课程reload不变。先完成环境恢复和固定发布后启动，异步与Harbor后置。

恢复指南gpu-reconnect-runbook.md，下一步pod-recovery-design.md（进行中）。训练目标以active-engineering-goal.md顶部P1→P2→P3为准，不引用旧r1更新代替新课。

## 1. TL;DR

- **位置**：worktree-harbor-modal-integration；主目录main未动。运行源码b47521d，独立审计d4401d3，文档提交以git HEAD为准。
- **新短课程已闭环**：ws-short-train-r1完成8步，8完整组/64唯一A/B、6独立任务。step2/4非零梯度；504 LoRA张量4→8变化，399base不变；零初始化B保存后非零。后四步零梯度，不称新增学习。
- **独立评估通过**：901/902各新进程加载step8，原B奖励1，各1组2唯一消费；母11文件摘要均不变。d4401d3修正validation广播分数审计，原901失败报告保留。
- **尚未完成**：短课程证据归档/HTML与交接收尾完成；四能力、提分对照、结果重复实验、空白环境复建、异步及Harbor仍后续。旧四族r4零更新不追认。
- **GPU**：短课程两评估已exit0；RSI父基线H0已exit0并审计通过；学生提议P已exit0并登记未晋升候选；H1已exit0，2题独立原始审计通过（inspect1/file0），GPU已释放；等待组合比较后再晋升。入口：[短课程指南](../../docs/harbor-modal-integration/work-state-short-course-runbook.md) → [最终reload报告](../../docs/harbor-modal-integration/work-state-short-reload-final-result.md) → active-engineering-goal.md。

当前短课程母checkpoint：`/workspace/uni-agent-g1/checkpoint/ws-short-train-r1/global_step_8`。运行checkout：`/workspace/rebuild/uni-agent-work-state-short-r1`；只读审计checkout：`/workspace/rebuild/uni-agent-short-audit-d4401d3`。二者不可互换源码身份。

云盘归档：`/workspace/reports/ws-short-r1-engineering-evidence-20260909.tar.gz`，SHA256 `d7764c1422ce5a9f89df862a927059224ca5ede201fd2756a40468ef505d8823`；18,197,593字节，173,735成员逐项回读通过。checkpoint单独保留，归档不含凭据。

## 当前优先：短课程独立重复实验 r2

用户明确恢复训练主线；聊天面板需求为误发，不实施。r2已结束：工程复现通过，有效更新未复现（32终态B全部满分、8步零梯度）；两题reload均通过。完整证据见ws-short-repeat-r2-result.md/json。最新优先核心记忆/context能力：WS01交接、WS03索引、WS05事实更新及WS06负例。异步审计已保存但实施暂停，尚未启动异步GPU；准备器无代码修改。先分析已有四族真实失败，复用原base基线入口，再定向补任务与训练。四能力数据方向保存在four-capability-data-plan.md，144条为预算而非已有数据。

- 新实验 `ws-short-train-r2`，执行源码 `f419bbb3d72fd49abc0b37cea94fde699d1c03ac`，远程 checkout `/workspace/rebuild/uni-agent-rsi-compare-f419bbb`；固定 VERL overlay 与 DSH 0.1.3a2、现有 venv。
- prepare/check 已通过；后台 launch PID `328842`，日志 `/root/runs/ws-short-train-r2-launch.log`。这只是已发起，尚未宣称训练完成。
- 数据8训练/2公开开发、8步、n4、同步模式；checkpoint `/workspace/uni-agent-g1/checkpoint/ws-short-train-r2`。首次实验保留。
- [ ] 核实 GPU 模型加载与实际任务消费。
- [ ] 训练终态后核消费组、独立任务数、梯度、参数与 optimizer 变化。
- [ ] 使用 r2 step8 串行独立 reload 901/902，核母文件不变与实际评分。
- [ ] 对照 r1 汇总，归档、commit/push；奖励不必逐项一致，无有效更新不得算复现通过。

## 当前接续：RSI 基线与跨课程初始化审计

短课程收尾之后，继续四能力目标。RSI worker/proposer 原入口仍要求 VERL 完全 clean，与已批准的 finish-reason overlay 冲突；本轮复用严格 overlay 校验并绑定有效来源，不退回未修补版本。准备器/worker/proposal 共用同一来源合同；旧 RSI manifest 必须重建。

下一真实运行是父 H0 的 runtime 能力发现及文件约束取证两个开发任务；入口 `docs/harbor-modal-integration/rsi-parent-baseline-runbook.md`。这是固定权重评估，不是 RSI RL 或候选晋升。207项CPU与Ruff通过，b1c568b已推送；远端 `/workspace/rebuild/uni-agent-rsi-b1c568b` 已固定部署。`/root/runs/rsi-student-h0-r1/prepared/preparation-manifest.json` SHA256=f37d7cb1430c872ea339e3a8b4be76eb488c1337b5af2e0a376939930b113b68；21:38:04(SGT)启动PID316633，operator-launch.json/log在该root。H0已exit0（314.622秒），2题完整唯一消费、原始审计passed，均reward0；结果rsi-student-h0-r1-result.md/json。H0归档42文件逐项通过，见rsi-student-h0-r1-archive.md。P清单 `/root/runs/rsi-student-p-r1-data/preparation-manifest.json` SHA256=8c510da59bcb681cded5cb91e884b65f7d020fcef8c00457610b0f37fb5ee4da；21:48:36启动PID320743，子进程320866。日志 `/root/runs/rsi-student-p-r1-launch.log`，正式run `/root/runs/rsi-student-p-r1`。P已exit0（265.645秒），42真实token、1条TQ消费、原始审计通过；生成增加inspect_list的合法候选，格式reward1。已由原注册器登记候选438ad348…，未晋升，结果rsi-student-p-r1-result.md/json。H1准备 `/root/runs/rsi-student-h1-r1-data/preparation-manifest.json` SHA256=ad62faa9c4c14d7a76da069a0d737fef1f71833d81188bf91712d3d7ed02bb3f；21:59:36发起PID325008，日志 `/root/runs/rsi-student-h1-r1-launch.log`，正式run `/root/runs/rsi-student-h1-r1/H1`，H1已exit0、266.021秒，独立原始审计passed，结果rsi-student-h1-r1-result.md/json；尚未组合比较/晋升。

跨课程审计 `docs/harbor-modal-integration/work-state-curriculum-warm-start-audit.md`：当前 train 禁止 resume，不能用短课程母 checkpoint 冒充旧课程。远程 step8 有 r16/alpha16 的 LoRA metadata，但无现成 PEFT adapter 目录。后续应明确初始化来源、导出等同性、新 optimizer 和 step，而不是放宽 reload 同课程门。

## 2. 本轮交付物

| 路径 | 行数 | 说明 |
| --- | ---: | --- |
| `examples/dsh/capabilities/evaluate_work_state_tasks.py` | 263 | 逐题独立reload、失败隔离、最终汇总 |
| `examples/dsh/capabilities/prepare_memory_training.py` | 663 | after_run只读重验母状态 |
| `tests/uni_agent/examples/test_evaluate_work_state_tasks.py` | 381 | 19项控制器含真实SIGTERM |
| `tests/uni_agent/examples/test_prepare_memory_training.py` | 482 | Linux追加3项after_run |
| `docs/harbor-modal-integration/native-work-state-end-to-end-runbook.md` | 139 | 部署到训练/reload总入口 |
| `docs/harbor-modal-integration/work-state-rl-runbook.md` | 143 | 具体任务命令 |
| `docs/harbor-modal-integration/work-state-independent-evaluation-r1-result.md` | 28 | 四题最终真实结果 |
| `docs/harbor-modal-integration/work-state-independent-evaluation-r1-result.json` | 896 | 原日志/回执/消费证据 |
| `docs/harbor-modal-integration/work-state-independent-evaluation-r1-archive.md` | 20 | 持久化与SHA回读 |
| `docs/harbor-modal-integration/dsh-memory-context-skills-plan.html` | 1 | 专题状态页 |
| `docs/harbor-modal-integration/dsh-memory-context-skills-plan.md` | 360 | 训练任务与验收规格 |
| `docs/harbor-modal-integration/dsh-memory-context-skills-visual-check.md` | 28 | 1440/390真实视觉验收 |

### 较早交付物（历史）

最新第二族记忆及课程交付：`docs/harbor-modal-integration/native-memory-updates-r1-result.md` / `.json`（真实新事实优先A/B、CPU重评分、冻结与云盘归档）；`context-v2-curriculum-r1-execution.md` / `context-v2-curriculum-r1-preparation.json`（12train/4dev、参数透传、清单/源码/跨cwd验证及监督入口）。updates归档 `/workspace/reports/dsh-memory-updates-r1-20260909.tar.gz`，42335字节/51成员，SHA256 d4867f927c416699c885b9da8810b2f6c06fd1fed416001ae30e623441ffcfd4。

最新CPU增量（已推送，当前GPU精确提交以TL;DR为准）：清单驱动推理启动/跨cwd预检/实际VERL pin校验，候选未晋升隔离评估。root联合58项（RSI46+launcher12）通过；context另83项回归通过，Ruff双门通过。RSI默认生产路径及policy源码不变；helper复用已有监督器。

最新memory交付：`docs/harbor-modal-integration/native-memory-writer-r3-result.md`（40行）与 `.json`（540行），真实A/B各两调用/回执、CPU独立重评分、冻结身份与B输入隔离、finalize通过；无训练。归档 `/workspace/reports/dsh-memory-constraints-r3-20260909.tar.gz`（43147字节/51成员，SHA182ba035360c6c7f56fb73763e87fb88ac1ae06fd60a3320c1825ef408256240）。Reader Ray MetricsHead 因 AF_UNIX 路径超过107字节失败，但主线程确认推理仍进入CUDA graph capture；下一新run缩短独占RAY_TMPDIR，不终止当前作业。

最新context独立reload交付（文档与原始证据，无代码改动）：

| 路径（docs/harbor-modal-integration/） | 行数 | 说明 |
| --- | ---: | --- |
| `context-v2-train-r1-reload-report.md` | 43 | 实际加载、无更新、四题fresh消费与效果边界 |
| `context-v2-train-r1-reload-result.json` | 292 | 清单/回执/日志/metrics/源题等同性及摘要 |
| `context-v2-train-r1-reload-archive.json` | 8 | 云盘归档243041字节、523成员、gzip校验通过及SHA256 |

| 本轮文件 | 行数 |
| --- | --- |
| `examples/dsh/capabilities/launch_context_inference.py` | 288 |
| `tests/uni_agent/examples/test_launch_context_inference.py` | 175 |
| `docs/harbor-modal-integration/context-inference-launch-design.md` | 20 |
| `uni_agent/tasks/dsh/rsi_candidates.py` | 386 |
| `examples/dsh/rsi_closed/profile.py` | 117 |
| `tests/uni_agent/tasks/test_dsh_rsi_candidates.py` | 326 |
| `tests/uni_agent/deployment/test_dsh_rsi_policy_canary.py` | 217 |
| `docs/harbor-modal-integration/native-rsi-student-next-stage-design.md` | 172 |


下面为本检查点代码/文档清单（行数用于冷启动定位；历史产物见末尾归档）。

| 路径 | 行数 | 说明 |
| --- | ---: | --- |
| `deployment/checks/harbor_evolution_scripted_smoke.py` | 270 | 实现/部署入口 |
| `deployment/services/harbor_training_supervisor.py` | 209 | 实现/部署入口 |
| `deployment/services/harbor_tunnel.py` | 112 | 实现/部署入口 |
| `docs/harbor-modal-integration/evolution-harbor-wiring-plan.md` | 83 | 设计/证据/手册 |
| `docs/harbor-modal-integration/evolution-lifecycle-harbor-increment-design.md` | 68 | 设计/证据/手册 |
| `docs/harbor-modal-integration/evolution-training-preparation-design.md` | 9 | 设计/证据/手册 |
| `docs/harbor-modal-integration/evolution-v2-policy-failure-admission-design.md` | 73 | 设计/证据/手册 |
| `docs/harbor-modal-integration/harbor-transport-jitter-tolerance.md` | 11 | 设计/证据/手册 |
| `docs/harbor-modal-integration/redact-m1-r1-launch-manifest.json` | 58 | 设计/证据/手册 |
| `docs/harbor-modal-integration/redact-m1-r1-result.json` | 63 | 设计/证据/手册 |
| `docs/harbor-modal-integration/redact-m1-r1-trajectory-audit.json` | 366 | 设计/证据/手册 |
| `docs/harbor-modal-integration/redact-m1-runbook.md` | 119 | 设计/证据/手册 |
| `docs/harbor-modal-integration/ssh-load-probe-20260908.md` | 11 | 设计/证据/手册 |
| `examples/dsh/evolution_verifier_v2.py` | 111 | 实现/部署入口 |
| `examples/dsh/prepare_redact_curriculum_v2.py` | 132 | 实现/部署入口 |
| `examples/harbor/evolution_verifier.py` | 119 | 实现/部署入口 |
| `examples/harbor/prepare_evolution_task.py` | 238 | 实现/部署入口 |
| `examples/harbor/prepare_m2_training.py` | 269 | 实现/部署入口 |
| `tests/uni_agent/deployment/test_harbor_training_supervisor.py` | 244 | 测试 |
| `tests/uni_agent/deployment/test_harbor_tunnel.py` | 109 | 测试 |
| `tests/uni_agent/examples/test_harbor_evolution_scripted_smoke.py` | 109 | 测试 |
| `tests/uni_agent/examples/test_harbor_evolution_verifier.py` | 119 | 测试 |
| `tests/uni_agent/examples/test_harbor_m2_training_entry.py` | 475 | 测试 |
| `tests/uni_agent/examples/test_prepare_evolution_harbor_task.py` | 141 | 测试 |
| `tests/uni_agent/examples/test_prepare_redact_curriculum_v2.py` | 65 | 测试 |
| `tests/uni_agent/tasks/test_dsh_evolution_verifier_v2.py` | 199 | 测试 |
| `tests/uni_agent/tasks/test_harbor_dsh_executor.py` | 465 | 测试 |
| `tests/uni_agent/tasks/test_harbor_dsh_isolated_trial.py` | 541 | 测试 |
| `tests/uni_agent/tasks/test_harbor_dsh_trace_artifacts.py` | 195 | 测试 |
| `tests/uni_agent/tasks/test_harbor_evolution_admission.py` | 131 | 测试 |
| `tests/uni_agent/tasks/test_harbor_evolution_scoring.py` | 157 | 测试 |
| `uni_agent/tasks/harbor_dsh/evolution_scoring.py` | 227 | 实现/部署入口 |
| `uni_agent/tasks/harbor_dsh/executor.py` | 371 | 实现/部署入口 |
| `uni_agent/tasks/harbor_dsh/isolated_trial.py` | 358 | 实现/部署入口 |
| `uni_agent/tasks/harbor_dsh/registration.py` | 283 | 实现/部署入口 |
| `uni_agent/tasks/harbor_dsh/task.py` | 490 | 实现/部署入口 |
| `uni_agent/tasks/harbor_dsh/trace_artifacts.py` | 189 | 实现/部署入口 |
| `uni_agent/tasks/harbor_dsh/trajectory_audit.py` | 230 | 实现/部署入口 |
| `tasks/harbor-modal-integration/active-engineering-goal.md` | 160 | 目标/交接/流程记录 |
| `tasks/harbor-modal-integration/handoff-history-20260908.md` | 473 | 目标/交接/流程记录 |
| `tasks/todo.md` | 361 | 目标/交接/流程记录 |
| `tasks/lessons.md` | 122 | 目标/交接/流程记录 |

本检查点组合回归：635 passed，0 skipped；一个已有Ray弃用警告。Ruff check/format通过。Harbor evolution v1真实Docker四mode已通过，见harbor-evolution-v1-docker-r1-results.json；新v2薄adapter仅CPU通过，尚待worker/packer接线和真实Docker。

## 3. 设计约束

- DSH拥有唯一Agent Loop；Harbor拥有环境生命周期。不得在DSH外再包一层MemAgent执行循环。
- 固定Uni-Agent upstream `89733ec81a69c3cc93ac90479de7ea7f01e51c1f`，VERL `fefb080262e1c015a0ea05f958822a6a512dc795`。
- DSH `b2369692ea530007075ebcd18d39fdba0bbd3982` / 0.1.3a2，runtime SHA `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。完整锁见deployment/versions/g1-deployment-lock.json。
- 镜像摘要、runtime二进制摘要、patch字节摘要、有序patch路径摘要分别绑定，不混为同一身份。
- 旧v1评分与旧产物不修改。v2只修复可信已完成失败的准入：分数仍0，不将失败改为成功；其他hard-veto仍拒绝。
- Harbor当前只支持一个TaskRef；重复train/heldout行是同题工程复验，不是4/2不同任务或隐藏集泛化。
- Harbor已有独立v2薄adapter及Task/audit CPU验证；worker/packer实际链路仍为v1。先验证两者明确版本，不能宣称完全相同准入。
- 不新增付费GPU/Modal/教师API；全异步与规模性能后置。现有GPU作业必须有步数与wall-clock上限。
- 远端源码从GitHub拉取精确commit，不scp源码；运行中不切换checkout。

## 4. 已踩坑与已验证行为

### 当前M1真实结论

`/root/runs/dsh-redact-m1-r1`，supervisor53590已退出，child53591；1065.022秒自然结束exit0。数据4train/2public holdout，从固定Qwen3-4B基座新建LoRA16/16，2global steps，n4，8192/1024预算。

- baseline、step1、step2两条留出均得1；不证明训练提升。
- 两step消费reward均全1，grad_norm/advantages/pg_loss均0；分别evict1和4组。
- checkpoint1/2 SHA均`584f7911bbd4933e328feb122699d041cda67febeab28d4aba42cd1b87b52cac`；504adapter和399base全部未变，delta passed=false。
- trajectory audit：15组，10 eligible-and-consumed，5 rejected，0 unmatched consumption，0 variance groups；总eligible=false，不能报整轮通过。
- 根因样本已inspect但没有define，正常completed且reward0；旧scorer把它记missing_pre_define_inspection→eligiblefalse，整组被淘汰。另有拼错cordis_undefined仍拒绝，v2不放开这一类。
- 没有独立reload：未通过数值门，不浪费GPU去复验未学习checkpoint。
- 证据docs/redact-m1-r1-result.json、redact-m1-r1-trajectory-audit.json；完整路径相对docs/harbor-modal-integration。
- 云盘归档`/workspace/reports/dsh-redact-m1-r1-evidence.tar.gz`，SHA`22088026fd717e232ad9d9b2cc4c59ee76ed42aaa85bb5873de943e8b34659d6`。

### v2修复边界

`evolution_verifier_v2.py`固定两个父源码SHA，自身+父源码组成bundle。新prepare_redact_curriculum_v2.py从原4/2可信manifest发布新task/verifier version2、原prompt保持，生成新task-config.yaml。CPU真实CLI→生产fresh receipt→原trajectory audit已测试；v2-r4正在GPU验证，第一步已有0/1奖励并成功保存；数值及reload待验收。

### Harbor与网络

- 旧T2真实Docker脚本策略4mode均通过，显式双镜像与私有Release回下载hash通过；见t2-harbor-scripted-r2-result.json和t2-image-release-download-verification.json。
- 学生Harbor r1 `/root/runs/t2-harbor-student-r1`在任务开始前SSH超时，supervisor exit -6 /controller-health-failed；无有效评分/更新。控制器已结束。
- 600秒只读SSH探针在592秒复现255退出：末收包至退出约29.793秒，随后新短SSH恢复。不能断言GPU节点持续宕机，也不能把短探针成功等同长连接稳定。
- 当前补丁SSH15秒×6；仅运行期明确传输异常容忍连续90秒，成功清零。认证/身份/格式/healthy=false立即失败；预检失败不启动、无自动重连、不复用旧run。15×6配置600秒探针通过，但该窗口未出现故障，不能证明恢复机制已实测。
- 新Harbor evolution：固定fixture/metadata/原scorer hash与TaskRef；第四个controller-owned binding文件送独立verifier；训练Task与audit重算同小数reward。v1真实容器四mode通过，不代表v2或学生RL已通过。
- 原T2独立verifier是纯stdlib；新evolution复用固定b016父镜像内Pydantic2.12.5（离线实际探针已验证），单独network none，不联网安装。

### 已有SFT证据与边界

原生SFT累计56步，以及4条注册决策补课64步均有LoRA真实更新、冻结base和独立导出加载证据。但两次完整日志工具学生eval均0/2；不宣称SFT已学会完整任务。详见t2-sft-warm-checkpoint-audit.json、t2-sft-registration-state-audit.json、t2-registration-student-eval-r1-result.json。

## 5. 下一里程碑清单

- [x] 固定部署、真实训练消费与checkpoint、独立四题结果收尾、云盘归档。
- [x] 总指南/专题HTML/goal与冷启动记录同步；控制器19项和Linux追加3项通过。
- [ ] W4：补本课程可归因的非零优势、有限非零梯度和参数/optimizer变化；不能引用别的课程更新抵扣。
- [x] 短课程独立实现、217项CPU、8项Linux canary及8步真实训练完成；有效更新已审计，旧r4不追改。
- [x] 完成短课程两题独立reload的新离线审计、证据归档与HTML更新。
- [ ] 后续效果对照、四能力、单卡异步与Harbor另阶段推进，不新增工程前置。

## 6. 分支/部署状态

- 本地分支worktree-harbor-modal-integration；文档提交看git HEAD/origin。当前RSI源码b1c568b，短课程历史运行b47521d与离线审计d4401d3分别保留，不原地更新。远端CI本轮未查询。
- SSH root@216.243.220.178 -p 14465 -i ~/.ssh/id_ed25519；RTX PRO6000。历史作业rsi-student-h1-r1/H1已结束；P的PID320743/320866已终止。H0两进程已终止、supervisor exit0、raw-token审计passed。旧ws-r4-isolated-eval-r1已退出。
- venv /workspace/venvs/uni-agent-rebuild-cf2d3f5；模型/workspace/models/Qwen3-4B-1cfa9a7；DSH0.1.3a2、VERL fefb080+显式补丁。
- 母checkpoint /workspace/uni-agent-g1/checkpoint/work-state-train-r4/global_step_8；四次reload均核11文件不变，无再训练。
- 新证据归档/workspace/reports/work-state-independent-evaluation-r1-20260909.tar.gz，SHA c584f240d2276eb7e9b81bb0dd9553284ec735b150669ece194bbc8fd3a4ce01，12247源成员逐一回读通过。
- 私有运行/root/runs，checkpoint与脱敏证据/workspace；不全局ray stop/pkill，不覆写旧run，不把df集群容量当个人配额。每push前Ruff双门必须通过。

## 7. 冷启动 checklist

1. 读本页 → active-engineering-goal.md → 四题最终报告与零奖励根因，区分旧r4未更新与新短课程有效更新/独立reload已通过。
2. 核本地git status/branch/HEAD/origin；不要复活旧RSI PID；先核新版core课程的部署/作业状态；短课程运行b47521d与离线审计d4401d3保留。复用现venv，不因SSH观察超时重启任务。
3. 读总操作指南与独立短课程设计；后续新run必须新身份、固定新提交、保留母谱系。
4. 启动新GPU任务前只读核占用和版本；使用现prepare/check/launch及原audit，不能伪造TQ或放宽原分数。
5. 完成每节点后更新goal/handoff、Ruff check/format、commit/push。历史只按需看notes.md及handoff-history-20260908.md。
