# Work-state 在线协议只读审计

2026-09-09。范围：本仓 Gateway/DSH adapter、固定 DSH `b2369692ea530007075ebcd18d39fdba0bbd3982`、固定 VERL `fefb080262e1c015a0ea05f958822a6a512dc795`。DSH/VERL 关键结论通过 `git show <pin>:<path>` 读取，不用工作目录最新 HEAD 替代 pin。r1 运行源码为 `801083579318ed5268cc92caf45c3ce04ef6d099`，运行概况来自已有 `work-state-val-r1-result.json/md`；未读取远程请求、未操作 GPU、未更改生产代码。

已读 API 规则替代有效路径：`/Users/gumpm5/Documents/Code/xDAN-Project-Hope-2026/5-Develop/api-structures/API-REFERENCE.md`。规则中的 Codex 首选路径不存在。该文档验证 OpenAI SSE/reasoning 字段，不是 Qwen3 模板正确性的运行证据。

## 结论

1. **没有发现强制 tool_choice=required 或默认清空历史的配置。** 不能据此排除真实 token 渲染问题；要确认每次拒绝反馈出现在下一次 backend 输入。
2. **发现真实上游结束原因损失。** 固定 VERL vLLM server 把 `length` 与 `stop` 合并为 `completed`；Gateway 再转成 `stop`，DSH 可以把截断文本认作 completed。这能解释“残缺 tool_call 文本仍 completed”的可行路径，不能仅归咎模型主动结束。
3. 工具解析还有独立边界：解析到完整 tool calls 时优先回 `tool_calls`，即使原始 stop_reason 是 length；解析不出完整 tool call 时可能保留普通文本。它不强制生成工具，但影响终止与准入事实。
4. 当前没有运行证据证明 r1 的重复调用由历史丢失引起，也没有证据排除它。WS01 改只读源、WS05 混淆业务 config 与 editor 参数仍可能是任务协议理解问题；不能从调用次数直接下结论。

## 实际接线与证据

| 环节 | 源码位置 | 核验结果 |
| --- | --- | --- |
| Stage provider | `examples/dsh/capabilities/work_state/stage.py:97` | sdk-minimal、deepseek-official、reasoning_effort=off；4096 max_tokens_per_turn，max_total_tokens 字段8192 |
| 实际模型地址 | `uni_agent/agents/dsh/agent.py:235`、`runner.py:80` | provider 是协议适配标识；base_url/model 来自注入 Gateway session，非调用外部 DeepSeek。4096经 DSH_UA_MAX_TOKENS→SDK RunConfig |
| DSH wire | pinned `packages/llm/llm-deepseek/src/serialize.ts:342` | OpenAI chat messages/tools、stream=true、max_tokens；off→thinking.disabled；未设置 tool_choice |
| Gateway choice | `uni_agent/gateway/adapters/openai.py:184` | 只接受 auto/none；required/指定函数会明确请求错误，而非悄悄强制工具 |
| Qwen thinking | `examples/dsh/train_qwen3_4b_online_rl.sh:249`、`uni_agent/framework/entry.py:39` | enable_thinking=False 传至 Gateway codec；DeepSeek wire 的 thinking 字段本身不控制 Qwen 模板，真正控制点是这个模板参数 |
| Parser | `uni_agent/gateway/session/codec.py:382,488` | vLLM Hermes，request.tool_choice=auto；恢复完整合法工具块，不完整文本可保留；异常不被伪造成成功工具执行 |
| vLLM stop loss | pinned `verl/workers/rollout/vllm_rollout/vllm_async_server.py:681` | `elif finish_reason in ("stop", "length"): stop_reason="completed"`；返回 TokenOutput 未额外保留原始 finish_reason |
| Gateway stop mapping | `uni_agent/gateway/session/codec.py:24,517` | completed→stop；aborted/abort也映射stop（另一个需要保留语义的边界，未证明r1触发） |
| DSH completion | pinned `packages/core/agent-loop/src/agent.ts:467` | max-tokens→max-tokens；否则消息无结构化tool-call→completed。completed不验证业务产物 |
| SSE | `uni_agent/gateway/adapters/openai.py:82`；pinned `llm-deepseek/src/translate.ts:32` | 返回结构化tool_calls及finish_reason，然后[DONE]；DSH length→max-tokens、stop→stop。没有发现[DONE]缺失导致自动续工具的源码路径 |

## 历史与预算：能排除什么

- pinned `agent-loop/src/agent.ts:353` 每次请求调用 `session.deriveMessages()`；`buildRequest` 最后使用 boundaryMessages。
- pinned `packages/core/session/src/index.ts:799` 从当前 surface 投影已持久化消息；`surface.ts:90` 包含 `tool/result.data.message`。失败 attempt不进入模型历史，tool result 会进入；这是设计区分，不是把拒绝反馈主动过滤掉。
- pinned `llm-deepseek/src/serialize.ts:245` 将 tool-result 转为 role=tool，保留 tool_call_id 与文本。空输出变 `(no output)`，未见普通文本错误内容主动删除。
- sdk-minimal 默认没有 context compaction 插件；独立 work-state patch只关 shell并装文件准入。DSH provider contextWindow默认1,000,000，与本工程 Gateway实际容量不同：不能把这个展示值理解成模型可用上下文。
- Gateway `session.py:405` 从收到的完整messages选择延续链；续接时只追加新消息，但保留旧真实生成token；新增工具/context位置mask=0。前缀不匹配会建新链，不是默认截断最老消息。
- `codec.py:312` incremental encoder使用dummy-user锚定模板差量，源码有“不是所有chat template都适用”的TODO。已有 `test_message_codec_continuous_token.py` 覆盖 Qwen形状，但其中tokenizer是测试替身；不能代替此次固定真实 tokenizer+真实多轮拒绝轨迹的实证。
- 准备器 `prepare_memory_training.py:272` 默认8192prompt+8192response；Gateway `session.py:197` 是每trajectory总容量16384；不是只限制单次生成。`session.py:517` 每次max_tokens=min(请求4096,剩余容量)。真实r1/r2以run manifest解析配置为准。
- DSH adapter只把max_tokens_per_turn传SDK；8192的max_total_tokens不是另一个已实施的DSH累计计数器。频繁短调用可累积数十轮直至Gateway容量或外层timeout，源码没有work-state 3次相同拒绝自动退出门。
- 容量已耗尽：Gateway直接返回空content/length；这一路不经过vLLM因此仍可正确产生DSH max-tokens。容量将耗尽的最后一次实际生成则可能被上述VERL length→completed吞掉，二者须区别。

## 请主线程取得的最小实证（不需要再跑模型）

1. r1 WS01首次拒绝前后、连续两次拒绝间的原 request消息数、role/tool_call_id、错误反馈文本是否出现、usage input/output token数。只提取任务公开allowlist与错误，不读取凭据。
2. 以原NPZ prompt_ids+response_ids、response_mask分段复原实际backend上下文；检查拒绝串及source观测是否存在于下一生成段之前，并核 Qwen turn boundary。用真实tokenizer、不要重新tokenize拼接冒充原始输入。
3. WS05 A最后生成：usage prompt/completion、实际请求max_tokens、剩余trajectory容量、原vLLM finish_reason若日志留存。只因tokens碰上限可标“疑似length”，不能据此补造原reason。
4. 各stage实际Gateway链数、rollback_count、每段上下文长度。若链重建频繁，核 prefix comparison/canonical tool argument差异；若单链增长且反馈确在原token输入，才把反复无效动作归类策略行为。

## 最短修复方向（设计建议，未实现）

- 优先保留backend真实finish_reason到可审计字段，由本项目集成层准确传递length/abort；不要以字符末尾或tokens数量猜测并重写旧回执。若固定VERL不可提供原值，需要明确的受控补丁/版本化集成，而非声称原pin无变化。
- codec只有真实自然stop且完整有效工具块才应优先tool_calls；length/abort应保持未完成语义。应加“完整调用+后续截断”“不完整调用+length”“自然stop文本”的CPU回归再部署。
- 原r1 WS05 A/B eligible目前不能被此审计追认为有效完整执行。先核实该实例是否发生截断；无法恢复原reason时保留证据不确定性。业务reward0并不弥补finished事实损失。
- prompt revision2可改善角色/业务输出理解，但不能替代协议修复与真实历史核验；不增加第二个Agent Loop、不放宽安全门、不借此扩训练量。

## 后续已授权只读 EOS 审计（2026-09-09）

新增 `examples/dsh/capabilities/audit_memory_generation_boundaries.py` 与 `tests/uni_agent/examples/test_memory_generation_boundaries.py`，不修改上述固定上游或资格/奖励代码。

合同：先运行原独立消费审计（含原始trace/receipt、NPZ摘要、真实权重版本、frozen/unpacked及输出快照）。仅消费已证实组进入token检查；原run尚运行时可报告该组observations，整体passed仍需原run completed且全消费审计通过。按原response_mask连续1段标注实际生成区间；区间数必须等于version_evidence.generation_count，否则拒绝声称边界已识别。不能用无context分隔的连续生成猜测两个末尾。

模型EOS来源必须显式配置路径+预期SHA，解析vocab_size和eos_token_id；如传generation_config，其EOS作为有效配置覆盖model config，二者文件均绑定摘要。命令行EOS集合必须与有效配置完全一致。source绑定属于operator提供的模型配置，不冒充与checkpoint权重的内生密码绑定。容量也显式记录operator-declared。

每个区间只报告原末token、是否EOS、是否恰好到容量、EOS/容量tie；original_finish_reason始终null。非EOS是“不确定”，不能推成length；EOS与容量tie保留原终止优先级未知。无EOS、无消费、配置/原证据异常、缺生成段都不passed。禁止覆盖已存在输出，原回执不动。

```bash
CUDA_VISIBLE_DEVICES='' PYTHONPATH=.:verl python -m examples.dsh.capabilities.audit_memory_generation_boundaries \
  --run-root /root/runs/work-state-train-r2 \
  --memory-root <该run的controller-chain-root> --run-id work-state-train-r2 \
  --model-config <固定模型>/config.json --model-config-sha256 sha256:<核定摘要> \
  --generation-config <固定模型>/generation_config.json --generation-config-sha256 sha256:<核定摘要> \
  --eos-token-id 151645 --capacity-tokens 16384 --output <全新audit.json>
```

退出0仅表示该消费集合所有可核定生成段有EOS正证据；退出1保留未通过报告。配置不合法直接报错，不生成成功报告。CPU集成使用真实Task/verifier/freeze/原TQ排布及模拟模型/消费行，仍不等于新增GPU训练证据。

验收：先RED确认缺少新模块；实现后新19项通过（含实际work-state CPU证据链、running部分消费、非EOS、未消费、NPZ篡改、模型hash/EOS集合错误、generation_config覆盖、连续mask分段与计数不匹配）；与原work-state消费8项组合共27通过。最后配置改为解析已校hash的同一raw bytes后19项再次通过。Ruff check/format、diff检查及CLI help通过。未联网、未修改GPU运行或历史回执。
