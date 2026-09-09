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

**执行源码与审计源码分开记录。** 已完成的 `ws-short-train-r1` 及两次 reload 使用 `b47521d`；这个版本的离线 auditor 不理解 VERL validation 将终态 B 分数广播到 A/B 行的语义。重审现有产物使用已修复的 `d4401d3` 或包含它的固定提交，在独立 checkout 中运行 `audit_memory_training`，保留原失败报告。`prepare_memory_training.check(after_run=True)` 则必须在该 run 原执行 checkout 中运行，不能用新 checkout 冒充原源码身份。新实验统一使用包含修复的已发布完整 SHA，prepare 与 launch 保持同一源码。参见[最终 reload 证据](work-state-short-reload-final-result.md)。

先按完整部署指南审计实际消费及 checkpoint。必须分别记录合法零奖励、拒绝组、实际独立任务数、非零优势和有限梯度。所有 sibling 同分时 GRPO 没有组内区分信号；不得通过改分、复制正例或筛除合法低分伪造更新。

独立 reload 沿用准备器的 `--mode reload`、`--resume-from`、`--mother-run` 参数，并**同样传入 `--family work-state-v1 --course work-state-short-fact-v1`**。母 checkpoint 必须来自本短课程；旧四族 r4 不得作为短课程母实验。公开开发题用于预定最终评估，不用于挑提示、温度或 checkpoint。具体实验运行名、文件摘要、实际参数变化与评估结果在完成后另行归档；本指南不是已通过声明。

以下每次只评估一题。第一题终态、GPU释放和母工件复核后，将 `SHORT_DEV_SEED` 改成 `902`、选择新运行名再执行；不要并发启动两个 GPU 进程。

```bash
export SHORT_DEV_SEED=901
export SHORT_RELOAD="ws-short-reload-${SHORT_DEV_SEED}-$(date -u +%Y%m%dT%H%M%S)"
: "${SHORT_RUN:?Set the completed short-course mother run}"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir "/root/runs/${SHORT_RELOAD}-data" \
 --run-root "/root/runs/${SHORT_RELOAD}" --run-id "$SHORT_RELOAD" \
 --runtime-executable "$WORK_STATE_RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family work-state-v1 --course work-state-short-fact-v1 --mode reload \
 --resume-from "/workspace/uni-agent-g1/checkpoint/${SHORT_RUN}/global_step_8" \
 --mother-run "/root/runs/${SHORT_RUN}" \
 --evaluation-task-id "work-state-short-fact-v1-ws07-v1-s${SHORT_DEV_SEED}"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
 "/root/runs/${SHORT_RELOAD}-data/manifest.json"
```

作业结束后执行下列只读检查（若 launch 失败，另开 shell 显式执行，不丢弃失败结果）。`after_run=True` 仍核源码、模型声明、runtime、母 checkpoint 全量摘要，仅允许本次运行目录已经存在。若源/母工件漂移，应先排查；普通任务失败则保留失败报告，继续下一独立题。

```bash
"$PYTHON_BIN" - "$SHORT_RELOAD" <<'PY'
import sys
from examples.dsh.capabilities.prepare_memory_training import check
check('/root/runs/' + sys.argv[1] + '-data/manifest.json', after_run=True)
print('Post-run source/runtime/mother checkpoint checks passed')
PY
export SHORT_AUDIT="/root/runs/${SHORT_RELOAD}/manual-audit-$(date -u +%Y%m%dT%H%M%S)"
mkdir -m 700 "$SHORT_AUDIT"
"$PYTHON_BIN" -m examples.dsh.capabilities.audit_memory_training \
 "/root/runs/${SHORT_RELOAD}" --memory-root "/root/runs/${SHORT_RELOAD}/chains" \
 --run-id "$SHORT_RELOAD" --output "$SHORT_AUDIT/consumption.json"
```

成功单题应为 1 组、2 条唯一 A/B 实际消费、采样权重版本8；任务得分另外报告。失败也可能 exit非0或audit不通过，不得手改文件凑通过。参数与optimizer检查使用[现有审计指南](work-state-parameter-audit-plan.md)，将旧示例RUN_ID替换为本课程母run；step4→8零梯度阶段可能仍受历史动量影响，需要联合逐步梯度与LoRA B初始化证据解释。
