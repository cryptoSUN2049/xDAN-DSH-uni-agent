# Context v2 原生入口

2026-09-09：v2真实训练及独立reload已完成工程验收，实际仅消费2条train题；首步非零任务梯度，第二步同分零advantage。14组消费/数值审计、独立reload4组通过，严格dev准确率0。详见[训练审计](context-v2-train-r1-cpu-audit.md)和[reload报告](context-v2-train-r1-reload-report.md)。v1四题保留独立合同，不能据此宣称学习提升。

## 固定工作目录后准备

在本次精确 Git checkout 内运行，继续使用已验收 venv；不修改部署 pin。以下 run ID 每次更换。模型 pin 仍为 Qwen3-4B `1cfa9a7208912126459214e8b04321603b3df60c`，runtime 二进制 pin 如下。准备器还核验所选 Python 的 SDK/runtime 0.1.3a2 与实际二进制路径、摘要。

```bash
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
export DSH_RUNTIME_MODE=exe
export MODEL_PATH=/workspace/models/Qwen3-4B-1cfa9a7
export CONTEXT_RUN_ID=context-v2-baseline-r1
export CONTEXT_DATA_ROOT=/root/runs/$CONTEXT_RUN_ID-data
export CONTEXT_RUN_ROOT=/root/runs/$CONTEXT_RUN_ID
CONTEXT_RUNTIME="$($PYTHON_BIN -c 'from deepseek_harness_runtime import bundled_runtime_path; print(bundled_runtime_path())')"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_context_training_v2 \
  --repository-root "$PWD" --output-dir "$CONTEXT_DATA_ROOT" \
  --run-id "$CONTEXT_RUN_ID" --run-root "$CONTEXT_RUN_ROOT" \
  --runner-python "$PYTHON_BIN" --runtime-executable "$CONTEXT_RUNTIME" \
  --environment-digest sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb
source "$CONTEXT_DATA_ROOT/training.env"
```

当前共享/workspace文件系统不兑现准备器要求的0700权限，因此准备目录使用/root/runs；结束后把数据/日志归档到/workspace，checkpoint仍直接存/workspace/uni-agent-g1/checkpoint。

产物：`train.parquet` 12 条、`validation.parquet` 4 条、`task.yaml`、`cases/*`、`training.env`、ops 要求的 `manifest.json`。输入/source/runtime/verifier 闭包均有摘要。准备器不创建运行目录、不启动模型。每个 source 必须完整真实读取，协议明确列出要引用的 source ID/行号；答案和 quote 不在 prompt 中。

## 先真实 strict inference 四题

从准备清单对应的精确 checkout 运行以下一条命令。入口读取 `manifest.environment`，覆盖外层相对 PYTHONPATH，并在 verifier 的 data cwd 先核导入/闭包/runtime；实际检查所有输入及 source 摘要后才新建 run root、记录启动清单并调用 owned supervisor。不要预先 mkdir run root，也不要复用旧 run。首次总预算3600秒、单会话最多900秒；结束后仍需按所有权核验独立 Ray/vLLM 后台资源，不能全局清理其他任务。

```bash
PYTHONPATH="$PWD:$PWD/verl" "$PYTHON_BIN" -m examples.dsh.capabilities.launch_context_inference \
  --manifest "$CONTEXT_DATA_ROOT/manifest.json" --model-path "$MODEL_PATH" \
  --concurrency 1 --gpu-memory 0.30 --max-model-len 16384 --wall-seconds 3600
```

配置总生成预算 8192、单轮 2048；训练入口 prompt 预算 8192，engine window 16384。inference CLI 自带 prompt 预算 4096（仍使用同一 16384 engine window），因此报告要记录入口差异，不能假装 token 边界完全相同。这里走 Gateway + TQ 实际 token 和奖励回读，没有 optimizer。

入口记录模型本地配置/tokenizer/权重摘要、完整argv、清单关键环境、cross-cwd预检和代码/输入摘要。部署锁的模型revision与本地字节测量分开标注，不假称重新在线核验了Hub版本。该入口不替代当前正在运行的旧run，也不会自动改旧实验。

四条 dev 是四种不同组合，仅一次采样不证明 GRPO 组内方差。后续先在 train 同题做 n=4 诊断并保留原始分布；当前 strict inference 限 n=1、partition=val，不能直接把 train metadata 换成 validation 来绕过。若用公开 dev 同题重复采样诊断，标为公开开发采样，不叫 trainer 分组验收、不据此宣称盲测泛化。

## 有信号后两步 online RL

重新 prepare 独立 run ID，例如 `context-v2-train-r1`，重新 source 新 `training.env`。不要复用 inference 的 run root。下述调用应继续包在专属 supervisor 中；首轮建议 7200 秒总上限，超时保留失败，不无限重试。

```bash
export MODEL_LICENSE_APPROVED=1
export MODEL_PATH=/workspace/models/Qwen3-4B-1cfa9a7
export VAL_ONLY=False
bash examples/dsh/ops/launch_qwen3_4b_online_rl.sh --foreground \
  "trainer.default_local_dir=$CKPTS_DIR"
```

prepare 默认 `VAL_ONLY=True`，这里显式改 False。sync、单卡、n=4、train batch=1、两步、LoRA16、完整模型/optimizer/extra checkpoint、CPU offload 设置均在 `training.env` 中。checkpoint 进入 `/workspace/uni-agent-g1/checkpoint/<run-id>/global_step_*`。尾部显式 checkpoint override 也写入 ops `command.txt`，避免缩略打印/继承环境遗漏保存位置。

两步只覆盖打乱后的部分 train 题，12 是可用课程数量。必须另外报告实际消费 task ID、组内奖励方差、有效组数、policy version、TQ token/logprob、optimizer step、LoRA 变化与 base 冻结；不能以仅有参数变化替代任务 reward advantage。

## 独立 reload

再次 prepare 独立 ID，例如 `context-v2-reload-r1`；新 source/fixture 绝对路径导致新 artifact hash，题的规则和文件内容保持确定性不变。source 新 `training.env` 后：

```bash
export MODEL_LICENSE_APPROVED=1
export MODEL_PATH=/workspace/models/Qwen3-4B-1cfa9a7
export ROLLOUT_N=1
export TOTAL_TRAINING_STEPS=1
bash examples/dsh/ops/reload_qwen3_4b_checkpoint.sh \
  /workspace/uni-agent-g1/checkpoint/context-v2-train-r1/global_step_2 \
  --foreground "trainer.default_local_dir=$CKPTS_DIR"
```

reload wrapper 设置 `resume_path`、`VAL_ONLY=True`；从父 checkpoint 读取的事实须见运行日志与独立评估证据。仍需另跑完全不改的原 v1 准备器/四题，报告 v1 公开回归准确率。v2 的 `read_coverage`、`semantic_accuracy`、`citation_coverage`、严格 `v2_task_accuracy` 和总 reward 分列。该课程只覆盖文件证据能力，不宣称多 context 或跨会话记忆已训练。

## 后续课程覆盖运行（计划，尚未执行）

当两族记忆工程任务结束、GPU空闲时，可用新run ID在相同固定模型/评分器上覆盖整个12题课程。保持batch1、n4、单epoch，设`TOTAL_TRAINING_STEPS=12`、`SAVE_FREQ=6`、`TEST_FREQ=6`，避免每步保存完整权重占盘；仍使用既有监督器和/workspace checkpoint目录。实际是否覆盖12个唯一task_id，以消费审计为准，不能仅凭配置值宣布覆盖完成。

验收分别记录12题中实际消费数量、48个计划尝试中的有效数量、非零advantage组数、分族奖励/严格准确率、base冻结、optimizer状态及独立reload。组失败或数据丢失不能用补零当完成；连续无信号时先诊断，不能无限重复。此运行扩大已定义课程的实际训练覆盖，仍不等于足够的泛化数据；四题dev保持公开开发身份，不改称封存测试。
