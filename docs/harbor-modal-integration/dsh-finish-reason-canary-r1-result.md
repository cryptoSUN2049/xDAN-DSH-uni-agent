# DSH finish-reason canary r1：真实Linux四项通过

2026-09-09 13:19:12 UTC+8（05:19:12 UTC采集）。真实CPU canary退出0，四case全部passed；源码checkout为`/workspace/rebuild/uni-agent-work-state-r3`，固定`17b6e5589abc8d5a77c6238d0971a129135aa9b7`。未更改checkout、部署pin或GPU进程。

| 输入HTTP语义 | 固定DSH实际finish_reason | finished | 实际工具调用/副作用 | 结果 |
|---|---|---|---|---|
| SSE stop普通文本 | completed | true | 0 / 无 | passed |
| SSE length普通文本 | max-tokens | false | 0 / 无 | passed |
| SSE length文本含完整可打印tool-call块 | max-tokens | false | 0 / 无 | passed |
| HTTP409 conflict_error | error | false | 0 / 无 | passed |

每case各1次本机HTTP请求，无服务错误；四case均返回真实原事件（trace_available=true）。特别是abort409实际返回DSH error，不是仅根据SDK异常推断，也未把超时当成功。打印tool-call只作为text，不被执行。

## 固定版本与原始证据

- SDK/runtime：0.1.3a2，源码`b2369692ea530007075ebcd18d39fdba0bbd3982`。
- runtime SHA256：`d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`，脚本实际与deployment lock核对。
- 远端报告：`/root/runs/dsh-finish-reason-canary-r1/result.json`，权限0600。
- 原报告SHA256：`cd8a979e05432b0e137e5a208ef1ca45fde0ad223b817b7000ef0a4a1d434af0`。
- 原事件分别在该目录的`stop/events.jsonl`、`length/events.jsonl`、`length-tool-text/events.jsonl`、`abort409/events.jsonl`。回读四文件重新计算SHA，与报告全部相同。
- [本地只读证据JSON](dsh-finish-reason-canary-r1-result.json)保存报告及外层采集metadata；它的文件SHA不同于远端原报告，未伪称逐字节副本。

| 原事件 | SHA256 |
|---|---|
| stop | `88c69b83a6398646edbdc0f0fa5aa4069e266fdea53d99024ce5427ba12a6653` |
| length | `5fe6038945ef74c2446f7aa3b229121c8397df164db848152b7283aea588385c` |
| length-tool-text | `0d9524269ff0423b667ec8b2574633e7a9197a26dc774cacbd986a33ffc4e63f` |
| abort409 | `d3f4851fc360b14d03070738b2b7d19f36d921a5097fb0fe425c6f54623d5344` |

## 实际执行命令

在原GPU服务器SSH登录后，运行的是CPU程序，CUDA_VISIBLE_DEVICES为空：

```bash
cd /workspace/rebuild/uni-agent-work-state-r3
CUDA_VISIBLE_DEVICES='' \
PYTHONPATH=/workspace/rebuild/uni-agent-work-state-r3:/workspace/rebuild/uni-agent-work-state-r3/verl \
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
  -m deployment.checks.dsh_finish_reason_canary \
  --runtime /workspace/venvs/uni-agent-rebuild-cf2d3f5/lib/python3.12/site-packages/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64 \
  --output /root/runs/dsh-finish-reason-canary-r1 \
  --include-abort
```

再次运行必须使用新output目录，脚本拒绝覆盖旧结果。

## 验收范围

真实固定SDK/runtime正确消费模拟HTTP结束原因，包括length文本不执行与409不completed。只使用loopback假模型，不访问外部模型，无GPU推理、真实学生token、奖励、训练更新或RL准入回执。

本报告不证明Gateway已对真实vLLM输出保留原始stop/length，也不追认历史DSH completed为“没有截断”。该上游修复与真实backend验证单独验收，见[协议审计](work-state-online-protocol-audit.md)及[canary设计](dsh-finish-reason-canary-design.md)。
