# 新版 DSH redact_email：两步 GRPO 与独立 reload

2026-09-08。训练已由主线程启动；本文件只记录只读核验结果和后续命令，不代表训练或 reload 已通过。

## 本轮实际身份与预算

| 项目 | 本轮固定值 |
| --- | --- |
| GPU checkout | `/workspace/rebuild/uni-agent-g1-v2`，`74b253bfe2f580d4c6175672b5bdc0b3ccf623a8` |
| VERL | `fefb080262e1c015a0ea05f958822a6a512dc795` |
| DSH | `b2369692ea530007075ebcd18d39fdba0bbd3982`；SDK/runtime 均 `0.1.3a2` |
| 实际 runtime executable SHA256 | `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb` |
| Python | `/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python` |
| 初始策略 | 固定 `/workspace/models/Qwen3-4B-1cfa9a7`，新 LoRA rank/alpha=16/16；未加载 T2 SFT adapter |
| 数据 | `/root/runs/dsh-redact-execute-r1-data`，4 train / 2 public holdout |
| 运行 / checkpoint | `/root/runs/dsh-redact-m1-r1` / `/workspace/runs/dsh-redact-m1-r1-checkpoints` |
| 项目 / 实验 | `dsh-redact-execute` / `m1-r1` |
| 批次 | 2 global steps，train batch=2，PPO minibatch=1，train n=4，val n=1，shuffle=False |
| 容量 | prompt=8192，response=1024，PPO max token=9216；Gateway 总轨迹容量=9216，包含工具观测 |
| DSH task | `examples/dsh/evolution_task_config_v2_fast.yaml`；sdk-minimal、reasoning off、每 turn 512，run timeout=1200s |
| 保存 / 评估 | SAVE_FREQ=1、TEST_FREQ=1、`save_lora_only=False`；model/optimizer/extra 全部保存 |
| 单卡设置 | LOW_VRAM=1；GPU memory=0.30；param/optimizer offload=True；layered_summon=False；eager/free_cache=True；CPU offload=0；并发=1 |
| 监督 | `supervise(..., health=lambda: None, wall_seconds=2700, grace=30)`；仅管理自己创建的进程组，无 Harbor controller |

真实启动参数在运行目录的 `launch-manifest.json`，命令为 `bash examples/dsh/ops/launch_qwen3_4b_online_rl.sh --foreground`。该 manifest 保存 LoRA、CKPTS_DIR 等参数；仅复制旧 `command.txt` 会漏掉继承的 LoRA 参数。不要重跑现有目录或修改运行中的 checkout。

patch 必须保持相对路径 `examples/dsh/evolution.patch.yml`，工作目录必须为上述 checkout。其 bytes SHA256 为 `edace17a8096ec41e572c10fc7ad96f0d9a62c0a6ff9c8271694b4c1b1024aeb`；不能改成 Harbor 的 `/opt/dsh-patches/...`，seed 另行绑定了有序路径列表摘要。task config SHA256=`33eff7c295c027dc11e1a0e81bd8da3b04aa03b727800716c331dda0e8ee373b`，与旧 M1v3 相同。

## 数据与 token 只读实测

新 Pod 保留的源 16/8 数据与历史准备报告哈希完全一致：train=`5e3927a87e8a1296ab0e665c9ca9029d0825096310ec7529570e6a564ac2da04`，holdout=`b4fb8a1eff5e2c9349dcc4d441119919359321766bc75caee7159f31185bc4e7`，manifest=`1e22ec154e30d1d3394c394b837be6cddcb5067da32ab895058d5347298854d7`。selector 原样选取 train 索引 8—11、holdout 索引 4—5；六个 fixture hash、当前绝对路径及新版 runtime 绑定均通过。

本轮 curriculum manifest SHA256=`3e75ccb8973a5e2703a97a12ee88638ebb6e11b567dde97d836c14dc3e5c4fe0`；train=`6e2a89b2510b163e297430e5b8ff70c30a95896e9a2412facc5ce9b250ad62ff`，holdout=`2e98bfc4c11dfcb2bf0e0781f53013e4ed5599b967c81681d62a963591f31d71`。旧 run-manifest 摘要的 dataset counts/id/source_commit 为 null，因为课程使用新 schema；实际文件摘要与课程 manifest 均已保存，不补写虚构值。

真实离线 Qwen tokenizer CPU 检查 exit=0：六题给定的完整 `cordis_define` JSON 加 `<tool_call>` 包络均 **145 tokens**；raw user prompt 为 train 585 / holdout 587 tokens。检查不包含运行时 system/tools 输入，不保证学生输出合法 JSON，也不保证整段轨迹不耗尽容量。DSH 配置中的 max_total_tokens=3072 在当前 adapter 中不是累计预算：明确配置的每 turn 512 优先传给 SDK。

需要另行重建课程时，复用 selector，并选全新输出目录；现有数据不要覆盖：

```bash
set -euo pipefail
cd /workspace/rebuild/uni-agent-g1-v2
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python -m examples.dsh.prepare_redact_curriculum \
  --repository-root "$PWD" --source-dir /workspace/data/dsh-evolution-v2-b236969 \
  --source-manifest-sha256 sha256:1e22ec154e30d1d3394c394b837be6cddcb5067da32ab895058d5347298854d7 \
  --runtime-executable /workspace/venvs/uni-agent-rebuild-cf2d3f5/lib/python3.12/site-packages/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64 \
  --output-dir /root/runs/dsh-redact-execute-r2-data
```

## 训练后验收

原生 launcher 固定 `val_before_train=True`，因此一次训练进程即包含 baseline 两题、step1 两题、step2 两题；无需再启动一个 baseline 模型。正常预期训练 4 组×4 trajectories、评估 6 组×1，合计 **10 组 / 22 trajectories**。审计数量之外还要核真实 receipt、Session v2 trace、response mask/logprobs 和训练消费匹配。

```bash
set -euo pipefail
cd /workspace/rebuild/uni-agent-g1-v2
export PYTHONPATH="$PWD:$PWD/verl"
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
test "$(cat /root/runs/dsh-redact-m1-r1/exit-code)" = 0
"$PYTHON_BIN" examples/dsh/ops/audit_qwen3_4b_online_rl.py /root/runs/dsh-redact-m1-r1 \
  --output /root/runs/dsh-redact-m1-r1/trajectory-audit.json
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 "$PYTHON_BIN" deployment/checks/checkpoint_delta.py \
  /workspace/runs/dsh-redact-m1-r1-checkpoints/global_step_1/actor/model_world_size_1_rank_0.pt \
  /workspace/runs/dsh-redact-m1-r1-checkpoints/global_step_2/actor/model_world_size_1_rank_0.pt \
  --output /root/runs/dsh-redact-m1-r1/checkpoint-delta.json
```

必须同时满足：监督自然退出且 exit=0；两次训练 grad_norm 有限且非零；LoRA 数值实际变化、base 张量不变；optimizer 状态有限、动量非零且 step 增长；全部轨迹 eligible-and-consumed，无拒绝或未匹配消费。当前 batch/minibatch/n 对应每 global step 两个 optimizer 更新，正常预期 step1/step2 checkpoint 的 optimizer step 为 **2/4**，以实际 state 为准，不能错把 global step 当 optimizer step。日志里 `optimizer.step` 被调用、或 checkpoint 文件存在，均不足以证明有效学习。

分别记录 baseline/step1/step2 的逐题 reward、accuracy 和七项 reward components；训练 reward 有方差不等于留出提分。若零梯度或业务 accuracy 无改善，保留失败结论，不放宽 verifier、不重复同题训练来制造成功。

## 独立 reload：通过上述 gate 后才执行

新进程直接恢复本次完整 `global_step_2`，不需要 merger 或 SFT adapter。保留原 4 条 train 的 dataloader 配置供状态恢复，VAL_ONLY 只评估两条 holdout。下面复用本次精确 environment，重绑定所有输出根，限定 1800s；未在本轮审计中运行。

```bash
set -euo pipefail
cd /workspace/rebuild/uni-agent-g1-v2
export PYTHONPATH="$PWD:$PWD/verl"
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python - <<'PY'
import json, os, subprocess
from pathlib import Path
from deployment.services.harbor_training_supervisor import supervise
repo = Path.cwd()
old = Path('/root/runs/dsh-redact-m1-r1')
launch = json.loads((old / 'launch-manifest.json').read_text())
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == launch['source_commit']
supervisor = json.loads((old / 'supervisor-result.json').read_text())
assert supervisor['exit_code'] == 0 and supervisor['reason'] == 'training-exited'
assert json.loads((old / 'trajectory-audit.json').read_text())['eligible'] is True
assert json.loads((old / 'checkpoint-delta.json').read_text())['passed'] is True
assert not subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip()
checkpoint = Path('/workspace/runs/dsh-redact-m1-r1-checkpoints/global_step_2')
assert (checkpoint / 'actor/model_world_size_1_rank_0.pt').is_file()
root = Path('/root/runs/dsh-redact-m1-r1-reload')
ckpts = Path('/workspace/runs/dsh-redact-m1-r1-reload-checkpoints')
assert not root.exists() and not ckpts.exists()
root.mkdir(mode=0o700)
env = {**os.environ, **launch['environment']}
for key in ['AGENT_LOG_DIR', 'ROLLOUT_DATA_DIR', 'VALIDATION_DATA_DIR', 'DSH_TRACE_ROOT', 'DSH_RESULT_ROOT', 'ALLOW_REUSE', 'PRINT_COMMAND']:
    env.pop(key, None)
env.update(RUN_ROOT=str(root), CKPTS_DIR=str(ckpts), EXP_NAME='m1-r1-reload',
           RESUME_MODE='resume_path', RESUME_FROM_PATH=str(checkpoint), VAL_ONLY='True')
command = ['bash', 'examples/dsh/ops/reload_qwen3_4b_checkpoint.sh', str(checkpoint), '--foreground']
record = {**launch, 'environment': {**launch['environment'], **{k: env[k] for k in ['RUN_ROOT', 'CKPTS_DIR', 'EXP_NAME', 'RESUME_MODE', 'RESUME_FROM_PATH', 'VAL_ONLY']}},
          'command': command, 'wall_clock_seconds': 1800, 'initial_policy': str(checkpoint)}
for key in ['AGENT_LOG_DIR', 'ROLLOUT_DATA_DIR', 'VALIDATION_DATA_DIR', 'DSH_TRACE_ROOT', 'DSH_RESULT_ROOT', 'ALLOW_REUSE', 'PRINT_COMMAND']:
    record['environment'].pop(key, None)
(root / 'launch-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
result = supervise(command, repo, env, root, lambda: None, wall_seconds=1800, grace=30)
raise SystemExit(0 if result['exit_code'] == 0 else 1)
PY
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python examples/dsh/ops/audit_qwen3_4b_online_rl.py \
  /root/runs/dsh-redact-m1-r1-reload --partition val \
  --output /root/runs/dsh-redact-m1-r1-reload/trajectory-audit.json
```

reload 验收：exit=0、日志明确加载上面 step2 actor、2/2 val 组独立新 session/receipt 且被消费，无 actor 训练指标或新增模型 checkpoint。同时检查进程与 GPU 已释放；监督文件本身不证明全部子进程清理。将 `/root/runs` 中两轮日志、manifest、轨迹和审计结果归档到 `/workspace`，避免下一次 Pod 更换丢失。

任务边界：本课程执行提示中提供的完整动态工具代码，对公开单字符串邮箱脱敏进行客观验证；并非 T2 多输入、工具自主编写或隐藏泛化证明。新版成功与否应单独记录，不能继承旧 7840 M1v3 的通过结论。
