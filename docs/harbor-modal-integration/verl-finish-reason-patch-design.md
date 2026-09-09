# 固定 VERL 结束原因保真：最小可复建修复设计

2026-09-09；设计已获主线程批准，最小实现与CPU回归完成，**尚未部署/未改官方 pin/未操作 GPU**。关联：[在线协议审计](work-state-online-protocol-audit.md)。目标是生产路径准确区分自然结束、生成截断和中止，不以 EOS 审计替代生产准入。

## 1. 已核实的最小故障链

固定 VERL `fefb080262e1c015a0ea05f958822a6a512dc795`：

1. `verl/workers/rollout/vllm_rollout/vllm_async_server.py:681–688` 把 vLLM `finish_reason in ('stop','length')` 都转为 `TokenOutput.stop_reason='completed'`。
2. `verl/workers/rollout/llm_server.py:240` 的普通 `LLMServerClient.generate()` 原样转交该输出，仅补 min/max 版本。当前 sync 的 `trainer/ppo/v1/trainer_base.py:373` 返回这个普通客户端。
3. `FullyAsyncLLMServerClient.generate():444` 虽有预算计数到 length 的逻辑，但**当前 sync 不使用它**，且预算计数也不能恢复 vLLM 当时实际结束原因。不得为了修复而切 fullyasync。
4. 本仓 `uni_agent/gateway/session/codec.py:24` completed→stop；`:495–515` 若解析出完整工具调用则直接返回 tool_calls，甚至会覆盖原始 length。
5. 当前 codec 还把 aborted/abort映射stop，需一并关闭假完成入口。

真实 r1 原NPZ最后一段达16384且非EOS为风险实证；不能从这个现象追填原finish_reason。r2 EOS正证据也不改变上游代码缺口。

## 2. 现有接口能否免补丁

`TokenOutput.stop_reason` 是 `Optional[str]`（`verl/workers/rollout/replica.py:39`），已经能承载 length；Gateway也已有length映射。无需新增数据类型、换训练器、升级依赖或改DSH。

但在当前服务器合并后，普通client收到的对象没有原vLLM finish_reason字段。Gateway/SDK侧不能从已有接口准确找回它。EOS或tokens==max_tokens都只能提供证据/疑点，不能恢复真实原因。

**推荐服务器一行补丁**：将

```python
elif finish_reason in ("stop", "length"):
    stop_reason = "completed"
```

改为

```python
elif finish_reason == "stop":
    stop_reason = "completed"
```

保留原else后，length原样传递；自然stop仍completed，abort仍aborted，其他值仍原样。补丁不触采样参数、token/logprob、奖励、weight版本、uv.lock或trainer调度。可选原始reason日志字段属于后续观测改进，不是修复必需条件。

## 3. 如何锁定补丁身份

| 方案 | 判断 |
| --- | --- |
| 运行时 monkeypatch/修改site-packages后仍记录裸fef | 拒绝：真实执行代码不可复建且manifest误导 |
| 本仓版本化patch + base SHA + patch SHA + patched-file SHA | **本轮推荐**：改动最少，保持官方paired基线，补丁身份显式可复建 |
| 单独维护VERL分支commit并更新gitlink | 可作为长期方案；不是本轮必需。必须记录official paired=fef与effective maintenance SHA，复核源码差异，不声称仍运行裸fef |

推荐新增：

- `deployment/patches/verl/fefb080-preserve-finish-reason.patch`：只上述一行。
- `deployment/versions/verl-runtime-patches.json`：schema、base_revision、patch SHA、目标精确路径及before/after SHA、预期修改文件集合、审查来源。本阶段不填虚构hash，实施生成后固定。
- `deployment/bootstrap/apply-verl-patches.py`：可信本仓工具，仅在**独立新checkout**上工作。首先核HEAD=fef、uv.lock原hash、补丁文件hash与所有目标beforehash；`git apply --check`后应用，再核afterhash和精确diff文件集合。不得使用模糊hunk、自动reset/stash或覆盖未知改动。
- `deployment/checks/verify-verl-patches.py`：只读，判定exact baseline或exact patched；训练目标要求patched，缺失/多改/补丁不符拒绝。重复apply只有精确afterhash才允许幂等返回；半应用拒绝，不自动修补。

**复合版本身份**：`official_base=fef... + patch_sha256 + ordered_target_after_sha256s`，本仓提交SHA绑定实现及部署工具。`g1-source-lock.json.verl_paired_gitlink`继续表示官方基线；`g1-deployment-lock.json`添加明确 `verl_source_overlays`，不能把修改藏在裸 `verl_revision` 后面。新增字段的名字、语义与检查器同时版本化。

## 4. 现有部署需要的精确调整

- `deployment/bootstrap/install-verl.sh:9–15` 当前拒绝任何tracked dirty。保留默认拒绝语义，改为只允许上一步检查器认定的**精确已授权补丁**；所有额外改动仍拒绝。先安装干净fef的frozen环境再应用补丁也可，但每次训练启动仍必须核patchhash。不可仅为了运行放宽dirty检查。
- uv.lock及现numpy overlay不变；此Python源修复无需重装CUDA、重新resolve依赖、重下载模型或重建DSH wheel。
- 现editable VERL import来自checkout，因此必须使用新独立checkout；新进程启动前核真实 `verl.__file__`、目标模块 `__file__` 与patched source SHA。运行中进程已import旧源码，**不能热修改旧run**。
- `examples/dsh/capabilities/prepare_memory_training.py:376,413`：prepared manifest绑定补丁清单hash及effective source identity；`check()`除HEAD外校实际目标afterhash。旧prepare仅核HEAD不足以辨别被patch的同一fef。
- `examples/dsh/ops/write_run_manifest.py:140`：保留verl_sha表示Git HEAD，另记录effective source identity/patch清单hash/实际模块路径与文件hash；不要以新增field冒充旧schema已完成此校验。
- `uni_agent/gateway` 代码所在本仓新commit同样进入manifest；原源码checkout、数据任务、模型与DSH artifact锁定不变。冷启动重建应通过Git拉取本仓→固定submodule→检查/应用patch→受监督新run。旧GPU run与回执保留。
- 如以后采用维护commit方式，installer硬编码fef及manifest/head检查均要改为official/effective双身份；不能只推一个VERL分支却忘记修改submodule锁。

## 5. Gateway生产处理设计

`uni_agent/gateway/session/codec.py::decode_response` 先归一化结束原因，再考虑工具解析：

| backend outcome | 给DSH的处理 | 工具副作用 |
| --- | --- | --- |
| stop/completed + 合法完整tool calls | 原tool_calls | 正常调用 |
| stop/completed + 普通文本 | stop | 无工具 |
| length/max_tokens + 任意文本，包括完整工具块后仍有截断文本 | length，保留原文本作轨迹证据；不恢复/执行工具块 | **不执行** |
| aborted/abort | terminal error/取消语义，不能映射stop | **不执行** |
| 未知/缺失 | 本轮保留既有兼容默认；另阶段设计迁移 | 本次不扩大行为变更 |

最薄落点：length在codec进入parser前返回文本+length，DSH固定runtime会记max-tokens且不执行tool；本轮不改SDK。abort不能伪装length（它是取消而非截断）；建议Session在收到backend abort后使该session进入ABORTED并返回明确非重试的HTTP409，后续同session请求也409。避免codec异常被通用500再驱动retry循环。保留已观察token的审计证据，不提交可训练trajectory；调用abort时避开持有request_lock再次请求同锁。具体异常路径通过actor/session CPU测试确认后实施。

自然stop却含不完整tool标记，是另一项格式有效性问题，不等价于length；本轮至少保留parser rejection证据，不能自动补JSON/补工具动作或假造finish_reason。

## 6. 必须先RED的CPU回归

1. **固定源码函数回归**：从fef原源码提取真实generate方法/关键真实路径，用假的vLLM final_res，无GPU；length在原源码得到completed，patched源码得到length；stop与abort行为保留，tokens/logprobs/版本不变。仅断言patch文本不足以证明行为。
2. **部署复建**：新临时Git checkout，原SHA→apply→check→幂等；错误HEAD、beforehash、patchhash、额外dirty、半应用、uv.lock变化都拒绝且不覆盖；manifest记录effective身份。
3. **codec优先级**：length+完整tool-call、length+完整call后残缺call、length+残缺JSON/文本皆length且parser不执行；stop+完整call原行为；stop+普通文本原行为；abort不返回stop。
4. **actor/Session**：Fake backend返回真实TokenOutput(length)，OpenAI SSE最终length+[DONE]；解析器不存在/异常也不能把length改为500；ABORTED session不继续生成，无工具调用/TQ资格；原请求/真实tokens不被重建。包括取消发生在锁外生成期间的路径。
5. **固定DSH无模型canary**：本地CPU scripted Gateway依次返回length/abort/自然stop；固定Linux runtime仍用于最终canary，验证length不会执行已完整打印的工具块，abort不会finished，普通stop仍完成。若只有Mac wrapper证据，明确不替代固定Linuxruntime。
6. Gateway现有tool解析、连续token/multi-context、DSH Task身份/receipt、memory credit/消费审计回归。不改reward函数，也不把旧r1失败追认为成功。

## 7. 部署验收与边界

先完成CPU与部署补丁身份检查，再从新commit+复合VERL身份启动短小固定诊断；不重跑大量课程来掩盖协议问题。真实运行至少有一例小max_tokens触发length且receipt.finished/eligible=false，和自然EOS正常路径。新manifest应能够由其他机器重新应用同一补丁得到完全相同源码hash。

这不要求训练大课、改模型参数、切fullyasync或Modal。EOS只读审计继续作为补充证据；生产资格必须依靠已修复的结束原因链和原严格Task/verifier。历史报告需标注受旧结束语义影响的范围，原文件不可回写。

## 集成清单接线补充

prepare/check现验证实际VERL复合身份，来源摘要集合包含Gateway源码、overlay模块/清单/patch与run-manifest写入器。`checkpoint_origin`要求母plan、原run和当前有效源码身份一致；新run manifest实际检查`verl.__init__`解析目录，拒绝旧editable导入。历史无overlay的通用run manifest保留兼容读取；新memory准备器要求显式patch，不自动修改源码。新增准备清单漂移、母checkpoint补丁不一致、run记录/声明不一致测试先RED再GREEN，另覆盖实际导入目录错误。模拟checker的recipe测试不替代真实Git补丁验证与固定Linuxruntime/GPU验收。

## 8. 已交付实现与CPU结果

实际落点统一为 `deployment/checks/verl_source_overlay.py`，同时提供 `verify_verl_source(repo, require_patched=True)`、`apply_verl_source(repo)` 与CLI `--repo <VERL-checkout> [--apply]`，取代第3节中分别建议的两个工具。`repo`明确是VERL根目录。默认只读；apply须由operator对独立inactivecheckout明确调用，工具不扫描/证明进程占用，也不自动选择旧checkout。

返回稳定identity：schema/base_revision/overlay_id/state/patch_sha256/manifest_sha256/files；没有机器绝对路径。验证deployment lock授权manifest摘要、manifest授权patch摘要、固定Git原文件SHA、实际after SHA与uv.lockSHA、精确Git status（不允许staged/额外dirty/untracked）。幂等只接受精确已应用状态。旧安装脚本改为调用verify-only，未自动放宽dirty检查或apply。

- patch SHA：`sha256:2cb5eef7dbe70abc553fa002c3d608e6a93954afcdbe3c8e319d5ad1581df436`
- 原vllm_async_server.py：`sha256:a3bc9c92b2182d2d3f0f480535a6cbe14e07fccdd8fbe6d7c68862f17ddb2597`
- 补丁后：`sha256:2a4452e0c5123c8f5ed62961d048cef97c3f1f5234a8be573f2837f4e01e1d75`
- overlay manifest：`sha256:15ecee86c9b4a290ff3a6d62de2c7da5cee995037f45c1f68aeab74deaf81fbd`

`g1-deployment-lock.json.integration.verl_source_overlay`记录上述清单引用/摘要/officialbase及新memory/work-state范围。父线程实现prepare/check与checkpoint_origin/运行manifest对复合identity的绑定，已独立阅读核对：新prepare先验复合source、hash Gateway与patch/checker，mother plan/run/current身份一致，运行manifest还核真实VERL import来源。旧未patch母run不会被默默认可为新身份。

codec在parser前处理length，保留原文本且不生成结构化tool_calls；明确abort直调返回409。Session对最终backend abort关闭会话、返回409，后续请求拒绝，不可finalize成可训练轨迹。FullyAsync client内部恢复流程未动，只有最终送达Gateway的abort触发此门。

先RED：原codec截断仍进入parser；部署module未实现时测试收集失败。实现后26项针对性通过（包括从固定源AST编译**完整generate方法**与fakeengine、临时真实Git checkout apply/check、真实ASGI HTTP/SSE/session）。加入既有bootstrap/continuous token/multi-context回归后**120项通过**。工具解析旧测试文件的一项需要本地不存在的`vllm`包，故该文件完整回归未在Mac通过；不安装GPU依赖，需在Linux既有venv补验。固定DSH无模型canary由独立agent交付，不能拿本文CPU测试替代。
