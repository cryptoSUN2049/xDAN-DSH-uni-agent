# CPU 测试环境状态 · 2026-09-13

历史阶段结果 `core-reader-diagnostic-cpu-result.json` 的 898 项通过和 90% 覆盖率仍是有效历史证据。本机当时使用的临时路径 `/private/tmp/uni-agent-cpu-20260907` 目前不再是 Python 虚拟环境：`bin/python` 只是指向系统 Homebrew Python，无法导入 `ray`、`torch`、`omegaconf` 等依赖。

因此本日检查只确认代码/远程分支状态和 shell 语法，没有重新声称 898 项回归通过，也没有用系统 Python 替代锁定环境。不要删除历史 CPU 结果；它们的运行日志和环境范围已写入阶段结果 JSON。

## 恢复复跑

1. GPU 恢复后先检查 `/workspace/venvs/uni-agent-rebuild-cf2d3f5`，并用其 Python 验证 `torch/ray/omegaconf/vllm` 导入和 deployment lock。
2. 若持久 venv 不存在，进入固定 checkout，严格按 `deployment/bootstrap/install-verl.sh` 用 `verl/uv.lock` 重建专用环境；不要直接 `pip install` 浮动版本。
3. 环境验证后，从 `tests/uni_agent/examples/test_diagnose_core_reader.py` 等清单重跑 CPU/真实 verifier 回归，再进行 GPU canary。

本文件不修改任何训练准入，也不改变已保存的历史通过结论；它只标记当前本机无法重现该历史环境。
