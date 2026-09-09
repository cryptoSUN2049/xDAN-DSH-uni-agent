# WS07 短课程：实际记忆恢复与原生 RL

本课程独立标识为 `work-state-short-fact-v1`。旧四族 r4 已完成执行闭环但没有有效参数更新；本课程不改变旧结论。目标是用更短的真实 A 保存→B 新会话读取→配置任务，验证有效在线 RL 信号。8 个训练实例、2 个公开开发实例，各只有一个结构，不是大规模能力训练。

## 部署与准备

先按[完整部署指南](native-work-state-end-to-end-runbook.md)固定已推送的完整 Git SHA、VERL overlay、已有 Python 环境与 DSH runtime。不要更新正在运行的 checkout。以下命令在该固定 checkout 中运行；`PYTHON_BIN`、`PYTHONPATH`、`WORK_STATE_RUNTIME`沿用部署指南。每次使用新的运行名。

```bash
set -euo pipefail
: "${PYTHON_BIN:?Use the verified Python environment}"
: "${WORK_STATE_RUNTIME:?Use the pinned Linux DSH runtime}"
export SHORT_RUN="ws-short-train-$(date -u +%Y%m%dT%H%M%S)"
"$PYTHON_BIN" -m deployment.checks.work_state_runtime_canary \
 --course work-state-short-fact-v1 --runtime "$WORK_STATE_RUNTIME" \
 --output "/root/runs/${SHORT_RUN}-canary"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir "/root/runs/${SHORT_RUN}-data" \
 --run-root "/root/runs/${SHORT_RUN}" --run-id "$SHORT_RUN" \
 --runtime-executable "$WORK_STATE_RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family work-state-v1 --course work-state-short-fact-v1 --mode train
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training check \
 "/root/runs/${SHORT_RUN}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
 "/root/runs/${SHORT_RUN}-data/manifest.json"
```

Canary 使用控制器提供的确定性响应检查真实 DSH 工具与评分，不能作为学生模型成功或 RL 证据。训练才使用 GPU 学生策略。训练固定 8 步、同题 n4、step4/8 保存，初始和周期评估关闭。Checkpoint 路径由 manifest 锁定在 `/workspace/uni-agent-g1/checkpoint/<run>/`。

## 判读与独立评估

先按完整部署指南审计实际消费及 checkpoint。必须分别记录合法零奖励、拒绝组、实际独立任务数、非零优势和有限梯度。所有 sibling 同分时 GRPO 没有组内区分信号；不得通过改分、复制正例或筛除合法低分伪造更新。

独立 reload 沿用准备器的 `--mode reload`、`--resume-from`、`--mother-run` 参数，并**同样传入 `--family work-state-v1 --course work-state-short-fact-v1`**。母 checkpoint 必须来自本短课程；旧四族 r4 不得作为短课程母实验。公开开发题用于预定最终评估，不用于挑提示、温度或 checkpoint。具体实验运行名、文件摘要、实际参数变化与评估结果在完成后另行归档；本指南不是已通过声明。
