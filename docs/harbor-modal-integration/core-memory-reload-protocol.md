# Core 课程独立 reload 协议

2026-09-10，沿用已批准的逐族首题工程验收。本文是执行前协议，未宣称运行通过。母训练须完成且监督exit0；不因step8文件出现就并发加载。选择最终step16，不根据开发题分数挑checkpoint。

## 固定任务

| 家族 | task ID |
|---|---|
| WS01 | work-state-memory-core-v1-ws01-v1-s2001 |
| WS03 | work-state-memory-core-v1-ws03-v1-s2001 |
| WS05 | work-state-memory-core-v1-ws05-v1-s2001 |
| WS06 | work-state-memory-core-v1-ws06-v1-s2001 |

必须在母实验固定checkout中，复用既有venv与VERL overlay。旧evaluate_work_state_tasks.py仍绑定旧课程且按旧ID片段命名，不能只替换任务ID就使用。现有prepare_memory_training支持显式course、evaluation-task-id；逐题新run串行执行即可。

```bash
export PYTHONPATH="$PWD:$PWD/verl"
PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
CORE_RUNTIME="$("$PYTHON_BIN" -c 'from deepseek_harness_runtime import bundled_runtime_path; print(bundled_runtime_path())')"
: "${CORE_MOTHER:?Set completed mother run ID}"
: "${CORE_EVAL_ID:?Set fresh evaluation run ID}"
: "${CORE_TASK_ID:?Set one task ID from the table}"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir "/root/runs/${CORE_EVAL_ID}-data" \
 --run-root "/root/runs/${CORE_EVAL_ID}" --run-id "$CORE_EVAL_ID" \
 --runtime-executable "$CORE_RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family work-state-v1 --course work-state-memory-core-v1 --mode reload \
 --mother-run "/root/runs/${CORE_MOTHER}" \
 --resume-from "/workspace/uni-agent-g1/checkpoint/${CORE_MOTHER}/global_step_16" \
 --evaluation-task-id "$CORE_TASK_ID"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
 "/root/runs/${CORE_EVAL_ID}-data/manifest.json"
```

launch内部执行check，不重复正式目录创建。无论任务得分如何，终态后保留launch退出码，调用check(manifest_path, after_run=True)核source/runtime/母checkpoint摘要，再运行audit_memory_training核唯一A/B、权重版本16及原始B奖励。每题新目录；正常低分或任务失败记录后继续下一题，身份/工件损坏需排查，不吞掉。

## P1与P2边界

四题仅验独立加载与新鲜执行。公开dev不是封存测试；base对照用同任务、同预算的mode val（去掉mother/resume参数）独立运行，可在训练后评估原base，但不得冒称训练前已执行。r3启动前未见封存测试证据；后续新测试只能称评估前冻结，严格训练前封存应在下一次预注册训练前完成。

P2仍缺封存任务入口、真实A工件配对的记忆消融与统计汇总。不能通过手改manifest或复用normal冻结包造消融。WS06无需记忆负例单列；新seed只证明实例变化，不等于结构泛化。后续按goal开展独立增量。
