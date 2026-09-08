# Harbor / Modal 集成交接

## 当前状态覆盖（2026-09-08，优先于下方历史追加记录）

- 当前 worktree/分支：harbor-modal-integration / worktree-harbor-modal-integration；提交身份以 git HEAD 为准，已通过 GitHub 分发。
- Uni-Agent 上游 89733ec + VERL fefb080 已适配；DSH runtime 保持 7840，不随 sibling 仓自动升级。
- M1 v3：两步真实非零梯度更新，504 LoRA 张量变化、399 base 冻结；10/10 组消费审计通过。独立 reload exit0，2/2 组通过；留出 accuracy 仍为0，无能力提升证据。详见 m1-v3-results.md。
- M2：Harbor H0 oracle=1/nop=0，真实 borrowed Docker 环境与 SSH 控制隧道探针通过；DSH BaseAgent bridge 已实现并做接口测试，实际 Harbor 模型训练尚未验收。
- 独立 GitHub checkout cf2d3f5 + 新 venv 安装 exit0，CUDA 前后向通过；复用依赖缓存与既有 DSH wheel，不冒充新机器冷构建或再次完整训练。
- 最新 DSH 审计见 docs/harbor-modal-integration/dsh-session-api-impact-audit.md：converter 本地3e93373修复，聚焦18测试通过；最新HEAD完整构建成功证据不足。ContextPilot仍有旧session.events与lineage条件冲突。
- G1仍active：下一步完成真实 M2 模型通路、训练/reload与总版本固定交付；不新增付费资源。下方为历史快照，旧“未运行/未推送/等待批准”不代表当前状态。

## 1. TL;DR

- 架构规范更新为docs/harbor-modal-integration/uni-agent-system-plan-v2.html；
  engineering-roadmap.html负责执行顺序，index.html只作导航，当前状态仍读本交接。

- 当前优先级：工程贯通 → 任务效果 → 性能与规模。全异步/Modal优化在第三阶段；
  Harness RL/RSI属于第二阶段效果目标。S编号不是严格顺序，先读路线图三阶段说明。

- 2026-09-08 用户确认本 worktree 继续全链路集成；docs/harbor-modal-integration/index.html
  已成为统一方案入口，覆盖 SFT / OPD / RL 与 Harness 演化（方案范围，不代表完成）。

- 用户已确认仓库分工：本仓为训练集成主线，DSH-Exp 负责 DSH 本体与历史研究；
  冷启动先读 [项目长期记忆](../lessons.md) 的 2026-09-08 分工规则。

- worktree：`.Codex/worktrees/harbor-modal-integration`；分支 `worktree-harbor-modal-integration`。
- 基线：父分支已推送的 `41694e2`，保留历史 RL 实现与后续修复。
- 用户 2026-09-08 已允许 git worktree add；工作区与固定 VERL 已初始化。
- H0 oracle 未运行；未部署 Modal / GPU，未调用模型或训练。
- 下一步：隔离环境固定 Harbor / 单 CPU 任务，先 Docker oracle，再分层集成。

## 2. 本轮交付物

| 文件 | 行数 | 说明 |
| --- | ---: | --- |
| `docs/harbor-modal-integration/baseline.md` | 57 | 派生点、历史运行身份、CPA 边界与合同 |
| `docs/harbor-modal-integration/index.html` | 15 | 独立 HTML 入口与继承设计链接 |
| `tasks/harbor-modal-integration/handoff.md` | 66 | 冷启动入口 |
| `tasks/todo.md` | 126 | 当前 worktree 计划；旧任务保留为历史 |
| `README.md` | 123 | 增加当前工作区入口 |

## 3. 设计约束

- VERL 固定 `483b8a009ba3a97563edee3a19887e4862b8094a`，不自动升级。
- Harbor 拥有其环境生命周期；bridge 只复用 exec/file，不重复创建或销毁 sandbox。
- 保留真实 Gateway session、token、fresh receipt 与准入，不伪造训练证据。
- 历史 Qwen3-4B RL 跑过，但不追认 C4 / P5 通过；CPA 只查到 API probe。
- 本目录只推进 Harbor 增量，八类 smoke 保持原验证范围。
- 创建授权不包含付费 Modal、模型 API 或 GPU；新 runtime / 接口设计须先明确。

## 4. 已发现的真实行为

- HarborTask 的 sandbox=None，使用 harbor_env: modal，绕过 Uni-Agent Agent registry。
- agent.name=dsh 不会自动加载 DshAgent，需要 Harbor-compatible bridge。
- endpoint 注入不建立隧道，Modal 内 localhost 不是 Gateway 主机。
- 本仓 Harbor → TaskResult 未映射完整 DSH lineage；strict CLI 限定 dsh_architecture，
  episode staging 限定 local，不能只改配置就声明严格链路已接通。
- Docker 29.2.0 / Linux arm64 可用；全局 Harbor 0.1.45 低于教程要求 0.16.1。
- 旧 DSH source / Linux runtime 仍需恢复；创建 worktree 不代替可复建运行证明。

## 5. 下一里程碑任务清单

- [x] 从精确 41694e2 创建 worktree，初始化固定 VERL，写入交接与 HTML 入口。
- [ ] 固定隔离 Harbor 依赖、单 CPU task / image 身份。
- [ ] H0：Docker oracle 的执行、评分、产物、清理；再单独验证 Modal。
- [ ] H1：细化并实现 DSH bridge 与实际 Gateway 网络。
- [ ] H2：reward / receipt / token / trial / session 严格审计。
- [ ] H3：真实 VERL update 与独立 reload。
- [ ] H4：paired holdout 与后续异步 / Harness 演化。

## 6. 分支 / 部署状态

派生点 41694e2；当前 HEAD 查 git log。初始化文档本地提交，不推送或创建 PR。
未来新 PR 先以 worktree-dsh-v3-live-smoke 为 base；父 Draft PR #2 仍指向 dsh-adapter。
父 worktree 的 31a1849 保持原处，其决定已在本 worktree baseline.md 落盘。
本分支未运行产品测试、oracle、云端任务或训练；208 项 CPU 通过属于父分支历史记录。
初始化验证：HTML 与 baseline 链接通过，390×844 预览无横向溢出；VERL 已解除
对父 worktree 的对象借用并通过 git fsck 连通性检查，固定提交不变。

## 7. 冷启动 checklist

1. 读本文件，再打开 docs/harbor-modal-integration/index.html 和 baseline.md。
2. 核对 git status / HEAD / worktree / VERL；main、dsh-adapter 和旧 clone 不动。
3. 看 tasks/todo.md 当前 worktree 段，继承的 dsh-v3-live-smoke 文档是父分支快照。
4. 先固定 Harbor / task / image 版本，在隔离环境做 H0，不升级全局工具。
5. 保存 H0 原始结果与失败原因；oracle 成功不等于 DSH 或 RL 成功。
6. 付费运行明确范围；push 前必须 ruff check . 与 ruff format --check .。

## 2026-09-08 上游能力核查补充

- 新增 docs/harbor-modal-integration/verl-capabilities.html（HTML 专题）及 verl-six-month-audit.md（时间线与版本证据），index.html 已链接。
- #117 是 Harbor 评估；#128 是 mini-swe-agent 训练；不能合并推断 Harbor RL 已接通。
- 隔离 Harbor 0.16.1 安装于 /private/tmp/harbor-h0-20260908；尚未运行 H0。
- H0 已查明 network_mode=no-network 会启用 egress sidecar；delete 会执行 compose down --rmi local，执行前需限定本任务资源。
- 本轮转入用户要求的上游调研，下一执行步骤仍为 H0，不将调研算作运行验收。

## 4B能力目标与复用审计补充

- 当前目标见 docs/harbor-modal-integration/4b-harness-capability-plan.md；Harness RL为必要范围，Modal为可选环境。
- 导航数据资料已读五份；ContextPilot HTML和规范已读，源hash在contextpilot-source-identity.json，源工作区有未提交修改。
- Uni-Agent已有MemAgent训练recipe；DSH训练adapter拒绝teacher_client，OPD待接入。本轮没有新增运行证据。

## RSI路线补充

- docs/harbor-modal-integration/rsi-plan.html：R0—R5、候选合同、奖励与评估、跨仓实施归属；rsi-source-identity.json保存指定研读报告hash。
- R1技能使用进入近期核心；R2冻结模型独立测Harness改进；R5单独检验改进机制增强。均未实施/训练，不与既有历史RL结果混同。
- 下一具体设计为技能发现/遵循与跨Session记忆两个任务，现有H0执行范围不变。

## 统一工程路线图

- 用户要求形成可复用训练体系：docs/harbor-modal-integration/engineering-roadmap.html为当前权威执行顺序，S0—S11含依赖、验收和产物。index.html已置顶链接。
- 不重新搭历史底座，优先复用；Harness策略RL在S5，候选演化在S9—S11。Modal/OPD不是首个闭环的前置。
- 新session先读路线图与已有能力审计，再执行S0/S1；本轮仅规划，无新增运行。

## 最新上游接线风险（2026-09-08）

- 上游89733ec相对继承6e00d83多5提交，证据见upstream-sync-evidence.json与upstream-adoption-plan.md。
- #109移除reward_info改TaskResult，S2前必须设计严格准入迁移；不直接覆盖本地unfinished整组拒绝。#165在启用SWE-rebench前采纳评估。
- 本轮未merge、未升级VERL、未运行新测试。S0/S1保留当前pin，路线图已加迁移节点。

## 成对版本同步预演

- 用户要求同步最新Uni-Agent及对应VERL并避免冲突。目标89733ec + fefb080，当前VERL483b8a0；相差52提交，不能只看Uni-Agent5提交。
- merge-tree预演8文件冲突，工作区未进入merge。version-sync-design.md与version-sync-preview.json为具体设计与清单；按Human Gate等待设计确认后实施。
- 未checkout新VERL、未跑兼容测试、未push；历史GPU结果不代表新版本通过。

## 系统规划v2交付

- 完整读取旧v1，保留两环境路径与分层设计，新增学习/记忆/RSI、三阶段、成对版本同步状态。
- system-plan-v2-source.json记录原始来源hash；旧worktree未修改。README、首页、路线图与交接已链接v2。
- 本轮仅文档，无代码合并、模型调用或运行状态升级。

## 概念地图补充

- 系统v2 #concepts加入10个实验维度、截图概念对照、OPD两种更新路径及本项目组合。
- 概念按ms-swift官方蒸馏文档校正：学生生成不必然持续on-policy，GKD采样可与OPD重叠；当前DSH OPD仍未实现。
- 本轮仅文档与概念更新，无代码、版本或训练状态变化。

## 可执行任务路线图

- task-roadmap.html细化三阶段15项任务，明确目标/依赖/归属/验收。P1.1—P1.7为工程阶段，勿与历史P0—P6混淆。
- 下一批：P1.1同步设计待确认，P1.2复建预检，P1.3沿用H0授权；没有新的运行或训练证据。

## GPU 已就绪：2026-09-08 最新补充

- 用户已部署服务器；只读SSH确认 RTX PRO 6000 Blackwell Server Edition，97887 MiB，驱动595.91.07。此前“无需购买”不再是当前行动建议。
- 首轮方案：docs/harbor-modal-integration/first-gpu-acceptance.md；候选身份清单：deployment/versions/first-gpu-candidate.json。
- 先工程批次A：基线eval、小步更新、张量数值变化、独立reload、同集留出eval；再逐批DSH/记忆/终端/RSI。
- 本次只读检查，尚未安装或启动训练；候选清单的null项仍阻塞完整版本冻结。

## 能力排期补充

- capability-milestones.html为用户四项能力诉求的排期专题：M1/M2工程→C1 DSH内化→C2记忆及C3受控演化→C4归因→C5性能。
- 不在DSH外新增MemAgent执行循环；现有MemAgent默认8GPU recipe需为当前单卡改配。
- 四类循环身份分别记录；ContextPilot树分支与异步partial rollout不能混同。token压缩不是记忆成功指标。

## 实验正交矩阵与记忆来源

- experiment-matrix.html将八个实验配置维度与系统验收证据分开，链接首页和能力排期。
- 新读DSH-Exp/feat-contextpilot-capability-sft/design.html，来源hash存contextpilot-exp-source.json；不是此前contextpilot仓同名文件。
- 新来源是离线compiler/证据设计，不代表跨会话RL或GPU效果已完成；27B参数规划不直接搬到4B。

## GitHub分发与预检实现

- 用户批准开始工程，并要求GitHub拉取替代scp；分支已推送origin，规划提交bbb8d7e。
- 新增deployment/bootstrap/checkout.sh（固定完整commit与子模块，拒绝覆盖）和checks/preflight.py（只读JSON清点，不冒充运行验收）；3项边界测试通过。
- RunPod代码目标/workspace/src/uni-agent；实际checkout和运行状态按远端检查记录，不跟随main漂移。
- DSH可复建来源找到官方训练worktree的1af5b00，Python文档要求Linux原生构建runtime；尚未恢复旧3b8fad发布物，也未构建新Linuxruntime。

## 原生训练任务审计

- native-recipe-selection.md对比MemAgent/HotpotQA、SWE、Harbor oracle及现有DSH单卡入口。
- 推荐有界E0a原生HotpotQA/MemAgent单卡诊断，M1 DSH与M2 Harbor验收保持不变。
- 原生HotpotQA不返回finished/DSH receipt；separate_async默认8GPU；不能直接套DSH strict或只改GPU_IDS。

## 配对GPU依赖安装

- VERL fefb080自带uv.lock可复用；远端frozen dry-run通过，254包，包含torch2.11+cu130、vLLM0.24、Transformers5.5.3、固定TransferQueue提交。
- /workspace/venvs/uni-agent-fefb080为隔离环境，/workspace/cache/uv为缓存，安装日志/workspace/reports/verl-install.log；仍须检查结束状态。
- 新增bootstrap/install-verl.sh和checks/gpu_smoke.py，安装后必须实际CUDA前后向并验证模块导入。
- GitHub API对DSH-Exp提交1af5b00返回422（不可拉取），DSH发布物仍未解决；不要声称SDK已安装。

## 最新G1已激活与GPU检查通过

- get_goal已确认新版用户目标为active（旧blocked记录不再适用）。
- /workspace/reports/gpu-smoke.json通过CUDA前后向与7个关键模块导入；torch2.11+cu130、vLLM0.24。
- 模型下载固定Qwen/Qwen3-4B@1cfa9a7208912126459214e8b04321603b3df60c，目的路径/workspace/models/Qwen3-4B-1cfa9a7。
- HotpotQA原生数据repo固定27275ff4fee67ac0acb6478e405e7ac07efbdc1a；先小型dev文件用于明确标记的工程诊断，不冒充正式benchmark泛化。
- 下一批实现单卡native smoke配置、固定小批数据、真实采样及update/reload；DSH与Harbor验收尚未通过。
- 模型下载已完成（MODEL_READY）；原生hotpotqa_dev.parquet已下载，128行。含旧模型回答/评分列，现有adapter只读五个必需列，继续保持此隔离。

## 递进与正在运行的诊断

- 用户确认原生训练→DSH记忆/上下文真实轨迹→Harbor长任务→动态Harness/RSI→性能。
- native-train-v1已启动：/workspace/reports/native-train-v1.log，结束码native-train-v1.exit；30分钟timeout，2步上限，先val。未出结果前不可启动重复GPU作业。
- DSH runtime恢复找到更短路径：GitHub可拉取7840bced35ee07ebefbdce0106b56dbc00bdc3ef，与本地1af5b00的python/packages/apps/native/scripts/lock/package无diff；无需发布研究文档即可准备构建。

## DSH源码恢复与Linux构建

- GitHub私有仓库已添加RunPod G1只读Deploy Key（ID162606530），私钥仅在服务器/root/.ssh/dsh_runtime_readonly；不将私钥/PAT写入仓库。
- /workspace/src/dsh-runtime已从GitHub成功拉取并固定7840bced35ee07ebefbdce0106b56dbc00bdc3ef。
- Node24.20.0官方tarball SHA256已核验，pnpm固定11.7.0；RunPod网络盘不允许恢复tar UID/GID，使用--no-same-owner。
- 构建入口deployment/bootstrap/build-dsh-runtime.sh；依赖安装进行中，尚未产生Linux runtime验收。
- 原生训练v1仍在同一进程运行，Actor初始化完成、vLLM加载并完成autotune；当前不重启，不追认更新成功。

## Subagent：DSH最新版本审计完成

- docs/harbor-modal-integration/dsh-latest-audit.md：官方master c389f96/0.1.3-alpha.2；当前7840/0.1.2-alpha.1；最新tag82a5fd6。
- SDK三核心文件AST相同，但新版SessionHandle/flush、日志v1、seq索引/冷读取变化需专门迁移验证。
- ContextPilot远端71ca762确有source/fs/runner实际代码；runner可执行真实三工具file-memory阶段，不只是离线compiler。旧设计HTML是早期快照，不能覆盖最新源码结论。
- 下一步记忆接入优先复用fs+runner及依赖闭包，维持edit/read/write-only独立profile；不能直接混入Cordis完整catalog。当前未升级DSH。
- 原生train-v1实际生成global_step_1文件和validation/0、1；仍需检查更新指标、step2及独立reload，未宣称本次训练验收完成。

## 原生诊断结束 / DSH 安装验收通过

- native-train-v1 退出0，两步完成但组内奖励分别全0/全1，advantage和梯度均0；504个LoRA张量step1→2变化数0，不通过有效更新门。GPU查询无计算进程。
- 退出阶段有DataLoader worker killed日志，cgroup OOM计数0，原因待核验，不将退出0等同无异常。
- DSH官方runtime、0.1.2a1双wheel完成；独立/workspace/venvs/dsh-sdk-7840安装后sdk-minimal与sdk-restart均通过。
- 实际命令/证据：docs/harbor-modal-integration/native-v1-and-dsh-runtime-results.md；摘要已更新deployment/versions/dsh-runtime-candidate.json。
- 下一步将wheel接入GPU训练环境，推进M1真实DSH任务；原生不盲目加步数，独立reload/M1/M2仍未验收。

## M1 部署与运行入口（当前）

- GPU训练venv已--no-deps安装两个DSH 0.1.2a1 wheels，import通过；GPU checkout固定99dc3c7。
- 实际GPU生成/workspace/data/dsh-evolution-v2-7840（16 train/8 holdout），环境摘要绑定当前runtime；Hydra --cfg job通过。
- dsh-m1-v1在启动前被run.log存在检查拒绝，exit2，没有GPU训练。不可关闭防覆盖；外层日志改写reports。
- dsh-m1-v2已提交启动，同一工具session6916；/workspace/reports/dsh-m1-v2.log，/workspace/runs/dsh-m1-v2/exit-code。下一轮先核验进程/日志，不重复启动。
- resolved-launch.json记录版本和环境；2 optimizer steps、前4个trim训练任务、前2个trim留出、n4、并发1、8192+1024上下文、LoRA16、30分钟timeout。启动尚不代表任何验收成功。
- subagent确认v2是最短真实Cordis链路；提供host代码/步骤，所以只证明受指导Harness执行，不证明自主设计或记忆能力。v3live training_eligible=false不可代替。

## Harbor H0 正反例实测

- 本机Docker29.2.0与Harbor0.16.1，固定ubuntu摘要；examples/harbor/h0-file-write任务。oracle=1、nop=0，两项无exception，证据docs/harbor-modal-integration/harbor-h0-results.json。
- 初次地址池耗尽，保留失败trial；独立文件任务network_mode=none解决，不清理其他服务。CLI失败可退出0，必须读TrialResult。
- M1同一dsh-m1-v2仍需查询日志；M2桥接未实现，RunPod远程DOCKER_HOST有挂载路径问题，不能直接配置即用。

## M1 v2 终止：待修指标合同

- exit-code=1：基线validation已输出0.jsonl；VERL trainer_base._val_metrics_update→metric_utils.process_validation_metrics:987 对dict求np_mean失败。未进入训练更新。
- 另有hermes JSON工具解析失败日志，需要后续诊断；不能把metrics修复等同任务成功。
- 下一步审计framework reward_extra_info中的嵌套receipt投影；保留审计数据，只向数值指标聚合提供受支持字段，不改VERL子模块；subagent正只读定位。

## M1 指标投影修复

- framework TaskResult投影仅保留标量指标；完整dsh_reward_info仍保留，VERL子模块不变。
- 新回归先失败后通过；实际调用固定VERL process_validation_metrics；框架/任务423 passed、1 skipped，另增强后的单测1 passed。
- 待推送修复后固定新revision启动dsh-m1-v3；沿用v2任务/预算，不能追认v2通过。

## M1 v3 已启动

- 修复部署dcbd323，旧v2 exit1且GPU无遗留计算进程后才checkout。
- 新run /workspace/runs/dsh-m1-v3，日志/workspace/reports/dsh-m1-v3.log，工具session26309；先查exit-code和真实进程，不重复启动。
- resolved-launch.json更新完整集成SHA，其余任务/预算与v2一致。
- 推送前检查曾因shell未fail-fast漏拦UP038；已补正dcbd323，两项Ruff重新通过。后续check链必须&&并在push前检查每个工具结果，不把末尾diff成功当lint成功。

## 可复用数值验收与 M2 设计

- 3bb1b46已推送；deployment/checks/checkpoint_delta.py在真实native两个checkpoint上运行，504 adapter变化0、399 base变化0，passed=false/exit1符合预期；报告/workspace/reports/native-v1-full-state-delta.json。
- M1 v3仍使用dcbd323，不更新运行中的checkout；最近日志Actor/vLLM加载完成、正在基线采样，需继续核验。
- docs/harbor-modal-integration/harbor-distributed-bridge-design.md为M2具体草案：Mac Harbor/Docker借用环境+RunPod Gateway，SSH控制/模型通路与证据回传；先审查后分批落实，不新增付费资源。

## M1 v3 更新和消费审计通过；reload运行中

- docs/harbor-modal-integration/m1-v3-results.md：exit0，两步非零梯度，504 adapter变化/399 base冻结；10/10轨迹组eligible-and-consumed，无异常消费。
- checkpoint比较工具3bb1b46、审计读取器cf2d3f5；原始run代码dcbd323，未修改训练产物。
- 独立reload已启动：工具28907，/workspace/runs/dsh-m1-v3-reload；日志/workspace/reports/dsh-m1-v3-reload.log。实际pid24470 timeout、24554 python；下一轮先核验，不重复启动。
- Harbor borrowed adapter cf2d3f5已推送，76项相关测试通过；未运行真实DSH Harbor bridge。

## M1 reload通过 / 复建启动 / DSH最新API审计

- reload exit0，明确load step2模型，2/2回执消费审计通过，只有val step2、无actor指标/新checkpoint。
- 实际Harbor borrowed容器测试通过并清理；SSH控制reverse-forward探针通过，模型通路尚未验证。
- 独立复建已启动：工具52307，/workspace/rebuild/uni-agent-cf2d3f5 + /workspace/venvs/uni-agent-rebuild-cf2d3f5；日志/reports/rebuild-cf2d3f5.log（实际完整路径/workspace/reports/），退出码rebuild-cf2d3f5.exit；先查询，不重复启动。
- 用户提醒DSH最新架构入口及旧Session API转换器构建问题；upstream_harbor_verl子代理正在独立只读审计，报告dsh-session-api-impact-audit.md。不升级固定7840。

## M2 容器执行部署通过（2026-09-08）

- bridge已提交推送eb536fb；本轮59相关测试复核通过。
- deployment/harbor/Dockerfile离线安装固定DSH7840双wheel与Pydantic2.12.5；最小8源码来自GitHub eb536fb完整SHA。版本及哈希在deployment/versions/harbor-execution-image.json。
- 镜像9ab3e43d…为linux/amd64，在Mac ARM64仿真；真实keyless SDK启动/关闭与Harbor bridge.setup均通过，测试环境已清理。无模型调用，不是M2训练证据。
- 实际构建上下文/private/tmp/dsh-harbor-image-eb536fb，wheel原件/private/tmp/dsh-harbor-runtime-7840，构建日志/private/tmp/dsh-harbor-image-build.log；镜像只在本机未发布registry。
- 可重跑入口：deployment/checks/keyless_sdk_smoke.py（镜像内）、harbor_dsh_setup_smoke.py（Harbor宿主）；参数见deployment/harbor/README.md。
- 下一步D2完整Gateway模型网络探针，再实现远程Task/结果绑定与M2真实更新/reload。当前GPU无计算进程（本轮查询），M1 v3与reload已结束；勿重复启动旧run。

## M2 模型方向网络已实测（2026-09-08）

- deployment/checks/harbor_model_route_probe.py 可复跑，固定镜像容器经host.docker.internal→Mac loopback SSH→RunPod节点动态端口，完整session path与nonce一致；报告harbor-model-route-result.json。
- 无真实Gateway/模型调用；临时HTTP探针与SSH、Docker进程均已结束，失败探针无训练产物。
- 初次探针readiness空连接让单次handle_request提前结束，已改等真实POST；不是网络限制，无需开放Mac局域网端口。
- 下一实现：有界worker与Task协议、独立Harbor verifier，后续真实学生采样与训练；当前G1仍active。

- 远程协议层uni_agent/tasks/harbor_dsh/protocol.py已实现：严格身份、独立policy、deadline/预算、幂等nonce/session与opaque artifact校验；69新测试+既有task/audit合计94 passed，两项Ruff通过。尚无HTTPworker/Task执行器；policy不能从请求反推，check_replay与ledger写入必须原子。
- Harbor0.16.1 separate verifier默认仍给agent挂载host日志。下一批本仓SingleStepTrial子类覆盖_agent_env_mounts为空，保留verifier mounts，只显式收集/app/answer.txt；注意继承create硬编码返回SingleStepTrial，必须正确工厂实例化。详细只读审计由upstream_harbor_verl落盘harbor-isolated-verifier-audit.md。

## M2 独立评分三例通过

- isolated_trial.py限制固定单文件任务、separate verifier、agent无宿主挂载；正确工厂避免上游create丢失子类。
- 实测v1 Oracle因/logs/agent目录缺失失败；补容器普通目录后v2 oracle=1/nop=0/tamper=0，三例无exception，宿主verifier未变。Docker查询专用agent/verifier均无残留。
- 证据docs/harbor-modal-integration/harbor-isolation-result.json；原始/private/tmp/dsh-harbor-isolation-v2；133项接口/协议/隔离测试通过。
- 下一批：下载前regular-file/size/symlink边界，随后有界worker/Task绑定真实Gateway，M2学生采样与更新/reload。当前未新启动GPU训练。

## M2 任务账本和文件边界

- ledger.py：SQLite持久化请求/状态，原子身份登记、单活动任务、deadline、取消待确认、不可变seal；重启不重跑；实际双线程争用仅一个成功。
- 本轮154相关测试通过。容器内同fd收集器三项真实symlink/directory/oversize精确AnswerArtifactError，未评分/未落host答案；正常v3仍1/0/0，证据harbor-artifact-boundary-result.json和harbor-isolation-v3-result.json。
- 明确剩余边界：当前收集器依赖agent容器内python且exec全量缓冲，尚非敌对进程硬传输限制。子代理unia_capability_audit已接下一批任务：可信宿主docker cp archive流硬限并解析单个普通answer.txt，不extractall。接班先核验agent状态及当前diff，勿覆盖它的代码。
- 后续主线必须实现实际HTTP worker/Harbor executor/Task回传并跑M2模型更新，不能长期停留在边界单测。GPU本轮未启动新训练，G1仍active。

## M2 worker组合回归与DSH再审计（2026-09-08）

- 宿主docker archive有界传输已替代容器Python收集器；真实六例正常1/0/0、异常三例拒绝，证据harbor-host-archive-result.json。不是并发写文件的事务快照。
- executor.py、worker.py、worker_http.py及deployment/services/harbor_worker.py已实现但尚未提交部署；组合198 tests passed，两项Ruff通过。executor测试使用替身，不代表真实学生经过worker。
- HTTP bearer、SQLite幂等与证据回传已测；失败/取消未证明清理时保留unconfirmed，不虚报终态。动态Gateway独立登记、训练Task/receipt、真实M2更新/reload仍待完成。
- 训练侧复用现有Gateway token和TaskResult管线；framework持有group/partition/sample身份但尚未完整传给runner，不能从prompt猜测。无需另建执行循环或修改VERL。
- 最新DSH架构再次由unia_capability_audit独立核对；固定runtime仍7840bced。引用的旧Session converter问题已在3e93373修复，不能把该离线问题推断为现有在线路径失败。最新报告入口：docs/harbor-modal-integration/dsh-latest-architecture-impact-audit.md（代理完成后核验）。
- 用户最新DSH交接：架构入口对应upstream c389f96bf3a9、0.1.3-alpha.2；构建/lint/转换器测试/架构核验/页面检查通过。主进程核实本地HEAD b2369692ea530007075ebcd18d39fdba0bbd3982且工作区干净；未推送为用户报告。此前报告的旧构建失败不能覆盖这次新交接；本仓最新runtime兼容及训练回归仍未运行。

## Session v2 实测与训练接线批次

- 新版DSH源码388tests、built migration worker1test；本仓DSH84tests通过。最新built CLI+SDK boot和官方minimal/restart真实runtime情景通过（本机替身模型，非Linux wheel/GPU训练）。详见dsh-session-v2-test-results.md和dsh-v2-sdk-scenarios.md。
- 用户要求先候选新版验证再继续M2，已更新active-engineering-goal与dsh-session-v2-upgrade-plan.md。当前GitHub API对b236969返回422，已请用户由DSH会话发布；不复制离线converter到本仓。
- build-dsh-runtime.sh默认保留7840，显式DSH_BUILD_REVISION支持b236969；未知SHA/dirty/平台/查询失败均拒绝，18输入测试通过。新版candidate JSON尚无产物hash、not-deployed。
- Framework将7字段_runner_context覆盖样本输入，独立副本防runner修改污染postprocessor；framework目录158tests通过，Ray分支只测CPU提交参数。
- worker取消改为独立executor Task、幂等cancel和shield等待；双取消/HTTP等待方取消/timeout后再取消三个测试先红后绿。最新Harbor+部署组合219tests通过；全仓Ruff check/format通过（195 files）。
- GPU实查仍dcbd323+DSH7840、SDK/runtime均0.1.2a1，无计算进程。尚未部署新版；worker Task/Gateway动态登记/真正M2更新仍待做，G1不能complete。

## 上游冻结与新版远程构建开始

- a524c94提交worker/身份/候选，a6ad775将默认构建目标切到新版，均已推送。用户明确统一0.1.3-alpha.2；旧版仅历史回退，不再默认M2。
- git ls-remote实际确认Uni-Agent main=89733ec、DSH master=c389f96；精确Uni-Agent tree的VERL gitlink=fefb080。本地main d723b5f已包含，dsh-adapter七个独有提交全为docs/tasks，无代码补合需要。新版source lock见deployment/versions/g1-source-lock.json。
- 私有DSH sync-dsh-architecture已实查发布e4a628ed3e，包含固定b236969；之前422/未发布状态已解除。
- 同一SSH工具session31983正在拉取独立/workspace/src/dsh-runtime-b236969；实际git clone pid29996/index-pack30000曾确认存活。完成clone后脚本会checkout b236、拉取/workspace/rebuild/uni-agent-a6ad775，并启动40分钟有界build。先poll同一handle/实际进程，不重复启动。
- 构建日志/workspace/reports/dsh-v2-build.log，退出文件dsh-v2-build.exit，包装脚本dsh-v2-build.sh；clone未结束前这些可能尚不存在。不要将clone运行中记为runtime已构建。
- unia_capability_audit正在实现client.py+客户端测试；保持其修改，后续需要Task/独立Gateway登记与真实训练。upstream_harbor_verl最新真实runner smoke报告已在本地待提交。

## 当前远程流程纠正与客户端完成

- 旧目录出现其他会话fetch PID30106，用户已处理关闭，主进程ps复查其退出。本会话先STOP包装29995，后仅TERM自己的29995/29996/30000，防止废弃流程自动checkout/build。包装已退出；子进程最后仍在退出中，不能直接声称完全清理。旧工具31983最后尚未返回终态，下一轮只核验，不恢复旧构建。
- 唯一后续构建目录改为/workspace/src/dsh-g1-v2-b236969，工具session49380。用已有7840 Git对象本地clone（非hardlink），再从GitHub fetch固定b236969。clone文件100%已完成，后续fetch/checkout/build仍须核验。
- 新构建输出/workspace/reports/dsh-g1-v2-build.log、dsh-g1-v2-build.exit；40分钟截止。旧dsh-v2-build路径废弃，不混用日志；本轮还没有runtime完成证据。
- Harbor Dockerfile/keyless检查/README已改为0.1.3a2；尚未构建新镜像，旧镜像和task摘要暂保留为历史实际状态，不填假摘要。
- 客户端client.py已实现；client+worker/HTTP主进程43tests通过，代理client+协议组合112通过；全仓Ruff通过197files。真实HTTP+SQLite，executor为fake；不冒充学生训练。
- unia_capability_audit现正在实现task.py、独立Harbor receipt绑定及测试，设计harbor-task-binding-design.md；不覆盖其未完成文件。下一步runner/config注册、Gateway独立路由登记、真实M2仍必须实施。
