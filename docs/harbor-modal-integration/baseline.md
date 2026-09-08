# Harbor / Modal 集成基线

日期：2026-09-08。用户已允许沿用 `git worktree add`，独立 worktree 已创建。

## 分支与来源

- worktree：`.Codex/worktrees/harbor-modal-integration`。
- 分支：`worktree-harbor-modal-integration`。
- 精确派生点：`41694e2c0e70bad266d4153ade0739a36c3a4112`。
- 来源：`worktree-dsh-v3-live-smoke` 已推送版本；父 Draft PR #2 尚未合并。
- VERL 已初始化到 `483b8a009ba3a97563edee3a19887e4862b8094a`。
- 未来新 PR 先以 `worktree-dsh-v3-live-smoke` 为 base，只评审 Harbor 增量。
- 父 worktree 的决策文档提交 `31a1849` 留在父分支，本文件独立保存其结论。

Git 已证明历史运行提交 `1e709977` 是 `41694e2` 的祖先。本基线继承真实 RL 实现、
unfinished group / reward lineage 修复、CI 修复、M1 CPU 执行器及整体方案。
不从缺后续修复的旧运行提交回退，也不使用有未提交草稿的旧 clone。

## 历史运行证据与边界

真实训练记录为 Qwen3-4B → DSH → Uni-Agent → VERL：

- Uni-Agent：`1e7099777c7e1571fa21e7676699effe31033e18`。
- DSH：`3b8fad1e32fd9d62acdfdb3ccbd8c8074c22d2ea`。
- 模型 revision：`1cfa9a7208912126459214e8b04321603b3df60c`。
- 64 rollouts / 4 optimizer steps，非零梯度、LoRA hash 变化、独立 reload 有历史记录。
- 实验未通过完整组和方差组门槛，不追认为当前严格 C4 / P5 合格。
- CPA 当前仅查到普通 API probe，不作为 DSH / Gateway / optimizer 证据。

来源：[历史状态](../dsh-adapter/project-status.md)、[CPA 探测](../dsh-v3-live-smoke/design.md)、
[训练手册](../../examples/dsh/README.md)。

## 集成合同与路线

1. Uni-Agent 保留任务协调、真实 Gateway session 和训练数据链。
2. Harbor 拥有其 Modal / Docker 环境生命周期；不再叠加 Uni-Agent ModalSandbox。
3. DSH bridge 只复用已有环境的 exec / file 能力，不重复创建或销毁环境。
4. 验证 Modal 内实际 Gateway 可达性、task / trial / session / token / policy version 关联。
5. Harbor 结果须适配 DSH fresh receipt、finished 与训练资格；拒绝错配和重放。

- H0：隔离依赖并固定单 CPU 任务，Docker oracle，再单独验证 Modal oracle。
- H1：DSH bridge + 真实 Gateway；执行、timeout / cancel 与产物回收。
- H2：严格 reward / token / lineage 合同。
- H3：合格批次、真实 VERL update、独立 checkpoint reload。
- H4：同预算 paired holdout；通过后才扩大异步并发与 Harness 演化。

继承的 [整体设计](../dsh-v3-live-smoke/uni-agent-system-plan.html) 包含架构、接口和预计改动范围；
[Harbor 专题](../dsh-v3-live-smoke/harbor-agent-rl-guide.html) 包含教程和上游证据。
本 worktree 新进展以 [入口页](index.html) 和 [handoff](../../tasks/harbor-modal-integration/handoff.md) 为准。

## 当前预检

Docker Desktop 29.2.0 / Linux arm64 已只读确认可用；全局 Harbor 0.1.45 低于
本仓教程要求的 0.16.1，应在隔离环境固定兼容版本，不直接升级全局工具。
旧 DSH source / Linux runtime 仍需恢复或明确冻结可复建新版本。
当前尚未执行 H0 oracle、Modal、模型调用或训练；v3 八类 smoke 仍为 0/8。
此次手工创建授权不包含付费云资源和模型运行。
