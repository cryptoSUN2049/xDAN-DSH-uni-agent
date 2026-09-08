# DSH 最新版本 / 当前基线 / ContextPilot 专题审计

日期：2026-09-08。只读 GitHub API + 本地 Git 对象；未升级、修改任何仓库，未运行GPU/模型。远端查询快照，不承诺此后不移动。

## 1. 精确身份

| 对象 | 实际查询结果 |
|---|---|
| 当前训练runtime固定 | `7840bced35ee07ebefbdce0106b56dbc00bdc3ef`，package `0.1.2-alpha.1` |
| 官方默认分支 | `master`（并非main；main API返回422） |
| 官方最新master | `c389f96bf3a9b6807cb71ed6bdad5849be0df6d8`，2026-09-07T16:46:19Z，package `0.1.3-alpha.2` |
| 官方最新tag | `dsh-v0.1.3-alpha.2` → `82a5fd61a7cf5c293cec4bdff68f455398d685e9` |
| 官方GitHub Release | `/releases/latest` 返回404；只能声称查到tag，不声称有GitHub Release |
| DSH-Exp远端master | `55ac060e791e8dcb1de144b5ed180cbd11dd3408` |
| DSH-Exp远端official-training | `7840bced35ee07ebefbdce0106b56dbc00bdc3ef` |
| DSH-Exp远端ContextPilot专题 | `71ca762018beebb58635bb4e896ebfbb4c6c2556` (`worktree-feat-contextpilot-capability-sft`) |

来源：
- https://github.com/deepseek-ai/deepseek-harness/commit/c389f96bf3a9b6807cb71ed6bdad5849be0df6d8
- https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.1.3-alpha.2
- https://github.com/cryptoSUN2049/xDAN-DSH-Exp/tree/7840bced35ee07ebefbdce0106b56dbc00bdc3ef
- https://github.com/cryptoSUN2049/xDAN-DSH-Exp/tree/71ca762018beebb58635bb4e896ebfbb4c6c2556

官方与派生base直接GitHub compare返回404，不能据此计算commit领先数。实际使用官方recursive tree（truncated=false）及指定SHA文件，与本地7840 Git blobs逐文件比较；没有猜测共同祖先。派生master相对7840 API显示behind32commits，这些不能全部算runtime功能变化。

## 2. 官方最新相对7840最重要的非格式变化

### A. Session持久化接口、写入所有权和durability合同改变

`packages/session/session-persistence/README.md`：
- 旧：服务级 `create/ensureMaterialized/append/load/inspect`，append承诺durable。
- 新：`create/open/stat/list`，create/open返回SessionHandle，`read/append/flush/close`在handle上执行；writer为进程内排他。
- 新append承诺接受/有序/本backend可见；**flush才是durability屏障**，close负责drain并释放writer。
- 新live事件由已获取writehandle的published session路由持久化；无writehandle的published session不会写入。
- 最新文档仅列shipped JSONL后端；旧文档列JSONL+SQLite。不要混淆session-query的SQLite索引与持久化后端。

对我们：训练证据“Session已flush再snapshot”必须保留；不能直接移植旧persist调用到新版本，也不能用append返回代替持久化验收。

### B. 日志逻辑格式v0→v1及迁移行为

同一持久化文档：旧构建v0且无格式迁移；新SessionHandle只暴露逻辑v1，JSONL支持released v0静态目录迁移；未知事件只有标明ignorable才可能容忍，否则拒绝。自定义ContextPilot事件与导出器均要核对event vocabulary/版本。

对我们：候选runtime升级不能复用旧日志假定无差别；冻结事件schema、导出器、训练receipt身份并做旧日志fixture迁移测试。

### C. 冷读取与中断修复职责变化

新增 `packages/session-query/session-query/src/cold-read.ts`：open(read)→read→close，再在内存附加interruptedTurnClosers；不写回。恢复执行由agent-loop持writehandle追加修复事件。`src/types.ts`新增inheritedEventCount。

对我们：只读历史记忆检索不应改动历史日志；训练导出应分清原始持久事件、内存修复视图和实际执行产生的奖励证据。

### D. Session索引与sandbox状态投影

- `packages/compaction/compaction/src/tool-pairing.ts` / `compaction-tool-result-pruner/src/index.ts`：`session.events[seq]`→`session.eventAt(seq)`；Seq与LogOffset拆分brand。非连续或fork继承语义不能再假定seq等于数组位置。
- `packages/sandbox/sandbox-policy/src/session-mode.ts`：删除从完整events倒序fold的effectiveSandboxMode，改用共享projection状态。隔离mode依旧事件化并可恢复，但调用内部旧helper将破坏兼容。

这些是底层接口/状态管理升级，不是“最新版本才拥有上下文压缩和sandbox”。

## 3. Python SDK对训练adapter兼容性

已实际下载最新指定SHA，并对比7840以下三个文件的Python AST（忽略位置信息）：
- `python/sdk/src/deepseek_harness/api.py`：AST相同。
- `python/sdk/src/deepseek_harness/client.py`：AST相同。
- `python/sdk/src/deepseek_harness/models.py`：AST相同（内容也未变化）。

因此我们使用的DeepSeekHarnessConfig、DeepSeekHarness.run、RunResult/events公开调用面，在此次抽查中没有语义变化。不能扩大为“所有runtime与adapter完全兼容”：底层日志v1、构建包和训练receipt需要实测；此次未下载所有runtime文件/运行SDK。

建议继续7840当前已启动构建，不因发现新tag暂停。后续候选分支比较固定tag与master，先独立CPU构建/SDK接口/日志迁移，再单任务模型验证。

## 4. 7840已经有的真实能力，不必等升级

### 上下文

`packages/compaction/compaction-basic/README.md`（7840）：按token压力自动总结旧历史、保留recent；overflow后压缩重试；`/compact`按需触发；可挂tool-result-pruner先裁大结果。总结增加一次LLM请求，只缩derived history，不缩system/tools/session prefix。默认dsh composition提供不意味着sdk-minimal全部挂载，应核对实际profile。

### 历史检索

`packages/session-query/tool-session-query/README.md`（7840与latest主体一致）：五个只读工具 `session_search/session_event_search/session_trace/session_event_trace/session_event_read`，按exact cwd限制workspace权限；opt-in，shippedhost不默认挂载。不是可写长期记忆库，也不是自动经验晋升。

### 动态Harness

`packages/extensions/tool-cordis/README.md`（7840）：七工具inspect_list/query/self、define、run/update、stop、undefine；immutable版本包、session-scoped可管理，定义仅process memory，restart丢失，不写repo、不安装包、不改cordis.yml。运行包可能影响同进程其他session；VM隔离globals**不是安全边界**。训练必须依赖外层独立任务进程/容器与权限限制。

因此短循环Harness动作已有可用原语；跨任务持久RSI仍需controller验收/晋升/版本管理。

## 5. ContextPilot专题是额外实际代码，不是官方版本功能

`71ca762...` 相对7840，仅packages/python就36files +3915/-19，新增三个experimental包、known-event-types和Python snapshot测试。官方latest tree与7840均无ContextPilot包。

### contextpilot-training-source

`packages/experimental/contextpilot-training-source/README.md`：精确protocol identity、accepted/settled事件、RFC8785 requesthash、failclosed Session exporter。事件log-only，不改模型上下文，不执行context管理，不调teacher/verifier，不启动训练。导出者在`scripts/trace-training/contextpilot-source.ts`；sourceEligible不等于最终训练质量。整Session要求固定完整trusted tool catalog，非只挑子集验证。

### contextpilot-training-fs

`packages/experimental/contextpilot-training-fs/README.md`：真实native文件工具背后的virtual ActorFileSystem，显式seed、readOnly与writableRoots、字节预算；不打开host路径；inmemory map；snapshot返回完整内容，由controller持久化并选择allowlist转移下一阶段。

### contextpilot-training-runner

`packages/experimental/contextpilot-training-runner/README.md`：**真实执行一个新Agent Session**，不是离线fixture生成器。执行前写独立input authority，核对每次provider dispatch的system/toolcatalog/route/budget；等Session idle及flush后snapshot真实文件，写`dsh.context-memory-phase.v2`。要求catalog**恰好edit/read/write三个工具**，禁止其他provider/辅助LLM；controller负责task质量、阶段迁移、最终admission。runner完成不等于任务成功。

### 对M1真实记忆轨迹的直接贡献

可以贡献：DSH真实file-memory操作、公开输入authority、模型请求、文件产物、flush后snapshot与跨阶段controller transfer。这是目前更直接的M1复用候选，无需先升级官方master。
不能直接贡献：全部Cordis动态工具同时打开的完整DSH任务、自动上下文压缩策略、长期持久化经验库、teacher/OPD、GPU训练或完整RSI。三工具严格catalog与完整DSH catalog存在明确冲突，应先保留专用memory校准profile，别删除检查强行拼接。

## 6. 最小迁移建议

1. 保持当前7840构建和原生训练验证独立继续，不追latest。
2. 先建立ContextPilot只读交付清单：fs+runner包、invariant companions、type/runtime依赖、profile/controller、schema、测试；确认source导出是否为当轮M1必需。
3. 在DSH仓独立变更中迁移必要依赖闭包，而非复制完整ContextPilot分支（其文档/编译器/数据资产不可混入训练主线）。固定该DSH候选commit供Uni-Agent调用。
4. 首先运行edit/read/write-only memory校准任务，验authority→request→tool call/result→flush→snapshot→verifier→receipt，双phase只允许选定memory文件转移。
5. 另用7840现有Cordis profile验证动态调度任务；二者训练任务可混合，runtime profile和catalog仍分开记录，不必在同Session开所有工具。
6. 待两类路径稳定，再评审合并能力scope或让模型选择context/Harness动作；同时维护Gateway多chain/token真值。
7. 官方0.1.3候选单独升级评审；必测v0→v1日志、handle flush/close、snapshot时机、ContextPilot已知event、session-query只读行为与Gateway重建context。

## 临时证据文件

- `/private/tmp/dsh-upstream-tree.json`：官方完整tree。
- `/private/tmp/dsh-latest-files/`：精确最新SHA相关文件。
- `/private/tmp/dsh-focused-diff.txt`：初轮聚焦差异。
- `/private/tmp/dsh-persistence-latest.md`：新持久化合同。
- `/private/tmp/dsh-changed-paths.txt`：blob路径差异；大量文档迁移/包版本变动，不作新增能力数量。
