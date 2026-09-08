# Uni-Agent 项目状态回顾与本地交接

逐项验收入口：[三阶段任务路线图](../docs/harbor-modal-integration/task-roadmap.html)。下一批P1.1版本迁移、P1.2环境复建、P1.3Harbor正反例。

用户确认优先级：**第一阶段工程贯通 → 第二阶段任务效果 → 第三阶段性能与规模**。S0—S11为交付物编号，不是严格执行顺序。

当前权威执行顺序：[工程路线图 S0—S11](../docs/harbor-modal-integration/engineering-roadmap.html)。下方旧计划保留阶段来源，冲突时以此路线的依赖与证据范围为准。

仓库职责以 [用户确认的项目记忆](lessons.md) 为准：本仓负责训练集成，DSH-Exp 负责 DSH 本体与历史研究。

当前 worktree：`harbor-modal-integration`。先读 [当前交接](harbor-modal-integration/handoff.md)。
旧章节保留历史；当前计划位于文末 Harbor / Modal 初始化段。

日期：2026-09-06；9 月 7 日追加 CI、GPU 核查与下一里程碑设计。

- [x] 核对当前仓库、分支、HEAD、worktree、工作区及 stash。
- [x] 阅读 DSH official training 最新 handoff、目标、验收标准及 lessons。
- [x] 区分本仓库、DSH worktree 与旧 Uni-Agent clone。
- [x] 对照代码确认已实现能力与未完成的真实运行闸门。
- [x] 复核本机可运行测试，分别记录本次与历史结果。
- [x] 写入 `docs/dsh-adapter/project-status.md` 状态快照。
- [x] 写入 `tasks/dsh-adapter/handoff.md` 冷启动入口及本地经验。
- [x] 在根 README 增加交接、状态和 DSH runbook 入口。
- [x] 检查文档链接、事实、Git diff 和必要门禁，提交文档。

## Review

本次 CPU 子集 82 passed、1 skipped（包含 v3 26 项）；额外两个审计测试文件因
缺 ray/tensordict 无法 collection。实际 CPU matrix 为 24 cases / 16 eligible /
8 passed / 8 rejected。两项 Ruff 门禁通过，157 files already formatted。
首轮文档只同步当前事实与来源；该轮没有执行 GPU 训练、查询控制面或升级历史实验资格。
独立复核通过：P0–P6、执行顺序、来源 revision/哈希与实际分支一致。
文档链接、代码块语法、行数和空白检查通过；后续用户授权 Git 交付，状态见 handoff。

## Git 交付追加

- [x] 提交本项目状态、handoff、lessons、todo 和 README：`104b53d`。
- [x] 通过两项 Ruff 门禁后推送同名 `dsh-adapter`，确认本地与 tracking ref 相等。
- [x] 在自有仓库创建 Draft PR #1（`dsh-adapter → main`），记录完整分支范围与测试限制。
- [x] 在状态快照和交接中记录 PR、首次 CI 查询及 sibling 未同步状态。
- [ ] 完整 PR CI、八类真实 process smoke 与新 C4 run evidence；完成前保持 Draft。

## 下一里程碑：2026-09-07

设计：[CI 修复与八类真实 Gateway smoke](../docs/dsh-adapter/live-smoke-next-milestone-design.md)。

- [x] 恢复交接并创建持续推进全局目标的 goal。
- [x] 查询 RunPod 实时状态：无 Pod、network volume、endpoint，当前每小时支出 0。
- [x] 核查 CLI、GPU 报价、现有模型端点和无模型 DSH runtime 启停。
- [x] 定位 PR 两类 CPU 失败：旧 VERL 的测试替身、Ruff first-party 分类。
- [x] 比较 CPU 直连与现有 Gateway 路径，完成带架构、接口、测试和费用约束的设计。
- [x] 独立复审设计：截止停费优先于导出；明确 Pod 内部同 UID 隔离尚未证明。
- [x] 查询 head `55ed21f` CI 终态，保存失败日志 hash；核对 runtime 来源、备份和官方停费能力。
- [x] 用户“好的 看看怎么继续”后，按已讨论路线推进 CPU 修复与执行器准备；GPU 独立确认。
- [x] 创建临时 CPU venv，复现 RLInsight 3 failed / 1 passed 及 CI Ruff I001；原缺依赖的两个审计文件 20 passed。
- [x] 核清既有产物接口与 inference CLI 最小差异：严格配置、UID 预登记、TQ 读回记录和时间 freshness。
- [x] 用户明确允许手工替代方式，已创建隔离 worktree。
- [x] M0：隔离 worktree 内复现、修复并验证两个 CI 问题；a197ead 已推送，五项 CI 成功。
- [ ] 恢复可重建 DSH source/runtime，明确新 run 的 node/exe 身份与 Linux x64 CPU 构建方式。
- [x] M1 CPU 准备：八条输入、启动命令、持久化证据和审计；不依赖 GPU 购买或旧 checkpoint 恢复。
- [ ] 实际付费运行前单独确认 GPU/模型预算并验证停止机制。
- [ ] M1 有界 GPU：单卡 inference-only smoke，逐 family 验收，导出并按截止时间释放资源。
- [ ] 更新真实结果、handoff、来源及 PR；通过后进入 v3 release。


## 当前 worktree 执行计划：dsh-v3-live-smoke

- [x] 用户明确批准 git worktree add；创建隔离分支并初始化固定 VERL。
- [x] 本 worktree 保存设计与冷启动入口，CPU 基线来自实际失败/通过报告。
- [x] M0：最小修复旧 VERL 测试替身与 Ruff first-party 配置，验证后独立提交 a197ead。
- [x] M1a：冻结八条输入、任务配置与 manifest；CPU 验证 bundle 和字节身份。
- [x] M1b：既有推理 CLI 开启严格校验，预登记 UID 并保存真实 TQ 读回。
- [x] M1c：有界启动/失败收尾和独立证据审计，覆盖 fresh/replay/tamper/缺失等拒绝。
- [x] Review：必要回归、coverage、自查、交接，推送本分支并记录 Draft PR #2。
- [ ] 另行确认真实模型和 GPU，完成八类 process smoke。

### 本 worktree Review

代码提交 `27f7efa` / `3220216`。208 项聚焦 CPU 测试通过，四模块 coverage
87%–99%；独立审计 review 的三项问题均有实际 RED→GREEN 记录。
全量本机尝试 744 passed / 7 failed / 2 skipped，不宣称完整 CI 通过；其中
6 个缺 vLLM/Pillow 失败已在基线复现，localhost 502 去除代理后基线通过。
详见 `docs/dsh-v3-live-smoke/verification.json`。

本分支已推送；Draft PR #2：https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/pull/2 ，base=dsh-adapter，main 未合并。

## Harbor 专题：2026-09-07

范围：用户要求调研、入门科普与独立 HTML 文档；不实现训练适配、不部署或付费运行。

- [x] 阅读用户指定的 Terminal-Bench 教程、Hub 数据集和新闻页五篇正文。
- [x] 对照 Uni-Agent、VERL PR、rLLM 与官方训练示例，区分代码、合并状态与实跑证据。
- [x] 在 `docs/dsh-v3-live-smoke/harbor-agent-rl-guide.html` 汇总角色、长流程、教程和本项目接入路线。
- [x] 从 progress 与 handoff 链接专题；记录本地 eval-only 与上游生态能力的区别。
- [x] 验证 HTML 的桌面/手机显示、内部锚点与本地来源链接；外部来源经调研读取。
- [x] 完成最终 Git diff 检查；专题与交接以独立本地文档提交交付，本轮未推送。

### Harbor 专题 Review

单文件 HTML，无外部字体、脚本与样式；9 个章节、10 个内部锚点、11 条本地文件
链接检查通过。桌面 1440×1000 与手机 390×844 真实浏览器预览，无页面横向溢出。
独立审阅已修正三点：DSH registry / strict CLI 不能直接复用、完整 benchmark
命令不是单任务首跑、Tinker recipe 只证明其具体 Agent / 后端组合可训练。
当前未实现 Harbor bridge、未复跑外部训练 recipe、未增加 smoke 或 GPU 运行结果。

## Uni-Agent 整体方案与 Modal / Harbor：2026-09-07

范围：定位已有总方案，新增本 worktree 的统一 HTML 入口与集成设计，不实现 bridge 或创建云资源。

- [x] 查找本仓与 DSH sibling HTML，区分早期架构、当前状态和 Harbor 专题。
- [x] 核查两条沙箱生命周期、DSH 执行位置与官方 Harbor → Modal 示例。
- [x] 形成 `docs/dsh-v3-live-smoke/uni-agent-system-plan.html`：目标、总体架构、接口、改动范围、验收计划。
- [x] README / progress / Harbor 专题 / handoff 互相链接，保留历史来源与版本边界。
- [x] 检查链接、桌面/手机显示、内容审阅和 Git diff；独立本地提交文档，本轮未推送。

### 整体方案 Review

8 章节、9 内部锚点、24 本地路径（含两条跨仓历史来源）检查通过；Harbor 专题互链有效。
桌面 1440×1000 / 手机 390×844 浏览器预览通过，目录跳转正常、手机无页面横向溢出。
独立代码审阅确认双路径生命周期、Gateway 网络与严格审计缺口；修正评分字段表述，
明确是本仓适配层缺口而非 Harbor 框架限制。本次仅文档验证，不新增云端执行或训练证据。

## 当前 Harbor / Modal worktree：2026-09-08

- [x] 用户允许 git worktree add，从 41694e2 创建 worktree-harbor-modal-integration。
- [x] 初始化固定 VERL；独立 baseline、HTML 入口与 handoff；README 指向当前工作区。
- [x] 检查文档链接与 Git diff，保存初始化本地提交。
- [ ] 固定隔离 Harbor 依赖与单 CPU 任务；Docker oracle → 同任务 Modal oracle。
- [ ] DSH bridge / Gateway / 严格合同 → VERL update / reload → paired holdout。

本次只完成工作区初始化，不把继承测试记录当成本分支实跑。

Review：HTML 5 条本地链接和 baseline 链接检查通过；手机 390×844 实际预览无页面横向溢出。
VERL 已检出固定 pin；复制完整对象并解除父 worktree 借用后，git fsck 连通性检查通过。

### 2026-09-08 上游专题核查
- [x] 查阅 VERL 多轮/沙盒/全异步源码与 Context7 官方文档。
- [x] 核查近六个月相关 PR 的 merged 状态及本地祖先关系，保存专题 HTML 与时间线。
- [ ] 继续 H0 单任务 Docker 正反例运行及资源清理验收。

Review：本次只交付文档，未执行训练；Harbor runtime、任务格式与 Modal 服务已分开标记。

### 2026-09-08 项目记忆固化

- [x] 将用户确认的跨仓分工写入 tasks/lessons.md，并连接 README、当前 handoff 与计划入口。
- Review：仅修改本 worktree 文档，DSH 侧已有未提交交接保持原样；检查链接与 diff，不涉及运行结果变化。

### 2026-09-08 统一全链路方案

- [x] index.html 升级为当前权威总览，整合模型学习、教师辅助、云端执行与 Harness 演化。
- [ ] 恢复可复建 DSH runtime 并完成原八类真实执行验收。
- [ ] 完成 H0 → DSH / Gateway → 可信训练轨迹 → 更新 / reload → 独立评估。
- [ ] 按基线缺口细化 SFT / OPD 接口与数据设计，单独验证教师信号和成本。
- [ ] 完成 Modal 同任务迁移，再扩全异步与 Harness 候选验收、晋升和回滚。

Review：本轮总览补全，不升级任何运行状态；付费云端、模型调用范围沿用既有边界。

### 4B能力审计与资料复用

- [x] 并行审计Uni-Agent、读取导航五份数据设计及ContextPilot规范，归档来源与边界。
- [x] 总览明确Harness RL必要、Modal可选、MemAgent可复用、OPD接口未接通。
- [ ] 下一步为DSH可复建环境与Harbor单任务验证；继而细化学生Harness动作和跨Session评估合同。

Review：HTML本地链接与diff检查通过；未复跑源码测试、模型、GPU或上游报告成绩。

### RSI专题规划

- [x] 完整读取指定研读报告，保存来源hash并补R0—R5 HTML。
- [x] 明确archive/parent/deploy资格、三层split、独立reload/rollback与2×2归因。
- [ ] 逐批冻结实际DSH工具映射、候选API/文件清单和运行测试后实施。

Review：仅新增设计与来源索引，验证HTML链接及diff；未执行论文代码、模型或训练。

### 可复用工程训练体系

- [x] 汇总S0—S11、依赖、验收与可复用资产；链接总览。
- [ ] S0/S1复建和单任务执行证据。
- [ ] S2/S3合同和基线 → 按需S4 → S5更新与独立评估。
- [ ] 分支推进S6 OPD、S7记忆、S8异步、S9—S11 RSI与复用发布。

### 实现基线与上游同步

- [x] 对比最新89733ec与继承6e00d83，保存5提交差异和采用策略。
- [ ] S2前设计#109 TaskResult迁移并保留DSH严格准入，测试旧/新证据schema。
- [ ] 启用SWE-rebench前评估#165防泄漏修复。

Review：只读API/源码核查并更新文档，无依赖升级或功能测试结果。

### 成对版本同步

- [x] fetch目标对象、核验上游gitlink、merge-tree预演。
- [x] 写8冲突文件、52提交VERL差异、迁移合同与测试设计。
- [x] 用户确认同步设计；已迁移配对 pin 和 typed TaskResult，CPU 回归通过。Linux/vLLM/GPU 验证仍待完成。

### 三阶段主线统一

- [x] 同步路线图、总览、长期记忆和handoff，区分工程/效果/性能验收。
- Review：本轮仅文档调整，无版本合并、训练或部署。

### 系统规划v2

- [x] 对照v1整合模块架构、接口与三阶段，保留来源hash。
- [x] 首页改为导航，系统规划/路线图/交接分工明确；更新README。
- [ ] 按版本同步设计继续工程实施，文档不替代运行验收。

### 学习概念维度

- [x] 将用户截图概念补入v2，区分目标/采样/来源/场景/Harness/参数/工具/环境/调度与评估。
- [x] 核对官方蒸馏文档，明确GKD/OPD关系与本仓接口边界。

### 任务与目标清单

- [x] 将三阶段细化为15项任务，标明依赖、归属、验收与状态；不替换历史P0—P6资格。
- [ ] 按任务清单产生新运行证据，再更新状态。

### 安装部署入口

- [x] 创建 deployment/README.md 与部署设计，明确复用现有 ops。
- [ ] 实现版本清单与只读预检，恢复 DSH 发布物。
- [ ] 实现 Linux 隔离安装与必要服务启动/健康检查。
- [ ] Docker oracle → 真实 DSH episode → GPU update/reload → 干净环境复建。

Review：本批只新增部署目录与设计；不将其标记为安装或部署完成。

### 四项能力里程碑排期

- [x] 对照RSI研读、研究索引及Harbor指南，落盘capability-milestones.html并链接首页。
- [ ] M1/M2工程验收后，先C1 DSH策略内化；并行准备C2记忆任务与C3a候选实验。
- [ ] C2/C3b完成后做C4权重×Harness归因，再按瓶颈推进C5性能规模。
- Review：本轮为规划；四种循环身份与跨会话奖励为待实现合同，无新增训练证据。

### 实验配置与证据矩阵

- [x] 新增八维配置矩阵、E0—E5实验顺序、不可用组合与独立验收状态。
- [x] 核读新增ContextPilot路径并保存hash与适用边界。
- [ ] 将首批实际任务实例、模型revision、数据split与阈值填入可执行实验配置。

### GPU环境实施

- [x] RunPod从GitHub拉取9b7dbdb与VERL fefb080；只读预检完成。
- [x] 固定VERL自带uv.lock的FSDP/vLLM安装预演通过（254包）；开始隔离安装。
- [ ] 安装完成后验证CUDA运算、GPU依赖导入和原生小任务。
- [ ] 固定模型与数据；DSH runtime构建和Harbor容器环境仍待实施。

### 本次真实运行核验

- [x] 原生两步采样/评分/checkpoint及504个LoRA张量差异审计。
- [x] DSH Linux runtime、官方wheels、安装后minimal/restart keyless smoke。
- [x] M1真实DSH奖励与有效更新、独立reload（v3；详见m1-v3-results.md，未证明提分）。
- Review：原生梯度零，不能记为有效更新；M2与整体G1仍未完成。

### Harbor M2 执行环境增量（2026-09-08）

- [x] BaseAgent bridge 与 borrowed adapter；相关59项复核通过，eb536fb已推送。
- [x] 固定amd64 Python镜像实际仿真启动；DSH wheel校验与GitHub固定源下载。
- [x] 离线构建DSH执行镜像，真实SDK initialize/shutdown与Harbor setup。
- [ ] Docker到Gateway模型网络、任务结果绑定与真实VERL更新/reload。
- Review：当前先验证部署兼容性；网络控制探针与SDK boot都不能代替M2模型训练。

### M2 远程任务接线

- [x] Docker→Mac loopback SSH→RunPod节点动态端口；完整session path与nonce实测一致。
- [x] 纯请求/产物合同及幂等边界测试；含DSH task/trajectory回归94 passed。
- [ ] 无agent宿主挂载的独立verifier Trial，oracle/篡改实测。
- [ ] 有界worker与Task接线、真实Gateway学生采样、更新/reload。
- Review：探针不启动模型；独立verifier默认日志挂载需专门适配，不能仅凭separate配置宣布隔离。

### M2 独立评分实测

- [x] 固定单文件task与独立无网络verifier；agent镜像保持已验证DSH。
- [x] 真实oracle/nop/评分伪造三例及无host mounts、清理验证（v2，1/0/0）。
- [ ] artifact类型/符号链接/大小在下载前受限，绑定到worker准入。
- Review：首轮oracle因移除mount后/logs/agent目录缺失而exit1，得到0分；不得将无exception视作oracle成功。适配器补普通容器目录后以新run复验。

### M2 worker执行状态

- [x] SQLite持久账本与原子请求登记、单任务领取、取消待确认、不可变seal；7项测试，连同协议76通过。
- [x] 单文件同fd读取与真实容器异常产物拒绝；宿主硬限传输仍待替换。
- [ ] HTTP worker + Harbor executor + Task回传与现有receipt准入。
- Review：账本重启不重跑旧任务；它不代替实际进程清理或训练消费证据。

### M2 宿主传输与worker接线

- [x] 宿主Docker archive增量硬限；真实六例复验通过，正常1/0/0，异常三项拒绝无评分。
- [x] executor证据/清理合同、worker/HTTP组合回归：198 passed；尚未运行真实学生executor任务。
- [ ] Gateway动态端口登记/隧道，训练侧Task与receipt绑定；M2真实训练/reload。
- Review：不依赖agent容器Python读取；不解包归档路径。当前HTTP已编写，尚未部署真实模型任务。

### 最新 DSH 架构兼容性复核

- [x] 确认当前训练 pin 仍为7840bced，runner读取Python SDK result.events，不调用离线TypeScript converter。
- [x] 独立subagent核对最新架构入口、Session v2与converter修复、ContextPilot事件坐标兼容性；报告已落盘。
- [x] Session/转换器388项、built migration worker 1项、本仓DSH回归84项通过；最新built CLI SDK boot通过。
- [ ] 新版SDK完整事件/restart、Linux候选部署及真实训练准入；随后继续M2。
- Review：新版源码审计与固定版本训练验收分开；未通过候选版本回归前不替换现有runtime。

### G1 新版统一部署增量（2026-09-08，取代上面的候选未发布状态）

- [x] Uni-Agent/VERL/DSH 固定源代码核验并记录 g1-source-lock。
- [x] DSH 0.1.3a2 Linux 官方 wheel 构建、独立安装、minimal/restart 验收。
- [x] Harbor Task/receipt、真实 Session Gateway 注册、独立 token 审计接线；主进程组合 110 passed。
- [x] 真实 SSH 控制面登记和双向转发检查，结束后端口/进程清理；未调用模型。
- [ ] 新版 Harbor 镜像 boot/setup 后更新任务摘要。
- [ ] 新版训练环境回归与固定 M2 运行配置。
- [ ] 真实学生 → DSH → Harbor verifier → Gateway token → VERL 更新。
- [ ] 独立 reload、留出评估、可复建交付与最终完整版本清单。
- Review：原生任务/M1 的历史证据不冒称新版 M2；环境兼容和数值更新分别验收。

## G1 新Pod隧道恢复（2026-09-08）
- [x] 独立双向HTTP持续探针与清理。
- [x] controller认证只读健康接口及异常退出证据。
- [x] run-owned GPU监督健康检查，固定新run重试（r5已启动，训练验收仍待完成）。
- [ ] 真正训练更新与reload验收（不可用连接测试替代）。

## 有价值任务基线（用户最新要求）
- [x] 收尾r6：全同奖励、零动量、评估超时，不能算有效RL更新。
- [x] 明确不把trim称为上下文管理；不再重复文件写入RL。
- [ ] 新版DSH真实Tool能力查询baseline，去除调用步骤答案。
- [ ] 补强故障恢复评分中的顺序/同Plugin/清理约束后再运行。
- [ ] 建立事实保真与A写入→B检索任务合同，再做记忆能力训练。

## 当前有价值任务闭环：T2 优先

- [x] T1 无答案提示基线执行并定位失败：错误查询导致容量耗尽，未通过完整评估。
- [x] T2 独立日志 oracle 与 4 train / 2 public dev fixture；主代理复核 10 项测试通过。
- [ ] 固定 T2 真实 DSH API 合同并通过脚本策略 runtime smoke（不冒充模型轨迹）。
- [ ] 严格生命周期 verifier 与负例测试；数据/配置/评分接入既有 DSH Task。
- [ ] T2 学生 baseline，按成功探索情况选择补 SFT 示范或进入有界 RL。
- [ ] 非零有限梯度、LoRA 数值变化、独立 reload、同预算留出评估。
- [ ] Harbor + Docker 对应任务增量与可复建复验。

Review：G1 尚未完成；全异步、Modal 和扩容延后。训练策略见 docs/harbor-modal-integration/dsh-capability-training-strategy.md。
