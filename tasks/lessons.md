# 项目经验

## 2026-09-06：项目记忆必须能在所属仓库恢复

- 用户指出训练交接仅保存在 sibling DSH worktree。本仓库须保留自己的
  `tasks/<branch>/handoff.md` 与 `docs/<branch>/project-status.md`，使新 session
  无需先猜测外部仓库路径就能确认分支、证据、目标和最近阻塞。
- 跨仓库原始设计、论文和实验账本保留其所有权；本地状态快照注明日期、来源
  revision 和证据范围。更新实验状态时同步本仓库快照，避免维护两套完整资料。
- 当前 `dsh-adapter` 是独立 Uni-Agent 仓库的开发分支。位于 DSH
  `.Codex/worktrees/uni-agent-dsh-adapter` 的旧 clone 不代表最新实现。
- 单测/trace replay、真实 process smoke、optimizer update、checkpoint reload、
  held-out uplift 是不同证据。后续代码修复不得追认旧 run 合格；远端状态须带
  查询日期，不能把旧 `status=running` 或历史停止记录当作实时状态。
