# Harbor / Modal 集成交接

## 当前状态覆盖（2026-09-08，优先于下方历史追加记录）

- 用户已批准工程集成；Uni-Agent 89733ec 与配对 VERL fefb080 已进入本地迁移，替代旧 pin。
- #109 使用 typed TaskResult；DSH 严格回执、整组准入、后处理防篡改与旧 dump 审计投影保留。
- 回归：framework/tasks 422 passed、1 skipped（Linux /proc）；Gateway session/RLInsight 70 passed。
- 另一次 parser 组合测试因本机缺少 vLLM 有 4 项失败，不计为通过；Linux GPU 验证仍待完成。
- deployment/README.md 与 deployment-design.md 已落地；安装器/服务组合尚未实现。
- 下一步：提交迁移、版本预检、恢复 DSH 发布物、Linux 安装与 Docker oracle，再真实 GPU update/reload。
- 未购买 GPU、未启动新训练、未推送本分支；下方“未merge/等待批准/固定483b8a0”为历史快照。


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
