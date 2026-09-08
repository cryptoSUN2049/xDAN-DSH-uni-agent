# DSH Session API 与训练轨迹兼容性审计

审计日期：2026-09-08（Asia/Singapore）。本报告是当前 Uni-Agent worktree 的跨仓审计快照。只读检查 DSH 源码、Git 状态与既有日志；没有修改 DSH、升级运行环境、调用模型或重新执行其构建。审计期间另一个 DSH 会话仍在提交，以下区分观测先后。

## 结论

用户提醒对应真实问题：DSH-Exp 合并新版后，原有离线训练转换器仍按旧 Session 存储与独立 assistant/chunk 事件解码。修复已从最初的未提交修改推进至本地提交 `3e93373d9752200ebefa2dc5746f42ae73805f82`；18 项聚焦测试日志通过，但没有完整构建成功证据，分支尚未推送。

当前训练 runtime 固定 `7840bced35ee07ebefbdce0106b56dbc00bdc3ef`，不会因 sibling 仓本地同步而改变。M1 的 update、消费与独立 reload 证据仍只属于该 runtime，不能推广为最新 DSH 或 ContextPilot 兼容证明。当前 RL 路径使用 Python SDK 实时事件与 Uni-Agent Gateway token，不调用 DSH 的离线 `scripts/trace-training/converter.ts`。

最新 DSH 是 **Session v2**；升级必须覆盖 v0→v1→v2、Session handle、事件坐标迁移和 ContextPilot 消费者。之前 `dsh-latest-audit.md` 的 v0→v1 描述不足以覆盖本次最新源码。

## 版本与发布状态

| 对象 | 本次直接观察 | 判断 |
| --- | --- | --- |
| GPU 训练固定来源 | `deployment/versions/dsh-runtime-candidate.json:4` 为 `7840bced35ee07ebefbdce0106b56dbc00bdc3ef` | 0.1.2-alpha.1 基线；本次未改变 |
| DSH 官方训练 worktree | 本地 `1af5b00d6802db7acbc742c9b832f2b514297e97`；远端同名分支 `7840bced...`，本地 ahead 4 | 不把本地文档提交当作已发布 runtime |
| DSH-Exp 初读根目录 | `sync-dsh-architecture`，HEAD `ec6fa89af199a2a5e61b24c445fce4194d54afe4`，合入官方 `c389f96...` | 已合并 0.1.3-alpha.2；converter.ts/spec.ts 当时 dirty |
| DSH-Exp 收尾复查 | HEAD `3e93373d9752200ebefa2dc5746f42ae73805f82`，2026-09-08 13:36:35 +08:00 | converter、spec、架构 gate 已本地提交；架构 HTML/索引/tasks 仍在修改 |
| DSH 远端同步分支 | `git ls-remote --heads origin sync-dsh-architecture` 无结果 | 本次查询时未推送该分支 |
| ContextPilot 专题 | 本地/远端均 `71ca762018beebb58635bb4e896ebfbb4c6c2556`，工作区 clean | 实际 source/fs/runner 已提交并推送；不是最新 Session v2 迁移成果 |

只查询了必要远端分支，没有读取或记录凭据。DSH 主仓仍有并行工作，后续发布前应重新核对 HEAD 与状态。

## 已验证的 Session 变化

### 1. 存储 API 与持久化时机

旧 pin 的 `packages/session/session-persistence/src/index.ts` 使用按 id 寻址的 `create/append/load/inspect/readFrom/readRaw`；旧 `append(id, events)` 文档承诺返回时 durable。最新接口通过 `create/open` 返回 handle，读取和写入发生在 handle 上。

当前权威源码：

- [SessionPersistence](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/session/session-persistence/src/index.ts:145>)：`create(header)` / `open(id, access)` 返回 `SessionHandle`；service `flush()` 汇总活动写 handle。
- [SessionHandle](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/session/session-persistence/src/handle.ts:83>)：`read()` 返回 `{eventState, events}`；不是裸数组。
- [append](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/session/session-persistence/src/handle.ts:85>)：只保证接受、排序及本实例可见；crash durability 必须等 `flush()`。
- [flush/close](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/session/session-persistence/src/handle.ts:99>)：flush 是持久化屏障；write handle close 等待持久化并释放写所有权，幂等且不可取消。
- [写入生命周期](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/session/session-persistence/README.md:57>)：published Session 没有 active write handle 时不自动持久化；session/flush 是 drain 与失败观察点。

迁移时不能把 `append` 返回、Agent idle、SDK 采集完事件、Session durable 四者混为同一证据。跨 Session 记忆 snapshot 继续要求 idle→flush→snapshot→文件 sync 的顺序。

### 2. Seq / LogOffset / fork

[types.ts:29](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/core/session/src/types.ts:29>) 定义 `SessionSeq` 与 `SessionLogOffset` 两个品牌类型；[index.ts:597](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/core/session/src/index.ts:597>) 提供 `eventAt(seq)`，609 提供 `snapshotEvents(from, toExclusive)`，638 的 `seq` getter 是下一个位置。

**最新仍明确保证 `seq = log.length`、从 0 连续。** 不能据此变化声称事件变为非连续。风险来自 inclusive event seq 与 exclusive/count offset 混用、fork inherited cut，以及格式迁移重排坐标。旧 `session.events` 公共读取被 `snapshotEvents()` 取代；完整 snapshot 与从中间开始的 slice 也不能互换后继续用绝对 seq 做下标。

[Session header](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/core/session/src/index.ts:97>) 拒绝旧 `seedLength` 字段；`inheritedEventCount` 在 storage/restore 参数中单独传递。不能直接重用旧 header 解码和 `Session.create` 调用参数来恢复 fork。

### 3. v0→v1→v2 与 assistant stream

[生成的 catalog](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/session/session-format-catalog/src/generated.ts:14>) 固定 `currentVersion: 2`，装配 v0、v1、v2 codec 和两个 adjacent migrations。最新 [Session 类型](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/core/session/src/types.ts:86>) 同样为 2；319 声明 `assistant/attempt`。

v2 把 provider stream 内嵌到 `assistant/message` 或失败/重试 `assistant/attempt`。旧独立持久 `assistant/chunk` 不能继续作为所有版本的唯一 replay 输入。版本号、原始文件字节、迁移后的逻辑事件坐标应分别记录；不能改历史原件来让新导出器通过。

## 离线 converter 修复及证据

本地提交 `3e93373...` 的关键代码：

- [converter.ts:298](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.ts:298>)：使用 `sessionFormatCatalog.createRestore(..., {recovery:'strict', validation:'current'})`、decodeRow、finish，返回当前格式 events，同时保留输入原始字节 hash。
- [converter.ts:387](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.ts:387>)：从 message/attempt 的 embedded stream 还原尝试；仍校验 terminal finish、内容和 usage。
- [converter.ts:459](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.ts:459>)：新的 `sourceEventSeqs=[rawEvent.seq]` 指向拥有 embedded stream 的 assistant message；不是旧格式中更早的 chunk seq。
- [converter.spec.ts:85](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.spec.ts:85>)：新增 v0 输入与当前 v2 导出 request/response 等价验证；原 fixture 从 27 个旧事件恢复为 16 个当前事件。原始 hash 与恢复后 seq 不是同一个版本的坐标。

本次读取到的实际日志（未复跑）：

| 日志 | 实际内容 | 可宣称的范围 |
| --- | --- | --- |
| `/private/tmp/dsh-converter-test.log`，13:32:41 | Vitest 1 file / 18 tests passed | 修复期 converter 聚焦测试通过 |
| `/private/tmp/dsh-converter-types.log`，13:33:11 | 空文件 | 不能仅凭空日志断言 typecheck exit 0 |
| `/private/tmp/dsh-sync-build.log`，13:34:58 | `MISSING_EXPORT FIRST_PARTY_SECTION_ORDER`，`build:lib exited with 1` | 这次完整构建失败；不能把多个子包 Build complete 当作全构建成功 |

build 错误引用 `lib/types/index.js` 中对 system-prompt 的旧导入；对精确 `3e93373...` 执行 `git grep FIRST_PARTY_SECTION_ORDER -- packages` 无匹配，最新已跟踪源码没有该符号的使用。因此旧日志不证明最新 HEAD 必然构建失败；可能存在未清理的构建产物，本次未追查或清理。准确状态是：**最新 HEAD 的完整构建尚无匹配的成功证据**。18 项测试与先前构建失败覆盖不同层面，DSH 交接写“构建复核中”也不是成功结果。

日志 SHA256：

- converter test：`bc8e61acaebee29b7c9cbe9e856ba256b67429a319ba71f175fa6dbac8ec0448`。
- build：`7e3fae6499adf91d421f3fbdcb94c550119b12aebdbf3c26a4034f31f209e097`。

## ContextPilot 的具体阻断点

以下路径属于 `.Codex/worktrees/feat-contextpilot-capability-sft` 的 `71ca762...`，不是根目录最新代码。三个包具有真实实现；本报告不把它们降格为设计稿，但也不把其旧版本测试推广为新 Session 兼容。

| 模块 | 直接源码证据 | 升级影响 |
| --- | --- | --- |
| phase runner | [index.ts:186](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/feat-contextpilot-capability-sft/packages/experimental/contextpilot-training-runner/src/index.ts:186>) 记录 firstSeq；193 `sessions.flush`；194 `agent.session.events.filter` | 必须改用 `snapshotEvents(firstSeq)` 并验证只有一个闭合 turn；`sessions.flush` 仍有新版本入口，不应无理由重写生命周期 |
| source invariant | [invariant.ts:267](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/feat-contextpilot-capability-sft/packages/experimental/contextpilot-training-source/src/invariant.ts:267>) 遍历 `session.events`；277再次传入 | 明确引用已移除公共属性；迁移 snapshot 与 exact seq 读取 |
| source invariant payload lineage | 同文件211/240按 payload 的 `sourceCallEventSeq` 访问完整 events | 完整当前连续数组可这样索引，但历史格式 migration 后 payload 内自定义 seq 必须同时迁移，不能只迁 envelope |
| source exporter | [contextpilot-source.ts:611](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/feat-contextpilot-capability-sft/scripts/trace-training/contextpilot-source.ts:611>) 拒绝 `sourceEventSeqs` 中任何 `seq >= assistantEventSeq` | 与新 converter 的 `[assistantEventSeq]` **直接冲突**，可从两处条件静态证明；不应简单删除 lineage 校验 |
| source event vocabulary | `contextpilot-training-source/src/index.ts:254` 定义 log-only evidence，known-event-types 扩展在专题分支 | 最新官方基础 runtime 不认识该扩展；须随固定依赖闭包注册并验证，不能把未知事件改 ignorable 来绕过准入 |
| virtual fs | `contextpilot-training-fs/src/index.ts:290` 返回独立 snapshot；本身无 Session API 调用 | 直接 Session 风险较低；仍须验证 native read/write/edit provider 与新 runtime 的组合 |

对于已存在的 ContextPilot v0 原件，还需明确接受策略：上游标准 migration 并不能仅凭事件名理解自定义 payload 中的 seq 引用。应提供经验证的迁移映射或明确拒绝这些旧原件；避免 silently 改成当前坐标。

## 对 Uni-Agent 的实际影响

[runner.py:97](../../uni_agent/agents/dsh/runner.py) 使用 `DeepSeekHarness.run`，结束 Python context 后把 `result.events` 编为私有 canonical JSONL，记录 hash 和 event count。它没有调用 DSH `readRaw` 或离线 converter。这个 `session.jsonl` 是 **SDK root-session 事件捕获产物**，不能与带 version header 的 DSH persistence 原始文件混称。

最新 [Python SDK api.py:149](</Users/gumpm5/Documents/Code/xDAN-DSH-Exp/python/sdk/src/deepseek_harness/api.py:149>) 继续收集根 session 的 `session.event` 通知，到 idle 结束；211/239 从 assistant/message / turn/end 读最终文本与原因。用标准库 AST 对比精确 `7840` 与 `3e93373` 的 Python client/api/models 三文件，三者均 AST 相同；SDK server 的 SessionId 构造改为 brandString。Python 行为相同仍不能证明底层事件内容和清理时机全部兼容。

- [trajectory_audit.py:104](../../uni_agent/tasks/dsh/trajectory_audit.py) 核对 trace 字节 hash、最后 turn/end、event count；没有解码 v0/v1/v2 storage header，也不验证完整 Session replay。
- [evolution_verifier.py:77](../../examples/dsh/evolution_verifier.py) 依赖 tool/call、callId、arguments 与 tool/result message；不依赖独立 assistant/chunk，因此不会因 chunk 移除而必然坏，但仍需真实当前 SDK trace 回归。
- Gateway 自身负责实际生成 tokens/logprobs/mask。换 DSH 版本会改变 prompt/system/tool 模板和请求次数，必须重新核对 request→Gateway session→receipt→trainer consumption，不能用离线 converter 18 tests 代替。

当前 `7840` 的 M1 两步 update、10 组训练/validation 消费和2组独立 reload 审计来自主线程现有运行记录；本审计未复跑或扩大该证据。最新 DSH 兼容、ContextPilot 多阶段文件记忆以及 Harbor DSH bridge 均需各自验收。

## 最小迁移建议与必要测试

1. 当前工程继续固定已验证 `7840`；完整保存 M1 模型、runtime wheel/hash、checkpoint 与 receipt。DSH-Exp 的 latest 候选单独冻结并取得可重建发布物，再安排升级。
2. DSH 仓完成已提交 converter 的全构建问题与文档发布；记录命令、exit code、source revision。不要依靠 mutable 根目录直接打包训练 runtime。
3. ContextPilot 若只需近期 file-memory，优先迁移 fs + runner 及其依赖闭包；按单独 profile 保持精确 read/write/edit catalog。source/exporter 若进入同批，必须一起迁移上述 lineage 条件及自定义 payload seq。
4. 加入或执行有区分力的版本 fixture：v0/v1/v2 同语义 request/response、retry/abort、fork inherited cut、surface replacement、未知 required event、迁移后自定义 seq。核对原始 hash 不变且输出坐标声明正确。
5. 生命周期验证：write ownership 冲突、append 后未 flush、flush 失败、idle 后 snapshot、close drain、只读 cold read 不修改原件；同时跑 TS/Python SDK keyless snapshots。
6. 集成验证：同一受限 DSH 任务用候选 runtime 生成真实 SDK trace，跑现有 verifier/admission/Gateway 消费审计；然后有界 update→独立 reload。只改变 runtime 一项，保留当前 7840 为对照。

本报告只新增审计文档；没有实施上述迁移。结构性源码冲突已核实，运行兼容性仍须上述测试与新 runtime 实测支持。
