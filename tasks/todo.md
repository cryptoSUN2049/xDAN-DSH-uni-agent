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

## Tinker Harbor OPD/RL 当前任务

2026-09-15。已完成授权的一批P0训练与独立验证。后续不自动扩大付费运行。

- [x] 4原创任务8次nop/oracle；Student/Teacher基线与真实token评分。
- [x] research/debug和官方源码复核；系统方案A–G确认并实施A–E工程部分。
- [x] 观测、资源、生命周期、初始checkpoint、分项信号及独立强校验接入。
- [x] 286项相关测试通过；10核心模块综合90.67%、分支83.23%。
- [x] b06728a可追溯wheel；最终Linux日志/Plotly/bootstrap真实通过。
- [x] 同资源契约云内audit：nop0/oracle1、2沙箱清理。
- [x] hybrid-p0-20260915-02真实1batch训练，回执与raw token证据通过。
- [x] 官方下载同源initial/final adapters，53,520,850个LoRA元素改变。
- [x] 新容器新进程reload；2任务有效运行，实际成功1题；2沙箱清理。
- [x] 独立审查失败轨迹、参数对比与训练证据；保存报告与项目快照。
- [x] 评估记录补齐的本地实现与465项回归；新代码云验收仍待执行。
- [ ] 更有区分度开发集、Teacher优势检验、非零RL信号真实验收。
- [ ] 官方Terminal-Bench锁定单任务重复、state+optimizer恢复。
- [ ] 最小Control Panel、预算/恢复协议与baseline/OPD/RL/hybrid消融。

## Review
工程闭环通过，能力提升未验证。训练两条轨迹同题奖励全1，所以实际RL信号为0。
验证前2/2、后1/2；失败是配置字段遗漏，不能用小样本和非配对seed断言训练导致退化。
原始产物保留ignored outputs与Modal Volume；权威摘要见docs/tinker-harbor-opd-rl/p0-cloud-closed-loop.md。

## Top-k方案复核（用户新增关注）
- [x] 核对官方SDFT、[N,K]训练和custom loss支持，明确当前Harbor路线及不同KL目标。
- [x] 保存docs/tinker-harbor-opd-rl/topk-opd-review.md，承认原比较遗漏。
- [ ] 27B真实top-k能力探针；9B多目标训练微分验收；Harbor上下文/mask适配。
- [ ] 当前baseline与top-k CE/reverse + RL同口径比较，不能提前称最优。
本轮已完成评估记录代码与本地回归；未提交新模型调用。

## 评估记录关卡最新进展
本地实现与465项回归通过，详见docs/tinker-harbor-opd-rl/eval-evidence-validation.md。新wheel/云验收分开记录；非零RL与能力提升仍未通过。

## OpenThoughts Shell基础候选（保留此前审查）
- [x] 固定39ab7143公开下载与728归档静态检查：616原始问题家族、workspace/output差异、资源与答案隔离已记录。
- [x] 保存docs/tinker-harbor-opd-rl/openthoughts-rl-integration.md设计与证据位置。
- [ ] 有界导入、家族隔离划分、执行profile适配；通过nop/oracle后才做Student/Teacher筛查与新鲜OPD+RL。

## 联合更新复核与真实公开数据（用户明确继续）
- [x] 原始P0逐token独立重算；RL0与OPD1138非零位置确认，131项相关回归通过。
- [x] 4类本地payload边界验证；联合更新参考文档已写，区分模拟与真实云证据。
- [x] 跨领域公开任务策略与有界导入设计：TaskTrove优先审查，NVIDIA后续技能扩展，NL2Bash为基础补充。
- [x] 三源5,830题下载核验；6候选原样落盘、来源/文件哈希和既有loader/资源字段通过；运行兼容仍有明确缺口。
- [ ] 显式执行profile与controller适配、云环境验收，随后真实非零RL+OPD新鲜更新。

本轮Review：131项联合相关回归、4类本地payload检查通过；真实P0原始数组RL0再确认。新模型/沙箱调用0。公开6候选71,381字节已导入，training_ready=false；公开setup_files、workdir、参考解、依赖失败分类待实现/云验收。

## 2026-09-15 里程碑 review

- [x] 联合路径原始证据重算与本地 payload 验证；真实 RL=0 的限制已记录。
- [x] 三份公开 TaskTrove 数据核验（5830 题），六题安全静态导入；训练就绪状态保持 false。
- [x] 更新参考文档、数据策略、handoff 与 lessons；独立提交全仓 Ruff 基线修复。
- [ ] 六题运行时契约与 verifier 验收。
- [ ] 小批真实联合更新同时产生非零 RL / OPD 信号，并完成独立评估。
- [ ] Terminal-Bench 2.1 固定版本与同口径 Opus 4.6 对照。

Review：当前是数据与证据里程碑；最终模型能力目标未完成。提交与远端同步记录以本分支 Git 历史及 upstream 状态为准。

## 公开任务运行更新
- [x] 运行配置适配与134项回归。
- [x] 单题真实Modal nop/oracle环境验收，两个沙箱已清理。
- [ ] verifier故障分类及真实Student/Teacher筛查，尚未新增训练更新。
