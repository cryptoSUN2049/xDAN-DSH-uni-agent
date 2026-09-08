# DSH 依赖恢复任务：严格 verifier 补强设计

状态：**仅设计，未实现、未启动任务**。2026-09-08；基于本仓 v3 live projector/rubric 和固定 DSH `b2369692ea530007075ebcd18d39fdba0bbd3982` 的源码。保留历史 v1 任务与结果，新合同使用独立 task/version/verifier 身份。当前 runtime-grounding baseline 不依赖本设计交付。

## 目标与第一批任务

让 Agent 发现并修复真实 DSH Plugin 的依赖配置，在同一 Plugin 下发布新 Package，验证功能恢复并释放资源。验收对象是实际生命周期与功能；输出字符串 `passed`、最终回答和调用次数均不能独立构成成功。

第一批限定 Host-only、单 Session、单目标 Plugin、一次修复版本；允许必要的只读发现/诊断。公共输入给出有故障的 Plugin 源码、预期工具 API 和允许修改范围，不给缺失服务的诊断结论、正确替代依赖、修复源码或调用顺序。Agent 用当前 runtime 接口自行发现原因。未知 provider 的名字可以存在于故障源码中，它是待诊断输入，不是修复答案。

功能任务建议采用“恢复一个根据当前工具注册信息回答查询的诊断工具”，而非无参数 `recovery_probe() -> 'passed'`。公共 API 定义查询参数和输出结构；预期值由独立 verifier 从可信 runtime inventory 计算。冻结正确的功能主体，只允许修复公开声明的依赖配置位置和非功能元数据，避免模型把工具改成常量返回。控制器使用公开模板的可编辑槽重建源码并比较字节，不用脆弱的字符串搜索推断任意 JavaScript 语义；这是一项有明确修复面的依赖任务，不声称通用程序修复。

至少两个不同查询输入，其中一个结果非空、一个边界结果；输入和工具清单随独立 case 改变。测试输入在修复 Package 源码固定后由可信 controller 给出；Agent 调用真实工具，controller 计算答案但不提供期望输出。仅回传输入、让模型“算出正确 JSON”仍不能代替工具实际运行。若无法提供该小型功能 oracle，任务保持 blocked，不能退回固定 `passed`。

## 现有代码的真实缺口

| 来源 | 当前行为 | 缺少的证明 |
| --- | --- | --- |
| [projector `_waiting_for`](../../examples/dsh/evolution_v3_live_verifier.py#L225) | 合并所有 self-inspect 的 waitingFor | 未绑定目标 Plugin/Package、事件时点 |
| [projector `_defined_plugin_ids`](../../examples/dsh/evolution_v3_live_verifier.py#L239) | 从调用参数或 define 文本收集 Plugin ID | 失败定义也可能被计入；不建立 Package 所属关系 |
| [projector `_diagnostic_recovery_observation`](../../examples/dsh/evolution_v3_live_verifier.py#L253) | 任意 update 调用 + waitingFor + 固定 probe 文本 | 未验证 update 成功、先后顺序、同一实例、最终状态或清理 |
| [rubric `_diagnostic_recovery`](../../examples/dsh/evolution_v3_verifier.py#L92) | 比较四个聚合字段 | `correction` 是 projector 推导的标签，不是独立修复证据 |
| [结果提取 `_tool_results`](../../examples/dsh/evolution_verifier.py#L125) | call ID 对应最后一个结果，输出无事件位置 | 重复结果覆盖、孤立结果、结果先于调用无法被严格识别；顶层 error 也需核验 |
| [现有 recovery 单测](../../tests/uni_agent/tasks/test_dsh_evolution_v3_live_verifier.py#L212) | 人工构造简化文本 `running/stopped/removed` | 不是当前 DSH 的完整实际返回格式，不能作为真实协议样本 |

现有 envelope/trace/fixture/scenario 摘要检查继续复用，但摘要相等只证明字节身份。原始 SDK trace 和 controller ledger 必须在 actor 不可写的位置，并与该次执行的会话、runtime 和 task release 绑定。

## 固定 DSH 的返回语义

源码：DSH `packages/extensions/tool-cordis/src/index.ts`（`b236969`）。以下是已读源码事实，不是本批运行结果。

- `cordis_define`：152–240 行。成功 render 是 `Defined P/Q (name); it is not running yet. Use cordis_run to activate this Package.`；定义不会启动或改变 current 指针。
- `cordis_run`：244–328 行。render 输出 `P/Q is running (R).`，或 starting / awaiting approval。**running 文本不证明 Host 已脱离 waiting**；execute 的结构化结果可含 `host.status=waiting`。Host-only 本批不接受 starting/approval 为成功。
- 配套 `cordis-host-runner/src/index.ts:981-1005`：`commitActivation` 即使 Host waiting 也设置 current=本次 Package、删除 next；attempt 状态仍为 waiting，而 `runResponse.status` 返回 running。因此 Q0 的 current/activeRun 可以成立，同时依赖仍未满足。
- `cordis_inspect_self`：99–147、462–497 行。精确 Package 输出 `mode=package`、`plugin.pluginId`、`packageId`、`plugin.currentPackageId`、`plugin.activeRun.{packageId,pluginRunId}`、`runtime.state`、`runtime.host.{status,waitingFor}` 和 `code`。以这些字段关联实际状态。
- `cordis_stop`：333–349 行。成功文本为 `Dynamic Plugin P is stopped; its definition and versions remain.`。停止后保留 current/version 指针是正常行为，不应要求这些字段消失。
- `cordis_undefine`：355–379 行。成功文本为 `Removed dynamic Plugin P and all of its Packages.`。其实现可自动 stop；本任务公开要求显式 stop，以单独验收停用与删除两个动作。
- 无参数 self-inspect 返回 `mode=plugins, plugins=[...]`；这里只证明当前 Session 的动态 Plugin inventory，不能扩大为 OS 进程、其他 Session 或 GPU 已清理。

SDK trace 若仅保留 model-facing 文本，按固定版本的完整 render 语法解析 define/run/stop/undefine；拒绝未知格式，不使用子串“包含 running”判通过。不要假设 trace 已携带内部结构化 receipt。精确 Package self-inspect 的 JSON 用严格解析；实际兼容情况由下一批真实 oracle trace 固定后确认。

## 顺序与身份合同

每个证据节点记录 `trace_sha256 + event_index + callId`。`event_index` 是已验证 trace 字节中的顺序，不把 SDK 事件包装误当 Session v2 的 `logOffset`。解析时保留 call 和 result 的位置；每个有效 callId 恰有一个匹配结果，所有后继依赖前驱的**结果**已出现。

```mermaid
flowchart LR
  B[初始 inventory] --> D0[定义 P / Q0]
  D0 --> R0[运行 P / Q0 / R0]
  R0 --> F[精确诊断 Q0 waiting]
  F --> D1[同 P 定义新 Q1]
  D1 --> R1[update 到 Q1 / R1]
  R1 --> H[精确诊断 Q1 running]
  H --> V[多输入真实功能验证]
  V --> S[stop P]
  S --> SI[停止状态和工具撤销]
  SI --> U[undefine P]
  U --> E[终态 inventory]
  E --> T[完整 turn/end]
```

| 阶段 | 必须满足的事实 |
| --- | --- |
| B | 新建隔离 Session；初始 self inventory 为空，目标工具名不在初始 Tool inventory。保存基线工具 schema 摘要；controller 冻结公共故障源码与允许修改范围。 |
| D0 | 成功 `define(kind=new)` 返回唯一 P/Q0；定义的 Host 源码与公开故障输入一致，Client 半边不存在。不使用 actor 自报 ID 作为身份起点。 |
| R0 | `run(P,Q0,mode=run)` 的成功返回绑定 P/Q0/R0；这是成功建立 waiting 实例，不要求 tool error。 |
| F | R0 结果之后的 `inspect_self(P,Q0)` 成功；响应身份与参数、D0/R0 一致；current/activeRun 指向 Q0/R0，Host waitingFor 包含 fixture 的故障依赖，Host status=waiting。记录真实 schema 所允许的顶层状态，不能凭文本猜测。 |
| D1 | F 结果之后，成功 `define(kind=existing, pluginId=P)` 返回 Q1，且 Q1≠Q0；只有公开可编辑槽变化，功能主体和保护约束不变。未新建第二个 Plugin，未覆写/删除 Q0。 |
| R1 | 成功 `run(P,Q1,mode=update)` 返回 P/Q1/R1，R1≠R0。错误结果、starting、approval、其它 P/Q 的成功不能替代。 |
| H | R1 结果之后成功 `inspect_self(P,Q1)`：响应 P/Q1，current=Q1，activeRun=Q1/R1，state=running，Host status=running，waitingFor=[]；next 不得指向另一待激活版本。inspect code 与成功 D1 定义一致。 |
| V | 在 H 与 stop 之间，调用目标工具完成至少两个冻结查询，call arguments 与 case 输入相符，成功返回符合公开 schema，并逐项匹配独立 inventory oracle；绑定本 Session。初始不存在该工具、唯一本批 P、无中间替换/停用/重定义动作，共同限定生效区间。不能仅靠函数名宣称存在直接 owner receipt。 |
| S / SI | 对 P 的显式 stop 成功；之后 inspect P 的 state=stopped、无 activeRun/未决 approval，Q0/Q1 定义仍存在且 current=Q1；之后的真实 Tool inventory 不再含目标工具，保护工具 schema 与基线一致。 |
| U | SI 结果之后对 P undefine 成功，返回 P；不能 undefine 其它对象、靠 Session 重启或 controller 强制清理代替 Agent 动作。 |
| E / T | U 结果之后无参数 self-inspect 得到空动态 inventory，Tool inventory 与基线一致；直到完整 turn/end 不再有 mutation/candidate 调用。DSH result 同一 session、finished=true、trace hash/event count 一致。 |

上表是有依赖关系的部分顺序；允许额外只读 discovery，不要求毫无诊断的唯一固定调用脚本。首批仅一个恢复版本；后续允许多次尝试时，需显式扩展状态机和预算，不能用“找出任意一段成功子序列”忽略中间破坏。

保护范围内不允许第二个 Plugin、Client 代码、Shell/子进程、写文件、覆盖控制器/检查器或更改保留工具。检查全部调用而非只检查上述证据子集。工具执行错误若属于完整的模型失败轨迹，记为任务失败；不要从统计分母抹去。

## 评分与证据输出

保留现有 hash-bound task envelope、runtime/version、raw trace、scenario/public fixture、verifier code identity。新增严格有序解析器返回每个阶段的证据定位和解析出的 P/Q0/Q1/R0/R1，功能检查逐例列出输入及实际/期望值摘要，清理检查单独列出。

- `evidence_valid=false`：摘要不匹配、关联冲突、重复 call/result、原始 trace 缺损、未知返回协议、controller 状态缺失等；不给可训练奖励，记录明确 exclusion reason。
- `evidence_valid=true, task_passed=false, reward=0`：完整真实轨迹中，模型未恢复、调用失败、选错实例、漏清理、超公开预算或功能测试不通过。保留到评估分母；是否用于训练由独立准入合同决定。
- `task_passed=true, reward=1`：所有身份、时序、功能、保护和清理门均通过。原 v1 `expected_retry='passed'` 不能提升为此状态。

首批仅 eval，`training_eligible=false`；连续评分、GRPO 组内方差和 credit allocation 不在此补强范围。Agent 清理与宿主 cleanup 分别记录，controller 兜底清理不能把失败改判通过。

## 负例矩阵与真实验收

以下先用可审计的最小 trace 单测证明拒绝，再用真实 DSH oracle 记录固定协议；合成 trace 通过不等于 runtime 已执行。

| 类别 | 变体 | 预期 |
| --- | --- | --- |
| 身份 | waiting 来自另一个 P 或 Q | 无法组成目标链，失败 |
| 身份 | 更新另一 Plugin；新建第二 Plugin 冒充修复 | 失败 |
| 身份 | Q1=Q0；用 mode=run 冒充 update | 失败 |
| 身份 | define 参数 P 与返回 P 不同；重复/孤立/冲突 callId | 证据无效 |
| 时序 | 先 probe 再 update；先 update 再观察故障 | 失败 |
| 时序 | 下次调用先于所依赖的 tool result；result 先于 call | 证据无效 |
| 时序 | 正确子序列之间夹入 stop/rollback/redefine | 失败，不跳过破坏节点 |
| 错误 | update 有 tool error，文本仍含 running；顶层 error 非空 | 失败 |
| 状态 | run render=running，但精确 inspect 仍 host waiting | 失败 |
| 状态 | starting / awaiting-approval / current=Q0 / activeRun 错 R | 失败 |
| 状态 | 去掉依赖但没有注册目标工具；伪造最终回答 | 功能失败 |
| 功能 | 任意输入均返回 passed；只回放第一输入答案 | 功能失败 |
| 功能 | 改写冻结功能主体、硬编码样例或篡改 oracle | 失败或证据无效 |
| 功能 | probe 输出来自初始同名工具或第二个 Plugin | 生效区间/初始状态检查失败 |
| 清理 | 漏 stop、stop 失败、停止了错误 P | 失败 |
| 清理 | stopped 后仍可见候选工具；保留工具被移除 | 失败 |
| 清理 | 漏 undefine、删除错误 P、版本定义仍在 | 失败 |
| 清理 | 删除前的空 inventory 被拿来作终态；终态之后又 mutation | 失败 |
| 清理 | 通过重启 Session 或 controller kill 获得空 inventory | 失败，不借清理掩盖行为 |
| 完整性 | trace/fixture/runtime/scenario hash 改动、跨 Session 拼接、无 terminal event | 证据无效 |
| 合法负例 | 未找到修复或完整结束但功能错误 | 记录 reward 0，保留分母 |
| 合法正例 | 正确恢复，额外只读查询，实际多输入功能通过，再完整清理 | 通过 |

下一批真实运行至少包括：可信 oracle 正例、无修复负例、常量 probe 负例、漏清理负例；每例隔离 Session，保留失败产物，无模型自动重试。首次真实 trace 需要确认 render/inspect 字段与固定源码一致，尤其 waiting 首次激活的 current/activeRun；若不一致先校准协议并固定版本，不能放宽为任意文本匹配。

## 下一批最小文件与接口范围

| 拟修改/新增位置 | 责任 |
| --- | --- |
| `examples/dsh/diagnostic_recovery_verifier.py`（新增） | 独立 v2 状态机、有序 call/result 解析、对象关联、功能与清理门；不悄悄改变历史 v1 分数。 |
| `examples/dsh/fixtures/diagnostic-recovery-v2/`（新增） | 无修复答案公共源码/API、controller-only case 与功能 oracle；保持物理隔离。 |
| 新单项 eval 入口中的 diagnostic 分支 | controller oracle 输入与结果、runtime/任务/工具身份冻结；继续使用已验证的新 DSH 执行路径，不调用硬编码旧 pin 的八类 smoke launcher。 |
| `tests/uni_agent/tasks/test_diagnostic_recovery_verifier.py`（新增） | 上述正负矩阵；回归旧 v1 评分不变。 |

拟议纯验证接口：输入 `scenario_contract + trusted_controller_evidence + raw_trace + finished_result`，输出 `evidence_valid / task_passed / reward? / reasons / ordered_witness / functional_checks / agent_cleanup`。内部错误不返回成功，未知字段/协议显式拒绝；现有外层任务 receipt 继续绑定这些输出的摘要。

本批不修改 DSH 核心、Session API、ML 版本、ContextPilot 包、训练器或远程环境。任何实现和真实执行均属于下一批；当前只交付设计。
