# Memory constraints r3：A→冻结→B 整链审计

审计范围：固定 `d3084f2a771804f011c4e641ecf0986c7166bc86` 的真实 GPU inference；本次只用 CPU 读取、重新评分。原始结果不重写；reader 结果已独立复验，主线程 finalize 产物 status=passed。

- chain：`memory-constraints-r3`，run `/root/runs/dsh-memory-constraints-r3`。
- `training=false`、`credit_assignment=none`；模型 `Qwen3-4B@1cfa9a7208912126459214e8b04321603b3df60c`。没有 optimizer 更新、SFT 或记忆 RL 训练。
- writer prompt revision `2`；监督结果 282.038 秒、exit 0。监督器通用 reason `training-exited` 在此处只表示推理子进程退出，不能据名称认定发生训练。
- 一个题、一次采样，reward=accuracy=1；fresh / eligible / finished 均为 true；TQ 中同一 UID 的 final/trajectory 回读奖励 1。

## 真实行为与无越权

21 个事件中，模型先调用 `str_replace_editor view` 读取只读 `writer-data/source.json`（seq 9，成功结果 seq 10），再调用 `create` 创建唯一允许的 `writer-data/memory.json`（seq 14，成功结果 seq 15），之后完成回答。共两次工具调用，两个成功结果；没有 source 写入、越权路径访问或拒绝事件。

使用原入口 `_load_manifest` 和 `_stage_result` 独立重验源/输入/运行命令摘要、receipt 自哈希、artifact/trace/session/任务/runtime 身份、新鲜时间窗及 verifier 再评分；全部通过，`unsafe=[]`。另外复算 source 文件摘要与最初 `source_sha256` 一致。完整工具参数及返回值保存在配套 JSON。

## 冻结及 B 可见输入

冻结文件 154 字节，与模型实际写出的文件逐字节相同；事实为 `region=eu-west-test`、`forbidden=public_bucket`。

| 证据 | SHA256（带前缀见 JSON） |
| --- | --- |
| source/source_version | cd7ed8e1fe9e436bf37a552e3e4424dadd06a86dae7edb9ea414c28fe0b2ea47 |
| frozen memory.bin | 31c573ec6efe8d3e52462efa1a66cfdaae7c91874ca704cd28d31a2e0a42da83 |
| frozen manifest.json | 105598915fb9842dd08819b2dc1e34b79b689bf062f93047c8c8bc5f8599e9cf |

冻结 manifest 绑定 chain、source version、writer DSH session；reader fixture 再绑定 writer Gateway session、receipt ID、trace SHA 以及上述两份摘要。独立复算内容、manifest、身份和回执绑定均通过。

实际 `reader/eval.parquet` 只有一条 user prompt，要求读取 question 与 frozen memory。没有拼入 A 的对话、工具历史或最终回答，也没有直接把 facts 答案写进 prompt。expected_answer 位于 verifier fixture，任务 metadata 仅传 fixture 路径/哈希等身份。reader closed policy 只允许读 `frozen/memory.bin` 与 `reader-question.txt`，writeFile=null，bash/pwsh 禁用；writer source 与 fixture 均不在可读白名单。reader 使用独立 homes、artifacts 与 run 目录。B 完成后已核实实际新 session/Gateway 身份均与 A 不同，真实 prompt 与上述准备输入一致。

## Reader 运行观察与边界

Reader 监督 PID `152851` 已 326.049 秒 exit0；真实调用两次 view 分别读 question 和 frozen memory，两个成功结果，无写入或越权。B 最终 JSON 正确包含 status=answer、两项 facts 与 source_version，fresh/eligible/finished/reward/accuracy 全通过。CPU `_stage_result` 独立重验通过；主线程 `chain-result.json` finalize status=passed、reward=1。A/B Gateway 分别以 `7283ac69…`、`ba8b45be…` 结尾，DSH session 同样独立。

Reader dashboard 启动错误已定位：`/tmp/dsh-memory-constraints-r3-reader/ray/session_2026-09-08_19-17-18_712568_152853/logs/dashboard_MetricsHead.log` 报 `AF_UNIX path length cannot exceed 107 bytes`，完整 socket 路径以 `sockets/dash_MetricsHead` 结尾。其后 Dashboard HTTP 缺失是连带现象。后续新 run 使用更短、独占的 RAY_TMPDIR；本次未终止进程，也不因 dashboard 错误判推理失败。

本结果证明固定模板的真实写入与可审计交接成功。提示明确了工具用法，尚不证明模型自主发现 DSH API、跨任务泛化或参数内化；此处已经证明一次 A 写入→冻结→B 新会话读取正确的工程闭环；后续仍需不同任务结构和真正在线 RL，不能由该固定题直接推断记忆能力提升。

## 持久化交付

整链原始数据、冻结文件、轨迹、回执、TQ 产物和日志已归档 `/workspace/reports/dsh-memory-constraints-r3-20260909.tar.gz`，43147 字节、51 成员，gzip CRC 通过；SHA256 `182ba035360c6c7f56fb73763e87fb88ac1ae06fd60a3320c1825ef408256240`。排除可重新构建的 runtime homes，不含 checkpoint。配套 JSON 保存独立审计检查、真实工具证据、最终 chain result 和归档清单。
