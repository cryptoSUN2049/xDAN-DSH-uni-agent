# Memory updates r1：新事实优先的 A→冻结→B 验收

固定 integration d3084f2，复用已验收 venv、DSH SDK/runtime 0.1.3a2、固定 Qwen3-4B。链 `/root/runs/dsh-memory-updates-r1` 已 finalize `status=passed`、reward=1；`training=false`、`credit_assignment=none`。

Writer 288.038 秒 exit0，reader 286.037 秒 exit0（以各自 supervisor-result.json 为准）。二者 fresh/eligible/finished/accuracy/reward 全部通过；CPU `_load_manifest` / `_stage_result` 重新校验来源、命令/输入、回执、trace、session、时间窗、TQ 回读与独立 verifier 评分通过，unsafe=[]。

## 真实任务行为

Source version2 的当前 region=`ap-south-test`，superseded version1 保留旧 region=`eu-west-test`；forbidden=`public_bucket`。Writer 真实读取 source 后，把当前 facts 与精确 source_version 写入独立 memory 文件，未把过期 region 当成当前事实。Reader 新会话真实读取 question 和 frozen memory，最终 JSON 返回当前 ap-south-test、public_bucket 及相同 source_version。

A 工具调用 2 次，B 工具调用 2 次；配套 JSON 保留每次参数与真实结果。source 摘要未变、冻结文件等于模型实际写入字节、内容与 manifest 哈希绑定全部通过。

A DSH session：`dsh-session-sample-0-rollout-0-cdbb46c28fac4d0e9e39bfd24a566cef`。

B DSH session：`dsh-session-sample-0-rollout-0-6e4c1f43584a4ac69a39258c78427e99`。

Gateway 身份亦不同；B prompt 仅有新问题与冻结文件读取指令，没有注入 A 对话历史或最终回答。事实经持久化文件进入新会话，不是在 DSH 外重新包一个 agent loop，也不是把跨会话记忆称为多 context 训练。

## 持久化交付与边界

归档 `/workspace/reports/dsh-memory-updates-r1-20260909.tar.gz`，42335 字节、51 成员，gzip CRC 通过；SHA256 `sha256:d4867f927c416699c885b9da8810b2f6c06fd1fed416001ae30e623441ffcfd4`。包含链输入、冻结文件、原始轨迹、回执、TQ 产物和日志，排除可复建 runtime homes。

加上 constraints-r3，当前是两种固定模板的真实 A→B 工程验收成功。没有梯度或参数更新，也没有封存测试泛化证据；新旧版本显式出现在 source 结构中，结果不能扩大解释为自主冲突发现、任意复杂记忆整理或记忆 RL 能力提升。
