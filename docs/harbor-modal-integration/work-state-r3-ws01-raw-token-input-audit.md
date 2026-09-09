# r3 WS01 B：原始token输入完整性核验

只读CPU核验完成。目标为 `work-state-train-r3` initial validation 的 WS01-v1-s303，chain `memory-0b8f6cf731284850bf928c390e4d12c7`，B Gateway session `memory-B-16e47a454753487eae4e4ac68e42bca5`。未操作GPU、未改代码/回执、未增加课程。

## 原始输入结论

使用固定 `Qwen3-4B` revision `1cfa9a7208912126459214e8b04321603b3df60c` 的本地真实tokenizer，直接解码 Gateway stage NPZ 中的 `traj0_prompt_ids`、`traj0_response_ids`，以 `traj0_response_mask` 区分生成与工具观察。未调用tokenize或apply_chat_template重新构造“原始”证据。

- 原始prompt为1427 tokens，完整stored actor prompt逐字包含在decode结果中；包括完整reader_goal、准确绝对index.md路径及“先读公开说明和可用memory index”的规则。stored prompt与agent-result envelope也完全相同。
- response区共608 tokens，其中模型生成300、观察/模板308。四个连续生成段的response区间为 `[0,76)`、`[235,331)`、`[405,492)`、`[567,608)`。
- 第一生成段确实请求view本链reader-data/sources/notice.json。其完整真实trace工具结果逐字存在于第一与第二生成段之间的 `[76,235)` 观察段，也逐字存在于第二生成前的1662-token记录输入前缀中；初始prompt不含该结果。
- 观察段实际模板为 `user → <tool_response>完整结果</tool_response> → im_end → assistant`，其后有固定空think前缀。未发现notice结果丢失、错放到第二生成之后或缺少assistant边界。

以上12项检查全部true。该例B没有读取index不能解释为“index提示没进原tokens”或“首个notice结果未进入后续记录历史”。这不意味着模型一定关注/遵守了这些信息。

## 证据与边界

[JSON摘要](work-state-r3-ws01-raw-token-input-audit.json)记录全部检查、生成区间、解码文本哈希以及10份原文件路径/哈希：NPZ、stage metadata、fixture、stored prompt、envelope、trace和四份模型/tokenizer配置。

原NPZ：`/root/runs/work-state-train-r3/agent-logs/step_0/memory-B-16e47a454753487eae4e4ac68e42bca5/trajectory.npz`，SHA256 `93c1fb2a8a478027b77b58b9966365ea308c5add2d443d754e71bca44fea8939`，与stage/crosswalk身份一致。

范围限于这一条已结束的B轨迹。NPZ/mask证明记录下来的连续历史前缀，不是另一次独立截获每次backend HTTP请求；不据此推断所有会话、模型注意力或有效学习。摘要没有保存完整系统提示或凭据，仅保留已知任务路径及模板短片段。训练流程/采样消费与奖励提升仍分别验收。
