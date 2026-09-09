# r3 固定Linux环境协议回归

2026-09-09 13:21:02 UTC+8开始（05:21:02.991538UTC）。固定checkout `/workspace/rebuild/uni-agent-work-state-r3`，集成 `17b6e5589abc8d5a77c6238d0971a129135aa9b7`；VERL官方fef基线+`preserve-finish-reason-v1`精确补丁已显式apply及verify通过。

既有 `/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python`，CUDA_VISIBLE_DEVICES为空，PYTHONPATH指新checkout和其中verl；未安装任何依赖。

`test_message_codec_tool_dispatch.py` 与 `test_terminal_finish_reason.py`：**30 passed，3 warnings，exit0，25.92秒**。补齐本机CPU环境没有vLLM而未能执行的真实解析器导入/HTTP/SSE回归；警告为弃用信息，不是CUDA失败。

原始证据在 `/root/runs/work-state-r3-linux-checks/{pytest.log,junit.xml,result.json}`；pytest.log SHA256 `75ac1492ebe9b287bb711cbbdf460f25cef45ff1e182a9c233ee3ba471c151ca`。只读检查使用独立cache/tmp，未改checkout或GPU任务。

另见[固定DSH实际canary](dsh-finish-reason-canary-r1-result.md)。这些结果验证协议处理，不代表GPU学生完成任务、非零训练梯度、参数更新或能力提升。
