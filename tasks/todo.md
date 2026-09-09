# Uni-Agent 项目状态回顾与本地交接

最新权威目标：[原生四能力 Goal](harbor-modal-integration/active-engineering-goal.md)。Harbor 后置，以下旧路线仅作历史记录。

## 2026-09-09 当前执行计划：有价值的工作状态任务 × 原生 RL 验收

最新：r4于14:18:35 UTC+8启动，固定5b4b01b，54项recipe+audit回归通过；新run尚未验收。下文r4未启动为此前记录，当前进度见work-state-train-r4-execution.md。

唯一当前顺序以权威goal的W0—W6为准；下面旧S/P/N历史段的“当前/下一步”不覆盖本节。

用户最新纠偏：先完成工程执行、真实消费、保存及独立reload，再补有效更新证据，最后看任务成功率/奖励改善。r3已因周期评估安全拒绝退出，r4尚未启动；合法全零不主动停止，不继续用复杂任务优化阻塞整条流程。W4仍需真实非零梯度与参数证据，不能用zero-grad exit0替代。

- [x] 核对既有goal状态、设计、handoff、实际代码与证据边界。
- [x] 更新goal：双目标、W0—W6退出条件、长期四能力与当前工程工作包分开。
- [x] W1 任务/冻结/权限/verifier/框架回归与真实DSH canary：8种结构/106次工具请求通过，见work-state-runtime-canary-r1-result.md。
- [ ] W2 四族数据清单与真实学生基线。
- [ ] W3 同策略完整组的真实在线RL消费审计。
- [ ] W4 本课程有效梯度、参数/optimizer与checkpoint审计。
- [ ] W5 本课程checkpoint独立reload和新鲜任务结果复跑。
- [ ] W6 手动脚本/指南/证据/交接与逐节点commit/push。

本次goal Review：沿用已批准设计；能力提分不是工程退出前置，CPU通过也不计GPU验收。平台仍usageLimited，未虚报激活或完成。当前protocol3/VERL结束语义补丁已17b6e55推送；r2/r3失败保留，r3 step4周期val WS06 A越权拒绝，未完成8步。r4尚未启动，调度修复已通过27项recipe回归，待主线程提交/推送并固定版本。有效梯度和reload仍待实证。

- [x] 修复并锁定length/stop保真补丁，Gateway截断不执行工具、terminal abort失败；固定Linuxruntime四项canary和既有vLLM环境30项测试通过。
- [x] 修复公开业务schema与空目录create/聊天不跨会话说明，独立40实例对照确认源事实/truth不变。
- [x] 归档r3 failed：原supervisor/WS06 A越权trace/receipt、step1–3零梯度及step4 checkpoint库存；不追认有效学习。
- [x] 实现并测试work-state train关闭val_before_train/test_freq=0，保留8steps/n4/save4/8；27项recipe回归通过，独立val/reload严格门不变。
- [ ] 固定新提交与r4 manifest，核复合VERL身份与已发布DSH0.1.3a2 runtime；不重建现有SDK环境。
- [ ] r4新run完成工程步数、真实完整消费、保存与独立reload；当前尚未启动。
- [ ] 单独验收有效梯度/优势/参数与optimizer，再评能力效果；工程exit0与checkpoint存在不自动通过本项。

历史逐项验收入口：[三阶段任务路线图](../docs/harbor-modal-integration/task-roadmap.html)。其版本迁移、环境复建、Harbor顺序不再是当前执行优先级。

用户确认优先级：**第一阶段工程贯通 → 第二阶段任务效果 → 第三阶段性能与规模**。S0—S11为交付物编号，不是严格执行顺序。

历史工程路线：[工程路线图 S0—S11](../docs/harbor-modal-integration/engineering-roadmap.html)。下方旧计划保留阶段来源，冲突时以当前active-engineering-goal.md为准。

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
- [x] 固定 T2 真实 DSH API 合同并通过GPU固定wheel脚本策略 runtime smoke（不冒充模型轨迹）。
- [x] 严格生命周期 verifier 与负例测试；数据/配置/评分接入既有 DSH Task。
- [x] T2 学生 baseline 完整exit0/fresh reward0，选择真实业务示范SFT暖启动。
- [ ] 逐决策SFT转换、真实tokenizer/mask、原生VERL单步LoRA与独立导出/加载。
- [ ] 非零有限梯度、LoRA 数值变化、独立 reload、同预算留出评估。
- [ ] Harbor + Docker 对应任务增量与可复建复验。

Review：G1 尚未完成；全异步、Modal 和扩容延后。训练策略见 docs/harbor-modal-integration/dsh-capability-training-strategy.md。

## 当前 G1：T2 示范暖启动 → 学生在线 RL → Harbor 同任务

- [x] 固定新版DSH runtime，6公开case/18实际业务调用通过。
- [x] 真实请求/事件生成56训练与28开发决策，tokenizer/mask逐项验证。
- [x] 原生SFT累计56步，504 LoRA数值更新、399基座不变、optimizer step56。
- [x] 原生merger导出adapter；step1独立CPU加载匹配。
- [x] step56独立学生任务评估：exit0，公开dev 0/2；保留失败证据。
- [ ] 有差异奖励的新版DSH在线RL真实更新与独立reload。
- [x] T2 Harbor隔离评分、训练侧业务复验CPU回归及4真实Docker正反例。
- [ ] 注册决策补课64步与后续独立学生评估。
- [ ] 学生→Gateway→Harbor→训练侧的真实准入验收。
- [ ] 新留出案例、可复建版本清单与最终G1交付。

Review：SFT参数审计不等同于在线RL打通；开发loss下降不等于任务效果或留出泛化。

## G1 当前推进：新版 DSH 执行课程与 Harbor 诊断

- [x] 原样筛选邮箱脱敏4/2课程，10项测试，GitHub74b253b，GPU源码拉取并核验。
- [x] Harbor r1启动期SSH失败归档，GPU退出，无有效任务评分。
- [x] 失败诊断增强：SSH退出码、HTTP异常类型/时间，39项测试；超时策略未改。
- [x] M1 r1两步数值/消费审计已执行但失败：0grad、LoRA不变、5组拒绝；v2新run仍待验收。
- [ ] 独立reload与同条件公开holdout评估。
- [ ] Harbor新run真实学生闭环，再验收M2更新。

Review：SFT数值更新通过但任务0/2；Harbor脚本策略四例通过不等于学生RL通过。

检查点review：611项组合CPU回归通过（包含新增smoke，无skip），M1真实零更新结果和SSH复现已归档；当前以handoff.md与active-engineering-goal.md为准。

## G1 检查点：Harbor v2准入与持久存储

- [x] Harbor v2薄adapter及Task/audit CPU实现，635项相关回归通过；Ruff双门通过。
- [x] 新增验收追踪MD，记录500 GB云盘与标准checkpoint目录。
- [x] r4第一步真实0/1奖励和checkpoint云盘保存成功。
- [ ] 第二步数值/消费审计、独立reload和留出评估。
- [ ] Harbor v2 worker/packer接线与真实学生M2。

Review：本提交为进行中检查点；不将first checkpoint或CPU通过当成G1完成。

- [x] 独立数据会话委托落盘：tasks/harbor-modal-integration/data-curriculum-session-brief.md。
- [ ] 另会话完成D0设计并获批后实施数据pilot；不阻塞G1主线。

- [x] M1独立reload最终审计2/2通过、无再训练，证据归档云盘。
- [x] Harbor v2执行/打包/训练准备接线；668项组合CPU测试通过。
- [ ] 固定提交部署GPU打包，在Mac真实Docker执行v2正反例；再M2学生训练。

## M2 失败恢复检查点
- [x] 查明 max-tokens 后 cleanup 状态丢失与重复提交根因。
- [x] 修复可信清理终态和 ledger 忙碌拒绝；685 项回归通过。
- [ ] 真实 Docker 截断任务拒绝后下一正常任务可执行。
- [ ] 新身份 M2 同步训练、参数更新与独立 reload。
- [ ] 同步通过后单卡 colocate_async 有界对照。

## 2026-09-09 原生优先重设计（覆盖旧M2下一步）
- [x] 回顾dsh-v3-live-smoke原系统方案并记录来源摘要。
- [x] 输出系统v3、四能力合同、N0—N5/P1与新的active goal。
- [ ] 设计审阅通过后实施N0复建与N1能力基线。
- [ ] N2—N5能力实验，P1不阻塞主线；Harbor后置。

## v3实施授权与首批工作
- [x] 用户批准无人值守推进v3；Harbor新GPU作业暂停。
- [ ] N0原生独立环境复建与有界训练/reload。
- [ ] N1四能力动作盘点和基线合同。
- [ ] P1原生启动mode透传与测试（GPU对照待N0通过）。

## 最新执行顺序：能力与结果优先
- [ ] N1真实跑通DSH/记忆/上下文/受控RSI四类任务，分别保存证据。
- [ ] 各类固定条件新run复现结果，再核训练前后变化。
- [ ] N0-E环境安装作为旁路交付，不阻塞上述工作。

## 2026-09-09 当前能力推进

- [x] 保存并推送0fdcbeb记忆边界与context准备器；22项复核与Ruff双门通过。
- [x] GPU从GitHub同步0fdcbeb，复用已验收venv，启动四例context真实基线。
- [x] context r1真实结果已核：4完成/0奖励/1准入拒绝，证据保存；未验收通过。
- [ ] 修订prompt歧义并独立r2复跑，评分标准不变。
- [x] 固定Linux runtime记忆边界canary14请求通过。
- [ ] 接真实模型A/B，严格freeze与双方回执身份。
- [ ] 查明grounding截断预算并独立复跑；不修改旧证据。
- [ ] 按四能力覆盖设计独立训练/评估任务，完成RL更新及reload；四例诊断不算能力训练完成。

Review：当前四能力仍未验收完成；真实GPU baseline在运行，后续以进程及回执为准。

## 2026-09-09 真实错误修复与后续门

- [x] memory反馈/3连拒绝保护：55项root CPU与3组Node；d13bda9已推送。
- [x] GPU新writer r2已启动（PID125477），复用固定venv与DSH。
- [x] context v2探索r2失败定位：合法view_range误判，16条真实会话已完成但准入拒绝。
- [x] 修复view_range边界并新身份r4真实复跑，不覆盖旧回执。
- [x] writer r2未通过，保留失败与诊断；新prompt revision2另开r3。
- [x] context v2有效训练组→参数/optimizer审计→独立reload与dev评估；严格准确率0，非能力通过。

Review：M1先前RL通过；本轮context/记忆仍是基线与接线修复，不宣称新增RL成功。

- [x] context v2 r4真实四题strict准入与TQ回读通过（290.008秒exit0），已归档完整回执。
- [x] context v2两步RL完成，14组消费与checkpoint/optimizer审计通过；仅首步有非零任务梯度，独立reload4题通过执行。

## 当前复核：context独立reload与memory新链

- [x] context训练/reload证据归档云盘，完整报告及HTML更新，390px视觉复核通过。
- [x] RSI两项开发worker独立评分合同，97项root联合CPU回归；尚未真实学生配对运行。
- [x] memory writer r3真实完成、reward1，严格freeze成功。
- [x] memory r3独立reader完成、最终整链身份与结果审计、云盘归档通过。
- [ ] 四能力足量结构覆盖与有效RL组、留出评估；不将12可用题当作12已消费题。

Review：context实际消费2条独立训练题/8次尝试；严格dev准确率0。memory r3整链通过，第二族updates-r1 writer运行中；training=false，整体Goal保持active。

- [x] updates-r1第二族真实A→冻结→独立B通过，独立回执/事实更新审计与云盘归档通过。
- [x] 启动context完整12题课程（PID162712），日志确认12train/4dev/12steps；尚未验收消费与更新。
- [ ] 课程实际覆盖、非零优势、checkpoint与独立reload验收。

## 2026-09-09：额度恢复后的执行计划

- [x] 实查训练监督终态和 GPU：context 12步 exit0，0 MiB。
- [ ] 完成12步实际任务消费、拒绝组原因、参数变化与开发集审计。
- [ ] 固定相同版本，独立加载 step12 并重新评估。
- [ ] 完成记忆 A/B resident backend 训练接线、CPU回归，再真实 GPU 验收。
- [ ] 完成 RSI 父策略基线准备，随后真实学生候选与比较。
- [ ] 每个完成环节运行 Ruff 双门、commit/push，更新交接。

Review：训练进程正常结束与全组通过分开；数据量按独立任务、采样与实际消费分别核算。

## 当前记忆RL工程接线批次

- [x] context母课程专属optimizer与step12独立reload/4新评估消费验收。
- [x] 完成人工SSH复跑手册、E0—E5验收标准并推送。
- [x] 修正NativeMemory训练step与实际权重版本绑定，281项组合回归后commit/push。
- [x] 完成独立memory数据/recipe清单和trainer真实消费审计器，CPU通过并push。
- [ ] 固定新integration commit、复用既有venv，GPU验证resident A/B及n4路径。
- [ ] 按实际reward差异报告有效学习信号，不人为制造奖励方差。

### Resident memory r1失败后的r2计划

- [x] 保留r1构造失败、零消费、专属SIGTERM及GPU释放证据。
- [x] 修正默认reward handles注入误判，316项组合/主线程38项回归通过。
- [x] 提交推送后从GitHub固定c5dacdc新源码，重新prepare/check/launch val-r2。
- [x] val-r2真正A/B执行、policy0原始版本、原奖励与2 keys实际消费审计passed=true；train-r2 CPU准备完成。
- [x] 启动train-r2并保留失败：initial val A行为错误，未到n4，无checkpoint；不能标训练验收通过。
- [x] 独立reload入口完成CPU实现与回归；待后续合格母checkpoint再真实验证。

Review：旧train-r1准备清单已作废，不修改旧JSON或追认r1成功。

## 2026-09-09 用户明确记忆/context能力目标

- [x] 明确A/B文件传递是工程诊断，不等于完整MemAgent复用或工作状态管理能力。
- [x] 对照DSH固定版本与ContextPilot设计核实接口：文件工具可用；人工compact/自动compact/实验ABI与模型工具分开。
- [x] 形成完整16节训练设计MD与HTML概览：12开发种子规格、信息矩阵、奖励、数据/验收路线。
- [ ] 当前train-r2及独立reload单独收尾；不把其单题成绩宣称为新版能力覆盖。

Review：用户核心是适时管理工作状态，奖励以恢复后的任务完成/事实保真为主，压缩率和写文件次数不作为成功指标。

Review：下一步WS01/03/05/06任务实现与新版合法低质量memory合同；当前GPU无任务。训练框架二级空keys错误仍未修复，不与A真实行为根因混淆。

## 工作状态原生RL工程主线（用户已批准）

- [x] 完整训练设计MD与HTML，任务/运行时/消费三线独立review。
- [ ] 新版多文件任务与权限、冻结bundle、合法低质量A/B verifier与oracle反例。
- [ ] 复用NativeMemory编排和原TQ/VERL，版本化stage/credit/消费合同。
- [ ] strict sync validation及时传播原失败，保留train补采。
- [ ] CPU/真实DSH工具canary后固定新commit，GPU工作状态基线与n4有效训练。
- [ ] 本任务checkpoint/optimizer审计、独立reload/fresh评估、复跑手册和证据归档。

Review：以工作状态任务完成新原生链，不以旧固定facts诊断反复重跑为前置；pin未变，性能和compact后置。
