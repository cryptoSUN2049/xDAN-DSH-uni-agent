# Uni-Agent 项目状态回顾与本地交接

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
- [ ] 明确允许 EnterWorktree 不可用时的手工替代方式，随后创建隔离 worktree。
- [ ] M0：隔离 worktree 内复现、修复并验证两个 CI 问题。
- [ ] 恢复可重建 DSH source/runtime，明确新 run 的 node/exe 身份与 Linux x64 CPU 构建方式。
- [ ] M1 CPU 准备：八条输入、启动命令、持久化证据和审计；不依赖 GPU 购买或旧 checkpoint 恢复。
- [ ] 实际付费运行前单独确认 GPU/模型预算并验证停止机制。
- [ ] M1 有界 GPU：单卡 inference-only smoke，逐 family 验收，导出并按截止时间释放资源。
- [ ] 更新真实结果、handoff、来源及 PR；通过后进入 v3 release。


## 2026-09-08：真实代码系统架构审计

交付：`docs/dsh-adapter/uni-agent系统架构.html`。本轮为文档审计，不修改产品代码。

- [x] 恢复三个分支的交接，确认最新集成工作区有在途合并，保存源码身份快照。
- [x] 并行审计核心框架、DSH链路、VERL边界，以已提交代码与在途变化分别取证。
- [x] 生成单文件离线HTML：分层架构、数据流、能力矩阵、接口、验收与缺口。
- [x] 核对事实和源码链接，验证桌面/手机显示、筛选及打印布局。
- [x] 记录审计结果及交付路径。

文档规格：静态单文件HTML，内嵌CSS分层图与轻量筛选；不依赖CDN。
测试计划：本地结构/链接审计，gstack browse桌面与手机检查；历史运行结果明确标注来源与未复跑范围。

### 本轮 Review

- 最终代码基线为最新集成 `7139f57` + VERL `fefb080`；审计中捕获并复核了新提交，不沿用初始合并冲突状态。
- 含 README / 参考成绩对照、14个正文章节、18项能力、40个来源入口；区分源码、当前CPU、上游与历史GPU证据。
- 本次DSH相关8文件79 passed；Framework严格准入子集28 passed（52 deselected），合计107；先前26项包含于79项，不重复计数。24-case CPU matrix符合预期。
- 浏览器1440×1000与390×844无页面横向溢出；166个链接的本地路径/锚点有效；筛选/重置/目录跳转通过，无本页console error；A4打印导出成功。
- 独立内容审阅未发现重大事实错误。未运行模型/GPU/云资源或修改产品代码。
- 产物：`docs/dsh-adapter/uni-agent系统架构.html`、同目录`uni-agent-architecture-evidence.json`。


## 2026-09-08：Qwen3.5-4B 能力与快速训练收益分析

- [x] 核对官方模型卡 benchmark、测试设置及Qwen3-4B区别。
- [x] 对照最新Uni-Agent模型专用recipe、MemAgent和DSH准入。
- [x] 按数据成本、接线成本和可验证收益排序最小实验。
- [x] 核验来源，给出结论和无法由当前证据承诺的边界。

本轮为研究分析，不启动训练或付费资源，不修改产品代码。

Review：官方模型卡分数按表格列核对；最新代码9b7dbdb明确旧DSH launcher拒绝qwen3_5，Qwen3.5 recipe默认64卡、MemAgent默认8卡。推荐区分“最快训练验证”（MemAgent）与“DSH业务优先”（工具/恢复）；OPD/SFT边界和GRPO组内方差信号已注明。详细结果：docs/dsh-adapter/qwen3.5-4b-capability-and-training-analysis.md。本轮没有训练或模型推理。


## 2026-09-08：DSH 专家小模型与记忆/context专项整改方案

- [x] 复核Uni-Agent最新版本、部署预检和MemAgent实际实现；读取当前目标与历史边界。
- [x] 分仓审计DSH和ContextPilot实际代码/进度，区分上游方法、迁移实现和本机证据。
- [x] 编写专项HTML：目标、事实、架构、整改项、接口/文件、数据/奖励、分阶段实验、验收及优先取舍。
- [x] 独立事实复核、链接检查、桌面/手机与交互/打印验证。
- [x] 更新交接并提交文档。

规格：单文件离线HTML；交付到docs/dsh-adapter/，不改产品代码、不调用模型或创建资源。方案细化属于本次授权，后续实现按具体任务及既有工程授权推进。

用户追加发布对标：核查MiniCPM5-2B官方模型/数据、AA口径、Meshy与JustRL II真实公开范围；补充公平比较、可借鉴数据与模型发布门槛。

- [x] 完成MiniCPM5-2B跨来源核实并纳入正文、课程、SP0/SP6/SP7与验收。

### 专项 Review

- 审计Uni-Agent9b7dbdb/verl fefb080、DSH memory71ca762、CP0b04840与DSH training1af5b00；44个源码/记录文件SHA256复核一致，区分未提交文档与产品代码。
- HTML含15节、12项整改、SP0—SP7、接口与文件、SFT/GRPO/ContextPilot完整路线，以及MiniCPM5-2B三轨发布对标与JustRL II独立候选实验。
- 真实pilot仅5attempt/10Session/58generic rows，生产训练eligible为0；不能等同记忆/context已训好。
- 独立事实复核通过。154链接中139本地链接/锚点有效；桌面1440和手机390无页面横向溢出，筛选/重置/目录与本页console通过；24页A4打印无文本横向越界并抽查截图。
- 本轮只写文档，未运行模型、训练、部署或修改产品；历史测试/GPU成绩未在本轮重跑。提交不推送。

## 2026-09-08：数据层与完整训练路线深化

规格：补充离线HTML专题，解释GKD/OPD关系、统一数据合同、数据生产与规模、SFT→学生状态蒸馏→RL→长循环/跨Session RL的进入门槛；更新原方案入口。只修改文档。

- [x] 复核最新源码身份与SFT/teacher/多chain支持，区分当前工程smoke模型与目标Qwen3.5。
- [x] 对照原始GKD/OPD资料，定义教师接口、loss与token对齐边界。
- [x] 形成数据层、课程/规模、训练阶段与长循环信用分配设计。
- [x] 独立复核，检查HTML链接、桌面/手机、打印；更新handoff并提交。


Review：新专题DSH数据层与完整训练路线.html包含11节、五类核心数据＋训练消费记录、D0—D7数据产品、SFT/纠错/GKD/PG-OPD/RL/long-loop分工与独立消融。以d606851/verl fefb080审计；20源码引用；55本地链接通过、手机390/桌面1440无页面溢出、15页A4无文字横向越界。独立复核后补齐终态无next-request、SFT与RL不同mask、credit与节点选择分开消融。未训练、未部署。

追加仓库同步核查：2026-09-08 12:42 UTC+8，官方UA89733ec为harbor d606851祖先，origin harbor与本地一致；默认main6e00d83落后官方5提交，root也尚未含这5提交。配对verl fefb080与官方UA gitlink一致，独立verl main又领先54提交。本GitHub仓库private:false。只读查询未fetch/merge/push/SSH；详细远端身份保存到dsh-data-training-evidence.json。

## 2026-09-08：更新默认main至最新集成代码

用户已明确授权更新main。方案：冻结origin/worktree-harbor-modal-integration的已提交快照，保持配对verl，验证后仅快进main；不纳入集成工作区正在开发的未提交文件。

- [x] 核查本地/远端身份、main祖先关系、工作区变化；main6e00d83可快进到d723b5f。
- [x] 导出独立只读测试快照及固定verl fefb080，Ruff lint/format通过。
- [x] 执行CPU回归与必要CI等价检查：471项通过；3项vLLM本机依赖限制留待Linux CI。
- [x] 正常快进推送main，回读远端SHA并同步本地main引用：均为d723b5f。
- [x] 检查main CI、记录交接与结果：pre-commit/docs/secrets-scan成功；Python3.11/3.12仍安装依赖，未宣称通过。

Review：main本地/远端均d723b5f；正常快进无force，未修改集成工作区dirty文件；结果保存docs/dsh-adapter/main-sync-result.json。审计记录仅本地提交，不重复推送main。

## 2026-09-08：面向RunPod全链路会话的参考MD

- [x] 读取harbor最新handoff/active goal/源码与未提交工作，更新M1 reload和M2 worker状态。
- [x] 形成单份可直接交给另一会话的MD：证据优先级、已完成、当前缺口、最小推进顺序、研究复用与验收。
- [x] 核查路径和事实、保存版本/来源摘要，更新本分支handoff并提交；不修改另一会话工作区或远端服务。

Review：参考MD共222行，已核对所有本地Markdown链接；独立源码复核补充Task注册、Gateway生命周期、训练身份与TQ接续入口。GPU和测试数字引用既有报告，本轮未复跑；未修改目标工作区或远端服务。

## 2026-09-08：DSH源码推送增量影响核查

- [x] 比较b2369692ea→e4a628ed3e提交和Python AST，核查Harbor仍固定7840。
- [x] 在参考MD补充9.1节，明确source/wheel/image/run边界和升级交付链；更新lessons。

Review：只读本地DSH与Harbor代码，未查询远端Release、构建运行时或变更运行环境；远端发布状态明确引用用户回执。
