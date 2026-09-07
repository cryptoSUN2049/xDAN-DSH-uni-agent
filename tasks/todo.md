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
- [x] 用户明确允许手工替代方式，已创建隔离 worktree。
- [x] M0：隔离 worktree 内复现、修复并验证两个 CI 问题；a197ead 已推送，五项 CI 成功。
- [ ] 恢复可重建 DSH source/runtime，明确新 run 的 node/exe 身份与 Linux x64 CPU 构建方式。
- [ ] M1 CPU 准备：八条输入、启动命令、持久化证据和审计；不依赖 GPU 购买或旧 checkpoint 恢复。
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
- [ ] Review：必要回归、coverage、自查、交接，推送本分支并记录 PR。
- [ ] 另行确认真实模型和 GPU，完成八类 process smoke。

### 本 worktree Review

代码提交 `27f7efa` / `3220216`。208 项聚焦 CPU 测试通过，四模块 coverage
87%–99%；独立审计 review 的三项问题均有实际 RED→GREEN 记录。
全量本机尝试 744 passed / 7 failed / 2 skipped，不宣称完整 CI 通过；其中
6 个缺 vLLM/Pillow 失败已在基线复现，localhost 502 去除代理后基线通过。
详见 `docs/dsh-v3-live-smoke/verification.json`。
