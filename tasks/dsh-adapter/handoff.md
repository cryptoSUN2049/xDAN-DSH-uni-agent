# dsh-adapter 交接

更新时间：2026-09-06。新 session 首先读取本文件，再读本地状态快照。

## 1. TL;DR

- 当前实现是独立 `xDAN-DSH-uni-agent` 仓库的 `dsh-adapter` 分支；代码基线 `ea06d5a`。
- 已有真实 online RL 四步参数更新与独立 checkpoint reload；P3 credible 未通过，P4 core 通过，P5/P6 未完成。
- v3 catalog、24-case CPU gate、live-contract verifier 已落地；八类真实 process smoke 最新记录为 **0/8**。
- 下一步先补八组 envelope/trace/fresh receipt，再做 v3 release、预算约束、同预算对照与 paired uplift。
- 详情、测试命令和跨仓来源见 [项目状态与目标](../../docs/dsh-adapter/project-status.md)。

## 2. 本轮交付物

文件行数为本次文档定稿时的值，内容调整后需同步更新。

| 路径（仓库根目录起） | 行数 | 说明 |
| --- | ---: | --- |
| `README.md` | 116 | 增加本地交接、状态快照和 DSH runbook 入口 |
| `docs/dsh-adapter/project-status.md` | 219 | 分支身份、架构、开发/测试状态、P0–P6、全局/短期目标、来源与同步规则 |
| `tasks/dsh-adapter/handoff.md` | 71 | 本仓库冷启动入口 |
| `tasks/todo.md` | 22 | 本次回顾和资料落盘的完成记录 |
| `tasks/lessons.md` | 14 | 跨仓项目记忆、证据分层和旧 clone 识别规则 |

本轮仅修改文档，不修改 Agent、训练代码或历史实验。

## 3. 设计约束

1. DSH 拥有 runtime/plugin/权限/语义 trace；Uni-Agent 拥有 adapter、Gateway 关联和准入；VERL 拥有 optimizer/token ledger。
2. Parquet 是 seed；真实 Gateway 轨迹、完整 group 和 fresh verifier ACK 齐备后才允许训练。
3. 安全且完整的策略失败可以 eligible/reward=0；unfinished、篡改、过期和不安全轨迹必须拒绝。
4. Candidate 不得修改 verifier、reward、credentials、权限、loop spine、共享 Registry 或历史证据。
5. Holdout 独立预封存，不参与选题和调参；unit/replay 不等于 process smoke，update/reload 不等于 uplift。
6. 文档交付放 `docs/<branch>/`，交接放 `tasks/<branch>/`；代码开发遵循用户的隔离 worktree 及设计审批约定。

## 4. 已踩坑 / 已发现的真实行为

- `.Codex/worktrees/uni-agent-dsh-adapter` 是停在 `main/6e00d83` 的旧独立 clone，并有未提交文件。
- 跨仓原始记忆在 DSH `worktree-dsh-official-training`；总 todo 有陈旧段，应读 scoped handoff/todo。
- v2 的 64 rollouts / 4 steps 真实发生，但完整组 14/16、variance 组 9/16 未达 90%/75%；unfinished reward 污染 group statistics，旧 artifact 无法由新 C4 追认。
- P4 加载 504 个 LoRA key 和 trainer state，8 条 holdout 执行完成，平均 reward 0.8125；不是 100% success 或 paired uplift。
- 本次 CPU 子集 82 passed、1 skipped（含 v3 26 项）；另外两个审计文件缺 ray/tensordict 无法 collection，macOS 跳过 Linux `/proc` teardown。
- 历史 RunPod 117-test 结果只属于 `d604458`；本次未查控制面或远端 checkpoint，Pod stopped 是 9 月 2 日记录。
- `max_tokens_per_turn` 不等于 episode 总预算；YAML reasoning 值应为字符串 `"off"`。
- validation-only reload 不继续 optimizer；六个操作入口没有单独的安全 optimizer resume。

## 5. 下一里程碑任务清单

- [ ] 八个 family 各做一次真实 DSH process smoke，保存 envelope/trace/fresh receipt，清除 live-contract pending。
- [ ] 生成并单测 96 candidate、独立预封存 32 holdout、24 verified demonstrations。
- [ ] Frozen-base 校准并冻结 48 train / 16 validation；完成 M3 字段对齐、泄漏审计和 eligible release。
- [ ] 实现累计 generated-group、attempt、token ceiling。
- [ ] 同 base、全新 LoRA、同预算运行 GRPO/DAPO；新 run 产生完整 admission/consumption audit。
- [ ] 独立 reload 并做 paired holdout；P5 要求正 uplift 且 95% CI 下界 >0，安全/协议无实质回归。
- [ ] P5 后验证隔离 Harness candidate 的新任务复用、canary、rollback、promotion。

## 6. 分支 / 部署状态

- 本仓库：`dsh-adapter`；本轮开始 `HEAD=ea06d5a8522b54febc206ad039b9c3097b0aa122`，干净且与本地 tracking ref 相等。文档提交用 `docs(dsh): add local project status and handoff` 定位。
- Sibling DSH：`worktree-dsh-official-training / 4553c835ba`，本地领先 tracking ref 3 个文档提交，handoff/todo 有未提交更新，保留原状。
- 用户后续已授权 commit、同名分支 push 和 PR 整理；本地文档先提交，随后补记远端 SHA 与 PR。没有部署或启动 GPU，RunPod 未实时查询。
- 远端历史 run、版本、P4 结果及来源 digest 均见本地状态文档；不能据旧 manifest 的 `running` 判断当前作业。

## 7. 冷启动 checklist

1. 读本文件 → [项目状态](../../docs/dsh-adapter/project-status.md) → [项目经验](../lessons.md)。
2. 执行 `git status --short --branch`、`git rev-parse HEAD`、`git worktree list`、`git diff --stat`、`git stash list`；确认实际根目录与 branch。
3. 跨仓验收按状态文档的 DSH scoped handoff、todo、验收标准和 v3 计划核对，勿用旧 clone 或总 todo 推翻新证据。
4. 重跑所需 CPU gate；缺依赖时记录环境限制，不将 collection failure 当作业务回归或全套通过。
5. 从八类 process smoke 继续；涉及新实验/资源启动时按现有授权、release 和预算条件执行，并先查控制面实时状态。
6. 新证据完成后更新本地状态、交接和 scoped todo；提交前按变更范围验证，push 前必须通过两项 Ruff 门禁。
