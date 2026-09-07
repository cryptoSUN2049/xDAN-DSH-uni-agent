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

## 2026-09-07：先比较全路径成本，再选择是否使用 GPU

- CPU 可连接模型 API，不等于能直接复用要求真实 Gateway ID 的训练 Agent/Task。
  评估成本时计入新增预算、receipt、隔离适配；不要仅按 GPU 小时费判断路径更省。
- DSH turn 不等于模型请求次数；SDK 的逐请求 max_tokens 与 RPC timeout 不等于
  总 token / episode wall-clock 上限。用源码与可执行测试证明预算实际在哪一层生效。
- `sdk-minimal` 的临时 cwd 不是宿主隔离，Cordis node:vm 也不是 containment。
  无模型初始化成功不授权在本机全权限环境运行模型生成的 host code。
- 本机 Ruff 通过不等于 CI 固定版本通过；显式声明本项目 first-party imports，
  避免两版 formatter 反复改动同一空行。
- 当前 runpodctl 2.12.0 help 不含 skill 示例的 terminate-after / stop-after。
  创建前验证真正可执行的停止机制，不把负载退出当作停止 GPU 计费。
- 导出卡住不能延后停费截止；停止后的存储费、补导出和资源删除也必须有截止条件。
- 独立 Pod 只隔离本机；同 UID 的模型代码仍可能修改 Pod 内 verifier/fixture。
  digest 复核可发现变化，但不构成不可篡改或候选权限隔离的证明。

## 2026-09-07：区分本地适配状态与上游生态能力

- 用户要求继续搜索 Uni-Agent / VERL + Harbor，并指出官方新闻、教程和 Hub。
  本地 eval-only 只能说明当前适配范围，不能推导整个生态没有 RL 方案；需核查
  上游代码、PR 是否合并、官方 recipe 与依赖版本，并区分作者实验和独立复现。
- Harbor 任务格式复用、原生 Trial 接入、训练 DSH Agent 是三个层次；Tinker
  Bash Agent 训练成功不能追认为 DSH 已打通，未合并 VERL PR 不能写成 main 能力。
- 长流程的环境连续、会话记忆与权重学习要分别解释。Harbor 多步骤默认新对话；
  resume 依赖 Agent capability，旧依赖版本不能自动享有新版功能。
- 面向入门用户先解释角色和证据，再讲 API。起步命令应限制单任务；latest 任务
  集可能包含 GPU / 多容器任务，不能把完整 benchmark 当作无成本入门检查。
