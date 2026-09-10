# Core reader 配对诊断操作指南

2026-09-10。用户已批准实施；本节点交付脚本与 CPU 验证，尚未运行对应 GPU canary。诊断不是训练，不产生 checkpoint，也不消费 TQ 样本。不得用本诊断的提示收益冒充模型参数学习。

## 1. 本次要回答的问题

固定 Qwen3-4B、原业务 verifier 和同一份真实 A 记忆，B 的 reader 提示修订包是否提高恢复任务完成率？每题 1 个 A，成功通过原准入后冻结一次；原/新提示各 4 个独立 B。16 个公开开发任务来自 WS01/03/05/06，每族 seed 2001—2004、variant 1。最多 16 A + 128 B；重复 B 不是独立任务，也不是 GRPO group。

A 没有通过准入时保留失败，不补采 A，不生成假 B。可信零分、拒绝、未完成保留为诊断结果；轨迹、receipt、输入或版本不一致则中止。两条件是角色、index 存在信息和检索指引的组合比较，不是单句指令因果实验。

## 2. GPU 恢复前置

先读 [关机检查点](gpu-shutdown-checkpoint-20260910.md) 和 [项目交接](../../tasks/harbor-modal-integration/handoff.md)。按现有 deployment 恢复持久环境；本命令不安装依赖、不更新源码、不购买服务器。

在 `/workspace/rebuild/` 建立本次提交的固定 checkout，使用 GitHub 拉取代码。记录 `git rev-parse HEAD`，不要直接使用浮动 main 启动。配对 VERL 必须为 `fefb080262e1c015a0ea05f958822a6a512dc795` 加已审阅的 `preserve-finish-reason-v1` overlay；按 deployment 既有安装流程准备，启动门会验证实际源码。旧正在运行的 checkout 不可覆盖。

确认挂载 `/workspace`、旧 venv 的解释器仍可执行、模型与 runtime 存在；检查 `nvidia-smi -L` 和进程归属。MIG UUID 在换机后必须重新选择，不能沿用旧 UUID。脚本拒绝已占用或归属不明的 GPU；不杀其他会话进程。

## 3. 固定环境与准备

以下是远程 Bash 示例。在本次固定 checkout 根目录运行；`DEVICE` 必须改为实际单 GPU 编号或 MIG UUID。旧 venv 路径若恢复后变化，使用已核验的新路径。

```bash
REPO=$(pwd -P)
PY=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
MODEL=/workspace/models/Qwen3-4B-1cfa9a7
RUNTIME=/workspace/venvs/uni-agent-rebuild-cf2d3f5/lib/python3.12/site-packages/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64
DEVICE=0
export PYTHONPATH="$REPO:$REPO/verl"
export DSH_RUNTIME_MODE=exe
RUN_ROOT=/workspace/uni-agent-g1/diagnostics/reader-canary-$(date -u +%Y%m%dT%H%M%SZ)

"$PY" -m examples.dsh.capabilities.diagnose_core_reader prepare \
  --root "$RUN_ROOT" \
  --model-path "$MODEL" \
  --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
  --runtime-executable "$RUNTIME" \
  --runner-python "$PY" \
  --cuda-visible-devices "$DEVICE" \
  --canary

"$PY" -m examples.dsh.capabilities.diagnose_core_reader check \
  --manifest "$RUN_ROOT/manifest.json"
```

`prepare` 冻结模型文件清单/哈希、源文件哈希、HEAD、runtime、解释器、任务与采样参数，保存 manifest 与独立 SHA 文件。只创建准备目录，不创建正式 chains 或 execution 文件。`check` 只检查输入未变化，不加载模型、不声称通过 GPU 预检。模型目录新增生效文件、manifest 修改或源码变化均需新 prepare。

父进程必须使用上述绝对 PYTHONPATH 和 `DSH_RUNTIME_MODE=exe`：真实 DSH 子进程在各 branch 目录运行，相对 `.:verl` 在那里失效。启动前还会 probe 该 Python 实际解析的 SDK/runtime 版本、runtime 路径以及 Uni-Agent/VERL import 路径，拒绝声明版本与实际运行版本不同。

## 4. 启动与观察

```bash
"$PY" -m examples.dsh.capabilities.diagnose_core_reader run \
  --manifest "$RUN_ROOT/manifest.json" > "$RUN_ROOT/launch.log" 2>&1
```

可在 `tmux` 中执行。终端另开窗口观察 `tail -f "$RUN_ROOT/backend.log"`、`tail -f "$RUN_ROOT/launch.log"` 与 `report.json`。不要因 GPU 利用率瞬时为 0 就重启：A/B 之间还有 verifier 与冻结处理。先看是否存在自己的进程和 Session 推进。

本入口拥有一个 localhost vLLM 服务，并通过现有 Gateway/DSH runner 执行真实任务；退出时关闭自己创建的 actor 和进程组。CPU 测试已覆盖关闭逻辑，但真实 GPU 行为仍需 canary 核验。每 stage 最长 1800 秒，累计生成上限 8192 token、单请求 4096，温度 0.7、top_p 0.9。vLLM 上下文窗口 16384、显存比例 0.5。Canary 也执行至多 1 A/8 B，最坏 stage 时间合计 4.5 小时；完整 16 题最坏 72 小时，另有启动及 CPU 开销。这是截止上界，不是预期耗时；先看 canary 实测成本再安排正式运行。

不自动重试或复用 run。中断后保存原目录，换新 RUN_ROOT 重建；旧部分结果不能补采后冒充预先固定的完整比较。若 canary 导致改提示/实现，正式实验使用新版本、新目录，不将旧 canary 混入正式数据。

## 5. 验收与判读

- `execution.json`：实际 runtime/import/VERL 身份、GPU 准入、起止时间与最终状态。必须 complete；出现 aborted 先定位原因。
- `report.json`：逐题 A、各 B 的 task/session/branch/repetition、原 receipt/trace/fixture 路径与 SHA、reward/finished/eligible、bundle SHA。报告部分完成时不将未观察结果算作业务失败率。
- 两条件同题 bundle SHA 相同；每 B 的 gateway session、目录和输出独立。writer 失败不会有 reader 行。
- `paired_tasks` 只包含完整八 B 的题。条件成功率与包含失败 A 的端到端成功率分开。16 题均观察完且配对齐备，才输出最终端到端成功率。
- `memory_view_attempt_count` / `index_view_attempt_count` **仅是尝试次数**，包含失败、文件不存在的调用。实际读到和使用事实必须结合原 trace 中对应工具返回及最终业务输出复核，不能由次数推断。
- `training_consumed=false`、`learning_verified=false` 始终保持。不要将诊断报告导入训练作为完整在线组。

先按 task/family 列出 A 可恢复事实、B 原始结果及新旧差值；WS06 单独作为无需 memory 的负对照。主要指标为每题原/新业务成功率差，再看错误类型和 token 成本。小样本只做描述性诊断，不宣称专家能力或泛化。

## 6. 正式比较与回归训练

Canary 合同通过后，新建 RUN_ROOT，重复 prepare 时移除 `--canary`，冻结全部 16 题，再 check/run。若仍无真实成功路径，保留负结果继续定位，而不是追加全零梯度训练。

如新提示有可重复收益且无边界回归，再审阅如何进入原 A/B 在线训练入口：仍用固定 harness 的训练前后独立评估，核实实际任务消费、组内奖励差、有效梯度、参数变化、checkpoint 与独立 reload。原生 RL 操作与目标见 [active goal](../../tasks/harbor-modal-integration/active-engineering-goal.md)。本指南不替代原训练脚本。

运行后将小型结果报告、输入 SHA 与判断写入 Git；原始 trace/log 保存在 `/workspace/uni-agent-g1/diagnostics/` 并归档，关闭 GPU 前核验备份哈希。不要提交凭据或用旧退出成功掩盖本次未执行。
