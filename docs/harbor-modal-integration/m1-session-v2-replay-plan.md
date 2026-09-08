# 新版 DSH M1 留出验证：只读核验与待执行命令

2026-09-08。初版只读检查本地源码和现有 Pod，形成下方重放命令；随后获准执行第 1 段 CPU 数据准备，于 **08:02:30 UTC / 16:02:30 SGT** 成功完成。训练与 reload 均未执行。

执行版本更新：上述只读快照发生在 `0b3fc06`；主线程随后确认现有 GPU checkout 已切换到 `c4f9c308e98dd002d491113691416e3ab8736306`，M2 训练 PID `32642` 当时正在运行。下方执行断言使用新的固定 commit。**禁止与 M2 并行启动 M1；先确认 M2 终态和 GPU/Ray 资源已经释放，不能把旧快照中的 GPU 空闲当成当前状态。** 本批 CPU 数据准备未干预 M2。

## CPU 数据准备实际结果

新目录 `/workspace/data/dsh-evolution-v2-b236969` 已创建，准备命令和核验退出码均为 `0`。共 16 条 train、8 条 holdout；24 条 runtime 绑定、新 checkout fixture 路径和 fixture hash 全部通过。两划分 task ID 交集为 0，计划选中的前 4 条 train / 前 2 条 holdout 均为 trim，输入交集为 0。生成后源码仍固定 `c4f9c308...` 且 tracked clean，未修改 venv、运行中 checkout 或任何服务。

| 产物 | SHA256 |
| --- | --- |
| train.parquet | `5e3927a87e8a1296ab0e665c9ca9029d0825096310ec7529570e6a564ac2da04` |
| holdout.parquet | `b4fb8a1eff5e2c9349dcc4d441119919359321766bc75caee7159f31185bc4e7` |
| manifest.json | `1e22ec154e30d1d3394c394b837be6cddcb5067da32ab895058d5347298854d7` |
| preparation-evidence.json | `a0c1571dfce767ea7eedb20208df04f6ad171bbcda685c88c33dbd96609bc77a` |

原始 [数据 manifest](m1-session-v2-dataset-manifest.json)、[准备证据](m1-session-v2-data-preparation-result.json)和[准备日志](m1-session-v2-data-preparation-log.txt)已原样归档。实际 runtime 版本、摘要、7 个生成源文件摘要和选中的 6 个 fixture 记录在证据中。

**后续不要再次生成或覆盖这份数据。** 新 shell 先恢复第 1 段的环境变量并执行版本/runtime 断言，跳过 `mkdir` 和数据生成命令；核对以上哈希后，在 M2 结束并释放资源的条件下进入第 2 段。下方准备命令保留为本次生成的可复建入口，重建必须另用新目录。

## 结论

最短路径是复用现有模型、wheel、venv、固定代码，仅重新生成很小的 Parquet 数据，再重放 M1v3 的 2 次更新和独立 reload。无须重新构建或下载。

必须新建数据目录：`prepare_evolution_dataset.py:199` 把 runtime `environment_digest` 写入每条 seed；`:212` 又把 fixture 绝对路径写入 prompt。旧 `/workspace/data/dsh-evolution-v2-7840` 绑定旧 runtime 与 `/workspace/src/uni-agent`，不能只改 run manifest 后复用。新摘要应为 **runtime executable** 的 `sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`，这里的 M1 本地环境不使用 Harbor image digest。

留出范围明确为 `trim-holdout-01/02`，不参与当前 run 的优化更新。4 个 train 和 2 个 holdout 的 task ID、fixture 均不同，输入字符串交集实际为 0。它们仍是同一 trim 任务族、带实现指导的工程任务，而且已被旧版评估过；不能称为全新盲测或通用 Agent 能力证明。

## 已实查状态（M2 启动前的 0b3fc06 快照）

| 项目 | 只读结果 |
| --- | --- |
| 旧训练 / reload | `/workspace/runs/dsh-m1-v3`、`dsh-m1-v3-reload`，两份 `exit-code=0`，manifest 均记录 DSH `7840` |
| 新 checkout | `/workspace/rebuild/uni-agent-g1-v2`，`0b3fc06760cc133a98fc3c495c2b7c5f2c882717`，tracked clean |
| VERL | 新 checkout 内 `fefb080262e1c015a0ea05f958822a6a512dc795` |
| 新 SDK/runtime | 指定 venv 中均 `0.1.3a2`；实际 bundled executable SHA 与上文一致 |
| venv | `/workspace/venvs/uni-agent-rebuild-cf2d3f5`；目录名是历史标签，当前已升级 |
| 依赖 | NumPy 2.3.5、torch 2.11.0+cu130、vLLM 0.24.0、transformers 5.5.3、Ray 2.55.1、pyarrow 24.0.0、datasets 5.0.0、PEFT 0.19.1 |
| 模块来源 | 显式 PYTHONPATH 下 `uni_agent` 和 `verl` 均解析到新 checkout，transfer_queue 来自该 venv |
| 固定模型 | `/workspace/models/Qwen3-4B-1cfa9a7`，历史 revision `1cfa9a7208912126459214e8b04321603b3df60c`；本次实查 config SHA `8ba006f74fecfaaeb392872a60f4a480e7ec9860153d2e1b769ec81f9a147f8a` |
| 源文件比较 | scenario、verifier、patch、task YAML、训练脚本、数据转换器和选中的 6 个 fixture，与旧 checkout 字节一致 |
| GPU | 此次 `nvidia-smi --query-compute-apps` 为空；启动前必须重查，避免与 M2 同跑 |
| 新目录 | 计划数据目录和训练目录在本次检查时均不存在 |

旧 `resolved-launch.json` 和真实日志确认：LoRA rank/alpha **16/16**、`save_lora_only=False`、PPO minibatch=1。旧 `command.txt` 明确 `LOW_VRAM=1`（启用）、`ROLLOUT_LAYERED_SUMMON=False`、`ROLLOUT_ENFORCE_EAGER=True`、`ROLLOUT_FREE_CACHE_ENGINE=True`、`ACTOR_PARAM_OFFLOAD=True`、`ACTOR_OPTIMIZER_OFFLOAD=True`、vLLM CPU offload=0；下方均显式保留。旧 `command.txt` 未列出继承的 LoRA 变量；仅复制这份命令会退回启动器的 rank 4，不能算同预算重放。

旧训练实际选择前 4 条 train、前 2 条 holdout，shuffle=False，batch=2，2 steps，train n=4，val n=1，并发1，8192 prompt + 1024 response，GPU memory 0.30、vLLM CPU offload=0。训练前基线与每步留出评估由现有脚本 `trainer.val_before_train=True`、`TEST_FREQ=1` 提供。

## 1. 固定输入并准备新数据（在现有 Pod 的同一 shell）

```bash
set -euo pipefail
export M1_REPO=/workspace/rebuild/uni-agent-g1-v2
export DSH_VENV=/workspace/venvs/uni-agent-rebuild-cf2d3f5
export PYTHON_BIN="$DSH_VENV/bin/python"
export PATH="$DSH_VENV/bin:$PATH"
export PYTHONPATH="$M1_REPO:$M1_REPO/verl"
export PYTHONDONTWRITEBYTECODE=1 DSH_RUNTIME_MODE=exe
export DSH_SHA=b2369692ea530007075ebcd18d39fdba0bbd3982
export ENVIRONMENT_DIGEST=sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb
export DATA_ROOT=/workspace/data/dsh-evolution-v2-b236969
cd "$M1_REPO"
test "$(git rev-parse HEAD)" = c4f9c308e98dd002d491113691416e3ab8736306
test "$(git -C verl rev-parse HEAD)" = fefb080262e1c015a0ea05f958822a6a512dc795
test -z "$(git status --porcelain --untracked-files=no)"
"$PYTHON_BIN" - <<'PY'
import hashlib, importlib.metadata as md, os
from pathlib import Path
from deepseek_harness_runtime import resolve_bundled_launch_args
assert md.version('deepseek-harness-sdk') == '0.1.3a2'
assert md.version('deepseek-harness-runtime-bin') == '0.1.3a2'
assert md.version('numpy') == '2.3.5'
exe = Path(resolve_bundled_launch_args('exe')[0])
assert 'sha256:' + hashlib.sha256(exe.read_bytes()).hexdigest() == os.environ['ENVIRONMENT_DIGEST']
PY
mkdir "$DATA_ROOT"
bash examples/dsh/ops/prepare_qwen3_4b_data.sh
"$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path
import pyarrow.parquet as pq
root = Path(os.environ['DATA_ROOT'])
rows = {s: pq.read_table(root / (s + '.parquet')).to_pylist() for s in ('train', 'holdout')}
assert {s: len(r) for s, r in rows.items()} == {'train': 16, 'holdout': 8}
ids = {}
for split, group in rows.items():
    ids[split] = set()
    for row in group:
        meta = row['extra_info']['tools_kwargs']['task']['metadata']
        assert meta['environment_digest'] == os.environ['ENVIRONMENT_DIGEST']
        assert meta['split'] == split
        ids[split].add(meta['task_id'])
        assert os.environ['M1_REPO'] in str(row['prompt'])
assert not ids['train'] & ids['holdout']
PY
```

`mkdir` 拒绝覆盖既有目录；准备脚本本身使用 `mkdir -p`，因此保留外层检查。生成器输出 16/8 行，训练通过 sample limit 选 4/2；不能传 `--max-records` 后再调用要求 16/8 的 manifest writer。

`write_dataset_manifest.py:87-89` 的 repository/branch 是历史硬编码，只有 commit 由 Git 实时读取；本次不修改业务源码。新数据 manifest 应与本文件、实际 checkout SHA、run provenance 一起保存，不把其 `branch=dsh-adapter` 当成部署分支证据。

## 2. 同预算新版训练

```bash
export MODEL_LICENSE_APPROVED=1
export MODEL_ID=Qwen/Qwen3-4B
export MODEL_PATH=/workspace/models/Qwen3-4B-1cfa9a7
export TASK_CONFIG="$M1_REPO/examples/dsh/evolution_task_config_v2_fast.yaml"
export PROJECT_NAME=dsh-qwen3-4b-online-rl
export EXP_NAME=m1-v4-session-v2
export RUN_ROOT=/workspace/runs/dsh-m1-v4-session-v2
export TRAIN_FILE="$DATA_ROOT/train.parquet" TEST_FILE="$DATA_ROOT/holdout.parquet"
export NNODES=1 NGPUS_PER_NODE=1 ROLLOUT_TP=1 GATEWAY_COUNT=1 CONCURRENCY=1
export LOW_VRAM=1 LORA_RANK=16 LORA_ALPHA=16 SAVE_LORA_ONLY=False
export TRAIN_BATCH_SIZE=2 PPO_MINI_BATCH_SIZE=1 TOTAL_TRAINING_STEPS=2
export TRAIN_MAX_SAMPLES=4 VAL_MAX_SAMPLES=2 DATA_SHUFFLE=False
export ROLLOUT_N=4 VAL_ROLLOUT_N=1 ROLLOUT_MAX_NUM_SEQS=1
export MAX_PROMPT_LENGTH=8192 MAX_RESPONSE_LENGTH=1024 PPO_MAX_TOKEN_LEN_PER_GPU=9216
export SAVE_FREQ=1 TEST_FREQ=1 GPU_MEMORY_UTILIZATION=0.30
export ROLLOUT_CPU_OFFLOAD_GB=0 ROLLOUT_LAYERED_SUMMON=False
export ROLLOUT_ENFORCE_EAGER=True ROLLOUT_FREE_CACHE_ENGINE=True
export ACTOR_PARAM_OFFLOAD=True ACTOR_OPTIMIZER_OFFLOAD=True
export TOOL_PARSER=hermes ATTN_IMPLEMENTATION=sdpa ACTOR_MODEL_DTYPE=bfloat16
export RESUME_MODE=disable RESUME_FROM_PATH= VAL_ONLY=False
unset PYTORCH_CUDA_ALLOC_CONF
unset AGENT_LOG_DIR ROLLOUT_DATA_DIR VALIDATION_DATA_DIR DSH_TRACE_ROOT DSH_RESULT_ROOT
unset CKPTS_DIR ALLOW_REUSE PRINT_COMMAND
test -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)"
test ! -e /workspace/reports/dsh-m1-v4-session-v2.log
mkdir "$RUN_ROOT"
"$PYTHON_BIN" - <<'PY'
import hashlib, json, os, subprocess
from pathlib import Path
root = Path(os.environ['RUN_ROOT'])
old = json.loads(Path('/workspace/runs/dsh-m1-v3/resolved-launch.json').read_text())
keys = set(old['environment']) | {'DSH_VENV', 'PYTHON_BIN', 'PYTHONPATH', 'ENVIRONMENT_DIGEST', 'VAL_ROLLOUT_N', 'SAVE_LORA_ONLY', 'PPO_MINI_BATCH_SIZE', 'RESUME_MODE', 'VAL_ONLY'}
out = {'environment': {k: os.environ[k] for k in sorted(keys)},
       'integration_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
       'verl_revision': subprocess.check_output(['git', '-C', 'verl', 'rev-parse', 'HEAD'], text=True).strip(),
       'model_revision': old['model_revision'], 'wall_clock_seconds': 1800,
       'kill_grace_seconds': 30, 'status': 'prepared-not-executed',
       'dataset_manifest_sha256': hashlib.sha256((Path(os.environ['DATA_ROOT']) / 'manifest.json').read_bytes()).hexdigest()}
(root / 'resolved-launch.json').write_text(json.dumps(out, indent=2) + '\n')
PY
uv pip freeze --python "$PYTHON_BIN" > "$RUN_ROOT/packages.txt"
set +e
timeout --signal=TERM --kill-after=30s 1800s \
  bash examples/dsh/ops/launch_qwen3_4b_online_rl.sh --foreground \
  > /workspace/reports/dsh-m1-v4-session-v2.log 2>&1
m1_exit=$?
set -e
printf '%s\n' "$m1_exit" > "$RUN_ROOT/exit-code"
test "$m1_exit" -eq 0
"$PYTHON_BIN" examples/dsh/ops/audit_qwen3_4b_online_rl.py "$RUN_ROOT" \
  --output "$RUN_ROOT/trajectory-audit.json"
"$PYTHON_BIN" deployment/checks/checkpoint_delta.py \
  "$RUN_ROOT/checkpoints/$PROJECT_NAME/$EXP_NAME/global_step_1/actor/model_world_size_1_rank_0.pt" \
  "$RUN_ROOT/checkpoints/$PROJECT_NAME/$EXP_NAME/global_step_2/actor/model_world_size_1_rank_0.pt" \
  --output "$RUN_ROOT/checkpoint-delta.json"
```

若 timeout/异常退出，保留失败产物、先查实际 GPU/Ray 进程再处理，禁止直接重启同目录。前台 launcher 被 timeout 杀死时 manifest 可能仍显示 running；外层 `exit-code` 和真实进程查询共同判断。日志放 reports，不能预写 `RUN_ROOT/run.log`，否则 launcher 会触发防覆盖。

当前新版 venv 没有安装 pip；依赖快照使用已安装的 `uv pip freeze --python`，不为记录版本向训练环境额外安装 pip。GPU 查询是最后一道资源检查，不能代替先确认正在运行的 M2 已结束。

## 3. 独立 reload 与同一留出预算

前一段 exit 0、审计与有效参数变化通过后执行，沿用同一 shell 的显式预算。这里加载**新版新训 checkpoint**，不是加载旧 M1v3 权重。

```bash
test -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)"
export CHECKPOINT_PATH="$RUN_ROOT/checkpoints/$PROJECT_NAME/$EXP_NAME/global_step_2"
export RUN_ROOT=/workspace/runs/dsh-m1-v4-session-v2-reload
export EXP_NAME=m1-v4-session-v2-reload
test ! -e "$RUN_ROOT"
test ! -e /workspace/reports/dsh-m1-v4-session-v2-reload.log
set +e
timeout --signal=TERM --kill-after=30s 1800s \
  bash examples/dsh/ops/reload_qwen3_4b_checkpoint.sh "$CHECKPOINT_PATH" --foreground \
  > /workspace/reports/dsh-m1-v4-session-v2-reload.log 2>&1
m1_reload_exit=$?
set -e
test -d "$RUN_ROOT"
printf '%s\n' "$m1_reload_exit" > "$RUN_ROOT/exit-code"
test "$m1_reload_exit" -eq 0
"$PYTHON_BIN" examples/dsh/ops/audit_qwen3_4b_online_rl.py "$RUN_ROOT" \
  --partition val --output "$RUN_ROOT/trajectory-audit.json"
```

最后核验训练日志中两次非零梯度、有限 loss，checkpoint delta 中 LoRA 变化且 base 不变，训练+validation 原始轨迹消费审计无拒绝/无错配，reload 日志明确加载新 `global_step_2`、没有训练指标或新 checkpoint。分别记录基线/step1/step2/reload 的两题 reward 与 accuracy。2 steps 的理想原始轨迹组数沿用旧 run 的 10，reload 为 2；数量不能代替内容审计。若 accuracy 没提升，如实记零，不扩大任务规模来掩盖结果。

## 仍待实际验证的阻点

1. 新 runtime 与 `evolution.patch.yml`、session-local host 工具、真实 Qwen/Gateway 的组合尚未在新版上跑通；现有 keyless/minimal 证据无法替代它。
2. 新 venv 模块路径已只读验证，但还没在此固定组合启动 Actor/vLLM。保留现有工具链、缓存和模型；出现依赖错误先诊断，不重复 build/download。
3. 本批的 M1 留出是优化数据之外的工程评估；M2 的 Harbor 分布式闭环仍需自己的 reward/消费/reload 证据。两个里程碑互不替代。
