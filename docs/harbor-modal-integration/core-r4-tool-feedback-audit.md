# Core r4：重复 create 的工具反馈与组失败审计

2026-09-10，只读检查；没有改变运行、提示、奖励、准入或 GPU 作业。

## 证据身份

- Run：`/root/runs/core-train-r4`，执行 checkout：`/workspace/rebuild/uni-agent-core-511bd71`。
- 首 writer chain：`memory-f5ebe4e661f44f899099e949a4dbb941`。
- Gateway session：`memory-A-bd3ea42810274512a6974fb75380a9f1`。
- 实际 token 归档：`/root/runs/core-train-r4/agent-logs/step_1/memory-A-bd3ea42810274512a6974fb75380a9f1/trajectory.npz`。
- NPZ SHA256：`3c5d8edfe3cff6a1c4398df70a752dedd557451594a4ae143068ca1312b97843`。
- Session 日志：`/root/runs/core-train-r4/chains/memory-f5ebe4e661f44f899099e949a4dbb941/writer/run/homes/436fad0045f9e35eadb5bf31/sessions/--root-runs-core-train-r4-chains-memory-f5ebe4e661f44f899099e949a4dbb941--/dsh-memory-A-bd3ea42810274512a6974fb75380a9f1/session.v2.jsonl`。
- 解码使用本地固定模型目录 `/workspace/models/Qwen3-4B-1cfa9a7` 的 tokenizer，不调用模型生成。

## 实际模型输入与重复行为

NPZ 的 `traj0_prompt_ids` 长 1637，`traj0_response_ids` 长 14747；response 内模型 token 9529、上下文 token 5218。以下索引均为 response_ids **零起点、左闭右开**，不是 Session seq：

| 范围 | response_mask | 解码事实 |
|---|---|---|
| `[1955:2102]` | 1 | assistant 调用 `str_replace_editor`，command=`create`，路径以 `writer-data/memory/modules.md` 结尾 |
| `[2102:2182]` | 0 | user/tool_response 包含 `Error: File already exists ... modules.md. Cannot overwrite files using command create.`，随后 assistant 生成前缀 |
| `[2182:2329]` | 1 | assistant 再次对同一 modules.md 调用 create，内容为 Modules 文件说明 |

Session 日志有 64 条 assistant/message、63 条 tool/result；其中 56 条 File already exists，首次在 step 8、seq 45。此前 step 6 对 modules.md 的 create 已成功。模型知道既有写入和后续工具错误的证据均在实际 token 历史中。

## 执行源码对应关系

`/workspace/rebuild/uni-agent-core-511bd71/uni_agent/gateway/session/session.py` 的实际 SHA256 与运行 `memory-launch-plan.json` sources 一致：

`82f40a83aef76940e907b87caa84d1d3978e03ee2242cacbcf45ee6f17a9ed51`。

- `session.py:489` 将工具增量 token 追加到 response buffer，并标记 mask=0。
- `session.py:503` 以 `buffer.prompt_ids + buffer.response_ids` 构造完整生成上下文。
- `session.py:266` 调用 backend.generate，`:268` 将该 context_ids 作为 prompt_ids 传入。

结论：至少上述重复点，工具错误和前一 assistant 调用都保留到真实生成上下文。证据支持“模型未正确利用错误反馈”，不支持“SDK/Gateway 丢失工具历史”。没有采集 HTTP 原包；结论基于实际 token 归档、Session 记录和哈希匹配的执行源码，不外推所有未检查会话均无问题。

## 一名 sibling 未完成时的实际调度

当前 train 不是任何单题失败就退出整个 job：

1. `framework.py:710` gather 所有 sibling，普通异常先聚合；`:735` 检查 unfinished。`:751` 严格模式整组拒绝，`:758` 写 TQ status=failure，不写任何部分组训练轨迹。
2. work-state stage 准入不通过会在 `work_state/stage.py:281` 抛异常，仍进入以上组隔离；成功 sibling 不能冒充完整组消费。
3. `framework.py:589` 最后确实可能抛 RuntimeError，但 train 的 `entry.py:191` 回落基类 fire-and-forget，`:152` 提交 Ray future 后不等待。因此该 worker 异常不等价于 trainer 主作业退出。val 分支才 ray.get 并传播异常。
4. 实际训练脚本开启 `trainer.v1.sampler.sync_refill_failed_groups=True`。`replay_buffer.py:314` 识别 failure 且无可消费轨迹的 UID，`:434` 清理 terminal 组，`:449` 用 refill_fn 补充 prompt；trainer_base 的 refill 继续通过 agent_loop_manager 提交新组。
5. 主线程真实观测：日志时间 **05:49:07** 首组被拒并清理 TQ，随后第 5、6 条 chain 自动创建并进入下一组，作业仍存活。这与上述源码一致，不是仅凭 raise 文本推断。

边界：失败组不会计入有效训练消费；持续拒绝可能耗尽 wall-time，或触发其他独立错误。当前证据只证明组拒绝后继续补采样，不能据此宣称已有梯度、参数变化或能力提升。
