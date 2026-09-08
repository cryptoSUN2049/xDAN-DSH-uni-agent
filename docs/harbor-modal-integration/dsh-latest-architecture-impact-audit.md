# 最新 DSH 架构对当前训练链路的影响

审计日期：2026-09-08。范围：只读本地 DSH Git、架构入口、转换器、Python SDK、ContextPilot 专题与既有验证记录；未升级 pin、修改 DSH、运行构建/模型。补充并更新 [上一份 Session API 审计](dsh-session-api-impact-audit.md)，不是覆盖其历史观测。

## 决策结论

1. **“本地转换器还依赖旧 Session API”已修复并提交。** 修复提交为 `3e93373d9752200ebefa2dc5746f42ae73805f82`；当前 DSH 根目录 HEAD 是 `b2369692ea530007075ebcd18d39fdba0bbd3982`，分支 `sync-dsh-architecture`，工作区 clean。
2. **构建状态较上一报告有实质更新：现有成功证据。** 新交接和版本化 verification.json 报告构建、lint、聚焦测试通过；本次还读到更新后的原始 build log 已完成 Web build 并记录 234 client artifacts。不要继续引用旧日志失败作为当前状态。
3. **当前 Uni-Agent/Harbor 运行链继续固定 7840，无须为完成本轮 M2 立即升级。** 该链不调用 TypeScript 离线训练转换器。五份 Python SDK 源码 AST 与新 HEAD 相同，但这只证明 Python 源码接口一致，不证明新 runtime 的端到端兼容。
4. **Session v2 与 ContextPilot 要作为独立迁移验证。** 新逻辑事件序号、assistant stream 与持久化 handle 语义有变化；不能重写已有 receipt 所引用的原始轨迹。ContextPilot 专题不在这次新主线中，也未由主线转换器修复自动完成迁移。
5. **198 项现有 Harbor 组合测试仍不是最新 DSH runtime 兼容证明。** 新版需要新 wheel/镜像、无模型 boot、真实 SDK trace、严格 receipt、GPU 更新/reload 分层验证。

## 版本与交接核验

| 对象 | 核验值 |
| --- | --- |
| 当前训练 pin | `7840bced35ee07ebefbdce0106b56dbc00bdc3ef`，0.1.2-alpha.1，Session 格式 0 |
| DSH 根目录 | `/Users/gumpm5/Documents/Code/xDAN-DSH-Exp`；HEAD `b2369692ea530007075ebcd18d39fdba0bbd3982` |
| 架构入口记录的 upstream | `c389f96bf3a9b6807cb71ed6bdad5849be0df6d8`，0.1.3-alpha.2 |
| 架构入口核验代码 | `a3a90039bdaf1a0829e926ae348fd98ec7b34f0f`；当前逻辑格式 2 |
| 离线转换器最新修改 | `3e93373d9752200ebefa2dc5746f42ae73805f82` |
| 历史官方训练 worktree | `1af5b00d6802db7acbc742c9b832f2b514297e97` |
| ContextPilot 专题 worktree | `71ca762018beebb58635bb4e896ebfbb4c6c2556` |

入口 [architecture-entry/index.html](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/docs/architecture-entry/index.html:12) 区分 observed upstream 与 reviewed local commit；14 章源码映射覆盖 Session v2、Web/Desktop 等。`git diff --name-only a3a90039bdaf... HEAD` 只有文档、截图和交接资料，没有 runtime、SDK 或转换器源码变化。因此 reviewedCode 对当前 HEAD 的代码仍匹配，不因最后一份文档提交改变而失效。

用户新交接报告 clean、未 push。当前 Git clean 已直接核实；本轮没有联网重查远端，未将用户的未推送说明变成独立远端核验结论。

## 相对上一报告的验证证据更新

权威交接：[handoff.md](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/tasks/sync-dsh-architecture/handoff.md:1)；版本化执行记录：[verification.json](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/tasks/sync-dsh-architecture/verification.json:1)，recordedAt `2026-09-08T05:45:17+00:00`，reviewedCode 为 a3a90039bdaf。

| 项目 | 这次可见证据 | 边界 |
| --- | --- | --- |
| `pnpm run build` | verification.json 为 passed；`/private/tmp/dsh-sync-build.log` 已更新，mtime 13:39:52，末尾 `built in 14.91s`、`recorded 234 client artifact(s)` | 旧报告在 13:34:58 读到的是同路径先前失败版本；日志已被覆盖，不能继续沿用旧 hash/失败结论 |
| Host TypeScript | verification.json 报告 tsc -b 成功且含 final gate source changes | 本轮未重跑 |
| lint | verification.json 报告 contracts-ready 成功；`dsh-sync-lint.log` 仅命令行 | 成功结论依据版本化执行记录和用户交接，不能单凭短日志推断 exit code |
| converter | 原始 `/private/tmp/dsh-converter-test.log`：18 passed；修复提交含对应测试 | 覆盖离线格式转换，不覆盖新 runtime 联调 |
| gate / 架构验证 | verification.json：94 项 gate/index、21 项架构测试，架构入口及页面检查通过 | 架构核验不是模型能力证明 |
| 全仓文档检查 | 仍记录旧研究稿双语配对、Node22 globSync ENOTDIR 问题 | 不宣称所有仓库门禁全绿 |
| DSH 仓内 Uni-Agent overlay pytest | verification.json 记录收集失败：缺完整 Uni-Agent 主体/get_agent_cls | 与当前独立 Uni-Agent 仓的测试不是同一环境 |

交接解释了旧构建失败的修复：清理四个已删除包遗留的 lib/node_modules 目录后构建通过。此次只核验记录与日志，没有执行任何清理。

## Session 与转换器实际变化

最新 [types.ts](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/core/session/src/types.ts:86) 为 `SESSION_FORMAT_VERSION = 2`；旧 pin 同文件为 0。新 [Session.create/fromRestore](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/core/session/src/index.ts:484) 区分新建与恢复，constructor 私有；`SessionSeq` 与 `SessionLogOffset` 区分事件位置与边界。存储迁移继续走官方 v0→v1→v2 相邻 catalog。

修复后的 [parseLogicalSession](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.ts:298) 调用 `sessionFormatCatalog.createRestore(rawHeader, {recovery:'strict', validation:'current'})`、逐行 decode、finish；不再自建旧 Session decoder。原始 UTF-8 字节 hash 保留为 traceSha256，逻辑事件已迁移到当前坐标。

[stepAttempts](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.ts:387) 从 `assistant/attempt` 和 `assistant/message` 内嵌 stream 调用 `expandAssistantStream`；成功 message 再通过 BlockAssembler 比对内容。失败 attempt 不会直接成为 SFT 成功响应。

[converter.spec.ts](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.spec.ts:82) 明确测试历史 v0 与当前 v2 恢复后的 request/response 相同；同一旧样例由 27 个事件迁移为 16 个事件。新文件的 trace hash 可以不同，语义等价不代表原始字节或所有 provenance 坐标相同。

### sourceEventSeqs 必须区分三种语义

- v2 `assistant/message` **禁止**持久事件携带 sourceEventSeqs，provider stream 已内嵌；见 [types.ts:432](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/packages/core/session/src/types.ts:432)。不能将“所有事件都删除此字段”当迁移策略。
- `tool/result` 等其他 surface event 仍可带 sourceEventSeqs；它可能绑定实际 tool/call，不应抹掉。
- 新转换器导出的 **SFT provenance.sourceEventSeqs** 在 [converter.ts:459](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/scripts/trace-training/converter.ts:459) 为 `[rawEvent.seq]`，指恢复后的 assistant message 事件，不是旧原始文件 chunk 序号，也不是 Gateway token 索引。

## 当前在线链路为什么不被离线修复阻塞

[Uni-Agent runner.py](../../uni_agent/agents/dsh/runner.py:72) 用 `DeepSeekHarness/DeepSeekHarnessConfig`，调用 `harness.run(..., session_id=...)`，从 `result.events` 构造独立 canonical JSONL。它不读取 DSH session.vN 物理文件，也不调用 scripts/trace-training/converter.ts。

直接用 Python AST 比对 pin 与当前 DSH HEAD，`python/sdk/src/deepseek_harness/` 下 `api.py`、`client.py`、`models.py`、`__init__.py`、`errors.py` 全部 AST 相同；看到的 Python diff 是格式调整。这支持现有调用签名不必为离线 converter 修复改变，但 runtime 发出的事件形状仍须升级实测。

[harbor_agent.py](../../uni_agent/agents/dsh/harbor_agent.py:185) 核对 raw trace hash、event_count、身份、终止 turn/end；[trajectory_audit.py](../../uni_agent/tasks/dsh/trajectory_audit.py:116) 同样复核原始字节和事件尾部。两者都没有对 sourceEventSeqs 做离线 SFT 投影。因此 pin 不变时其旧证据不失效；升级生成了新事件/新字节时必须生成新 receipt，不能替换已有 trace 后沿用旧 hash。

Gateway 的真实 token/mask/logprob 是训练事实来源，与 DSH Session v2 的语义事件序号不相同。禁止用迁移后的 sourceEventSeqs 重建或替换 Gateway token。

## ContextPilot 仍是独立风险

当前 DSH 根目录 `packages/experimental` 未包含 contextpilot 三包；专题 `71ca762...` 有 source/fs/runner。它们并未随 converter 修复进入新主线。

- 专题 [training-runner/index.ts:193](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/feat-contextpilot-capability-sft/packages/experimental/contextpilot-training-runner/src/index.ts:193) 先 `sessions.flush(agent.session)`，随后读取 `agent.session.events`；新 Session 公共读取改为 snapshotEvents，这里需要适配及类型检查。
- 同文件 :140 将完整工具表限定为 `edit/read/write`。不能把其成功轨迹直接当作完整 Cordis/DSH 调度验证。
- 专题 [training-source/invariant.ts:145](/Users/gumpm5/Documents/Code/xDAN-DSH-Exp/.Codex/worktrees/feat-contextpilot-capability-sft/packages/experimental/contextpilot-training-source/src/invariant.ts:145) 要求 tool/result 的 sourceEventSeqs 精确指向前一个 matching tool/call；迁移后必须验证新的坐标及同 callId 匹配，不能机械删除字段或将 slice 的下标当绝对 seq。
- 新主线 migration catalog/known event types 中未发现 ContextPilot 专用事件登记。历史插件事件能否通过 strict adjacent migration 尚未验证；未知事件不能擅自丢弃以换取 converter 通过。

## 新版升级必要验收

1. 单独固定新版 source SHA、SDK/runtime wheel hash、平台、镜像 digest；保留当前 7840 lane 作为回归基线。
2. 真正构建新版 wheel，并执行 keyless initialize/shutdown、profile/patch 预检；仓库 pnpm build 不等于目标 Linux wheel 或 Harbor 镜像已验证。
3. 新 SDK/runtime 的真实任务覆盖成功、普通失败、取消/重试、tool/result、内嵌 assistant stream；验证 canonical trace、event_count、session identity、receipt 字节绑定。
4. 离线转换器继续覆盖历史 v0/current v2，保留 original hash + restored version/seq，禁止重写历史奖励关联。
5. ContextPilot 三包在新版独立编译及真实 read/write/edit 轨迹验证，补 snapshotEvents、flush/durability、工具因果 seq 与自定义事件迁移测试。
6. 新 runtime 经 Harbor 独立评分、Gateway 非空 token/mask/logprob、strict admission、一次 GPU update 与独立 reload 后，才可升级默认训练 pin。现有旧 pin 的 198 项组合测试不能代替这一项。

本轮不重跑昂贵构建，不改变当前 M2 实施顺序；最新文档与构建进展已更新认知，runtime 升级仍应独立安排。
