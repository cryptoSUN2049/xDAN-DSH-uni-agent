# Uni-Agent 项目状态回顾与本地交接

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
