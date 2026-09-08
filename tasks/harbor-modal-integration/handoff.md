# Harbor / Modal 集成交接

## 1. TL;DR

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
