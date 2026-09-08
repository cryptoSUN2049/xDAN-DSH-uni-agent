# dsh-adapter 交接

> 2026-09-08 最新专项交付：先读 [DSH专家小模型、记忆与Context整改方案](../../docs/dsh-adapter/DSH专家小模型-记忆与Context专项整改方案.html)。最新产品基线为 `harbor-modal-integration / 9b7dbdb` + verl `fefb080`；新增MiniCPM5-2B发布对标。下方早期工程状态保留为历史，不覆盖最新worktree与本轮证据。

更新时间：2026-09-07。新 session 首先读取本文件，再读本地状态快照及下一里程碑设计。

## 1. TL;DR

- 当前实现是独立 `xDAN-DSH-uni-agent` 的 `dsh-adapter`；代码基线 `ea06d5a`，最新预检基线 `55ed21f`，Draft PR #1 已建立。
- 已有真实 online RL 四步参数更新与独立 checkpoint reload；P3 credible 未通过，P4 core 通过，P5/P6 未完成。
- v3 catalog、24-case CPU gate、live-contract verifier 已落地；八类真实 process smoke 最新记录为 **0/8**。
- CPU 路线已确认：本机复现 CI 失败，原缺依赖的两个审计文件 20 passed；待允许手工 worktree 后修改。GPU/付费运行另行确认。
- 详情、测试命令和跨仓来源见 [项目状态与目标](../../docs/dsh-adapter/project-status.md)。

## 2. 本轮交付物

文件行数为本次文档定稿时的值，内容调整后需同步更新。

| 路径（仓库根目录起） | 行数 | 说明 |
| --- | ---: | --- |
| `README.md` | 116 | 增加本地交接、状态快照和 DSH runbook 入口 |
| `docs/dsh-adapter/project-status.md` | 300 | 分支、开发/测试状态、目标、来源、跨仓对比及新 CPU 基线 |
| `docs/dsh-adapter/live-smoke-next-milestone-design.md` | 212 | M0/M1 设计、CLI 最小差异与证据合同；CPU 与 GPU 阶段分开 |
| `tasks/dsh-adapter/handoff.md` | 80 | 本仓库冷启动入口 |
| `tasks/dsh-adapter/notes.md` | 92 | CI、runtime/停费核查、临时 CPU 环境与报告哈希 |
| `tasks/todo.md` | 52 | 回顾、资料交付及下一里程碑清单 |
| `tasks/lessons.md` | 30 | 跨仓记忆、证据分层、CPU/GPU 路径选择、预算和隔离边界 |

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
- 历史 RunPod 117-test 结果只属于 `d604458`；9 月 7 日控制面无 Pod/volume/endpoint，旧 Pod 无法直接恢复，checkpoint 备份未验证。
- `max_tokens_per_turn` 不等于 episode 总预算；YAML reasoning 值应为字符串 `"off"`。
- validation-only reload 不继续 optimizer；六个操作入口没有单独的安全 optimizer resume。
- RunPod 新 Pod 隔离本机，不证明同 UID 的模型代码与 verifier/fixture 隔离；停费截止优先于证据导出，停止后仍有存储费。
- 旧 DSH pin 未取得、Linux runtime 部署包缺失、旧 P4 本机备份未证明，详见 [预检笔记](notes.md)；runbook node 模式不能由未执行的 exe hash 证明。
- 临时 CPU venv `/private/tmp/uni-agent-cpu-20260907` 可复现 RLInsight 3 failed / 1 passed；两个原缺依赖审计文件 20 passed。它不是 GPU 环境验证。

## 5. 下一里程碑任务清单

- [ ] CPU 路线已确认，继续 [M0/M1 设计](../../docs/dsh-adapter/live-smoke-next-milestone-design.md)；先明确允许 EnterWorktree 缺失时的手工替代方式，GPU 预算单独确认。
- [ ] 修复 RLInsight fixture / Ruff 分类，完成八条输入、审计与停止 watchdog，再创建 GPU。
- [ ] 恢复可重建 source/runtime；明确实际 node/exe 载体与 Linux CPU 构建方式，不静默替换历史 baseline。
- [ ] 八个 family 各做一次真实 DSH process smoke，保存 envelope/trace/fresh receipt，清除 live-contract pending。
- [ ] 生成并单测 96 candidate、独立预封存 32 holdout、24 verified demonstrations。
- [ ] Frozen-base 校准并冻结 48 train / 16 validation；完成 M3 字段对齐、泄漏审计和 eligible release。
- [ ] 实现累计 generated-group、attempt、token ceiling。
- [ ] 同 base、全新 LoRA、同预算运行 GRPO/DAPO；新 run 产生完整 admission/consumption audit。
- [ ] 独立 reload 并做 paired holdout；P5 要求正 uplift 且 95% CI 下界 >0，安全/协议无实质回归。
- [ ] P5 后验证隔离 Harness candidate 的新任务复用、canary、rollback、promotion。

## 6. 分支 / 部署状态

- 本仓库：`dsh-adapter`；代码基线 `ea06d5a`，文档 `104b53d`、交付记录 `00520c5` 已推送。最新设计/控制面核查的提交以 Git 历史为准。
- Sibling DSH：最新复核为 `worktree-dsh-official-training / 1af5b00d68`，领先 tracking ref 4 个文档提交；新增 CPU 一致性回执与执行器设计，handoff/todo 未提交更新保留。对比见状态 §10。
- 已创建 [Draft PR #1](https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent/pull/1)，`dsh-adapter → main`，覆盖整套 adapter；没有合并、部署或启动 GPU。
- CI head `55ed21f`：Python 3.11 为 565 passed / 1 skipped / 3 failed（RLInsight fixture）；pre-commit Ruff import 分类失败；Python 3.12 cancelled。其余详情见状态 §9 和预检笔记；M0 尚未修复。
- 远端历史 run、版本、P4 结果及来源 digest 均见本地状态文档；不能据旧 manifest 的 `running` 判断当前作业。

## 7. 冷启动 checklist

1. 读本文件 → [项目状态](../../docs/dsh-adapter/project-status.md) → [下一里程碑设计](../../docs/dsh-adapter/live-smoke-next-milestone-design.md) → [项目经验](../lessons.md)。
2. 执行 `git status --short --branch`、`git rev-parse HEAD`、`git worktree list`、`git diff --stat`、`git stash list`；确认实际根目录与 branch。
3. 跨仓验收按状态文档的 DSH scoped handoff、todo、验收标准和 v3 计划核对，勿用旧 clone 或总 todo 推翻新证据。
4. 重跑所需 CPU gate；缺依赖时记录环境限制，不将 collection failure 当作业务回归或全套通过。
5. 从 M0 CI 和八类 process smoke 准备继续；涉及新代码/资源启动时核对设计及预算授权，不将用户询价当作创建授权，并先查控制面实时状态。
6. 新证据完成后更新本地状态、交接和 scoped todo；提交前按变更范围验证，push 前必须通过两项 Ruff 门禁。

## 2026-09-08：真实代码架构文档交付

- 本轮仅在根分支 `dsh-adapter` 新增架构文档与证据清单，未修改产品代码或合并其他worktree。
- 已读用户指定旧HTML、最新README及三个worktree源码；审计期间另一工作流提交 `7139f57`，本页已复核typed TaskResult奖励链与部署目录的真实边界。
- HTML：`docs/dsh-adapter/uni-agent系统架构.html`；来源/版本/验证清单：同目录 `uni-agent-architecture-evidence.json`。
- 107项相关CPU测试通过；桌面/手机、本地来源链接、筛选、目录和打印验证通过。非全仓CI或GPU验证。
- 代码已具备DSH→Gateway→Framework→TQ→VERL训练接线；历史v2更新/reload存在，但升级后GPU组合、Harbor DSH bridge、OPD、paired uplift与自动RSI未验收。
- 后续实施仍进入最新worktree，先读其handoff与实际Git状态；不要在根分支依旧历史todo重复修已完成的迁移。


## 2026-09-08：专项方案与模型发布对标交付

### TL;DR

- 目标：DSH＋Qwen3.5-4B，经Uni-Agent训练专长、memory/context策略，并以MiniCPM5-2B作为发布对照。
- 完成：跨仓真实代码审计、12项整改、SP0—SP7、数据/接口/奖励/验收、三轨对标；尚未实施或训练。
- 先读新HTML与evidence JSON；最新产品实施进入harbor-modal-integration等对应工作区，不依旧根分支todo重复修已完成问题。

### 本轮交付物

| 路径 | 行数 | 说明 |
| --- | ---: | --- |
| `docs/dsh-adapter/DSH专家小模型-记忆与Context专项整改方案.html` | 126 | 专项方案与MiniCPM发布对标 |
| `docs/dsh-adapter/dsh-expert-memory-context-remediation-evidence.json` | 341 | 源码身份、原始来源与验证证据 |
| `tasks/todo.md` | 110 | 任务进度与Review |
| `tasks/dsh-adapter/handoff.md` | 131 | 最新冷启动入口与交接 |

### 设计约束与真实行为

- DSH唯一产品loop；Uni-Agent编排/准入/训练；ContextPilot保留上游oracle、迁移方法；不复制旧vendored verl或另建训练主线。
- DSH已有ActorFS、fresh Session、原生compaction；pilot仅read/write/edit，不能证明18项CP工具及自主context editing已接通。
- CP两批累计5attempt/10Session/58generic rows、2任务/1family、manual0、production eligible0；专用source/真实动作producer/训练闭环仍需专项接入。
- CP snapshot子树均值与query uid归一化不同于JustRL II token critic。E2/E3/E4同一SFT起点独立训练；不得用累计续训替代方法消融。
- MiniCPM官方card与文章/AA有版本和指标口径差异；GDPval891与19.6可归一化相容。数据只有公开轨迹/题目不保证附带环境；固定条款、来源和去污后使用。
- 当前Meshy925fc95公开recipe是标量GRPO；完整JustRL II参考代码未确认公开。当前verl虽已有critic/GAE，也不是完整方法。

### 下一里程碑

- [ ] SP0冻结模型、DSH发布物、parser/任务/verifier，加入MiniCPM共同环境基线。
- [ ] SP1完成Qwen3.5小拓扑真实更新与独立reload；同步准备SP2/SP3 CPU课程与phase桥。
- [ ] SP2—SP4复用DSH现有记忆与投影，建立可信SFT/RL；SP5完成有界分支与可重算credit。
- [ ] SP6进行同DSH、公开Harness、端侧成本三轨评测；SP7交付模型包、profile、recipe、model card与复现依据。

### 分支/部署状态与冷启动

- 本轮仅根分支dsh-adapter文档提交；没有push、合并、资源创建、模型调用或部署。旧CI/GPU结果不代表本轮新组合验证。
- 冷启动顺序：新HTML → evidence JSON → 本handoff → 目标产品worktree的handoff/todo → 实际Git状态；再按实施审批与隔离约定推进。
- 本轮验证：44源文件hash一致；139本地链接有效；手机/桌面/筛选/打印通过；CP、DSH和MiniCPM/算法独立复核通过。
