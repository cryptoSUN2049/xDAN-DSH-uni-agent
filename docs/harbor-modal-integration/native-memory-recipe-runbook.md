# 原生 resident memory：先 val，再 n4 工程诊断

此入口复用固定 DSH 单卡脚本、VERL v1 sync、NativeMemoryFramework。A/B 使用同一常驻 Gateway backend，但独立 session；DSH 是唯一执行 Loop。固定 constraints / updates 两族曾在独立推理中成功，这不证明新 resident 接线或训练成功。

每次一个 family、一条 train 和一条 val 调度记录。二者身份不同但语义相同，属于 `fixed-diagnostic-not-heldout`；不能当泛化留出集。默认 val-only，框架配置仍保留 train n4 / val n1。切到 train 才执行一次 n4 更新尝试。全部 B 同分意味着零 GRPO 信号，应报告消费工程情况，不能制造失败/伪造奖励来宣称学习。

## 固定源码与独立运行身份

本版命令固定已推送的 `c5dacdc7ff90ad7cb15e826b41b0f6748c2139f0`，使用独立 r2 checkout `/workspace/rebuild/uni-agent-memory-resident-r2`。不要在旧 context checkout 或运行中的 checkout 上切版本；若此目录尚未部署，先由部署端从 GitHub 拉取固定提交、创建独立 worktree，并按部署锁初始化 VERL，再执行下文。这里复用既有验收 venv，不等于新环境从零复建已经通过。

旧 [resident r1 失败记录](memory-resident-val-r1-failure.md)保留；该 run 在阶段执行前因 reward worker 句柄保护误判而退出，不能复用其身份或记为新版本已验收。本手册不声明 r2 GPU 已通过。

以下各段在同一 Bash 会话执行。操作者自行设置 `MEMORY_LABEL`（仅字母、数字、连字符、下划线，建议不超过 20 字符）；追加 UUID 避免复制文档时复用历史目录。

```bash
set -euo pipefail
cd /workspace/rebuild/uni-agent-memory-resident-r2
MEMORY_CODE_SHA=c5dacdc7ff90ad7cb15e826b41b0f6748c2139f0
test "$(git rev-parse HEAD)" = "$MEMORY_CODE_SHA"
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
export CUDA_VISIBLE_DEVICES=''
MEMORY_LABEL=my-memory-check
MEMORY_FAMILY=constraints
MEMORY_SUFFIX="$("$PYTHON_BIN" -c 'import uuid; print(uuid.uuid4().hex[:12])')"
MEMORY_BASE="${MEMORY_LABEL}-${MEMORY_SUFFIX}"
MEMORY_VAL_ID="${MEMORY_BASE}-val"
MEMORY_TRAIN_ID="${MEMORY_BASE}-train"
MEMORY_RUNTIME="$("$PYTHON_BIN" -c 'from deepseek_harness_runtime import bundled_runtime_path; print(bundled_runtime_path())')"
```

## 1. 准备、检查并执行 val

```bash
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir "/root/runs/${MEMORY_VAL_ID}-data" \
 --run-root "/root/runs/${MEMORY_VAL_ID}" --run-id "$MEMORY_VAL_ID" \
 --runtime-executable "$MEMORY_RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family "$MEMORY_FAMILY" --mode val
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training check \
 "/root/runs/${MEMORY_VAL_ID}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
 "/root/runs/${MEMORY_VAL_ID}-data/manifest.json"
```

`prepare` / `check` 不启动 GPU；检查实际 checkout/VERL、源与输入 hash、DSH SDK/runtime 0.1.3a2、runtime 字节摘要、模型 config/tokenizer config 摘要和跨 cwd 导入。模型 revision 必须等于部署锁，但 revision 字符串并非外网来源证明；当前只测量清单列出的模型文件。

`launch` 是真实 GPU 启动：清单环境显式设 `CUDA_VISIBLE_DEVICES=0`，不继承上述 CPU 预检的空值；拒绝已有 GPU compute process，创建独占短 Ray 目录及 0700 的 `run/chains`。监督墙钟 val 3600 秒、train 7200 秒，仅停止自己的进程组。可在 tmux 等持久终端运行，在另一 SSH 窗口观察；PID 或显存占用不是验收结果。

## 2. 专用消费 audit：先验收 val，再决定 train

等待监督进程退出后运行；审计命令自身为 CPU，只消费本项目可信产物，不连接 TQ 或调用模型。

```bash
CUDA_VISIBLE_DEVICES='' "$PYTHON_BIN" -m examples.dsh.capabilities.audit_memory_training \
 "/root/runs/${MEMORY_VAL_ID}" \
 --memory-root "/root/runs/${MEMORY_VAL_ID}/chains" \
 --run-id "$MEMORY_VAL_ID" \
 --output "/root/runs/${MEMORY_VAL_ID}/memory-consumption-audit.json"
```

该 CLI 只有 `passed=true` 才 exit 0：要求 run completed、所有 crosswalk 重新核验通过、实际 trainer JSONL 消费与准入 key 完整对应，且无未知/重复/错 reward 记录。审计失败会非零退出；保留日志与失败报告，定位原因后使用全新 run，不能改旧回执来通过。

`passed=true` 只说明执行和消费合同满足，不自动表示 B 答案正确。还要查看链回执的 `terminal_reward`、A/B verifier 回执及真实响应，确认合法读写、freeze、新 B 的检索结果。此 val-only 不更新参数。

## 3. 全新 train run：一次 n4 更新尝试，再审计

确认 val 证据满足本轮目标后执行，勿把下面 train 命令与未审查的 val 自动串起来。它从同一固定 base 模型开始，**不会加载前一个 val 的产物**；默认先 initial val，再一个 n4 train group，更新后再 val。

```bash
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir "/root/runs/${MEMORY_TRAIN_ID}-data" \
 --run-root "/root/runs/${MEMORY_TRAIN_ID}" --run-id "$MEMORY_TRAIN_ID" \
 --runtime-executable "$MEMORY_RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family "$MEMORY_FAMILY" --mode train
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training check \
 "/root/runs/${MEMORY_TRAIN_ID}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
 "/root/runs/${MEMORY_TRAIN_ID}-data/manifest.json"
CUDA_VISIBLE_DEVICES='' "$PYTHON_BIN" -m examples.dsh.capabilities.audit_memory_training \
 "/root/runs/${MEMORY_TRAIN_ID}" \
 --memory-root "/root/runs/${MEMORY_TRAIN_ID}/chains" \
 --run-id "$MEMORY_TRAIN_ID" \
 --output "/root/runs/${MEMORY_TRAIN_ID}/memory-consumption-audit.json"
```

切换 `MEMORY_FAMILY=updates` 时重新生成全套新身份，再走同样步骤。改变代码、数据或参数后也须重新 prepare；准备器拒绝目录复用，check 拒绝源码/输入漂移。此配方没有独立 reload 命令：train 内更新后 val 仍共享当前训练进程，不能冒充新进程 checkpoint reload。

## 证据位置和判据

- `manifest.json`：准备身份、环境、实际 ops argv、source/input/runtime/model 摘要、明确未运行状态。
- `<run>/supervision/train.log` 与 `supervisor-result.json`：真实启动与退出。
- `<run>/chains/<chain>/writer|reader/`：私有 task config、fixture、真实 trace / receipt、冻结记忆。B 不继承 A 对话。
- `<run>/agent-logs/`：stage-only NPZ+metadata，阶段原始 reward/token 不改变。
- `<run>/chains/groups/*/crosswalk.json`：链回执、唯一 TQ key、A 后 B、调度 step 与实际权重版本。仅 producer 对应关系，不能单独证明消费。
- `<run>/chains/groups/*/submission.json`：TQ 写返回；仍非 trainer 消费证明。使用独立 memory 消费审计，不拿旧 DSH v2 audit 假称已通过。
- checkpoint 在 `/workspace/uni-agent-g1/checkpoint/<run-id>`；train 只有一条题/一次更新尝试，可能零优势、零梯度。

先验收 fresh A/B、私有 freeze、新 B 事实正确、真实 logprobs/token/version、组准入和实际消费；参数更新仍需非零学习信号、checkpoint/optimizer 和后续独立 reload 证据。CPU Hydra/from_config 和首 A 目录冒烟不能替代 GPU 验收。
