# 原生四能力：复用已验收环境的真实 Gateway baseline

2026-09-09；只读核查，本文未启动 GPU。核查 checkout HEAD `00eeaeb280f5004e2afe275e58fbcc859fbd389f`。新任务实现提交后，运行 manifest 另锁完整 SHA；本计划不要求升级依赖或等待 N0 新环境训练。


## 本轮实际采用的入口

主线程已选择本文 `parallel_infer_verl.py` 原生 inference 路线，发出准备与有界监督启动：run 为 `/root/runs/dsh-capability-grounding-baseline-r1`，数据目录使用独立 `-data` 后缀；checkout `00eeaeb280f5004e2afe275e58fbcc859fbd389f`，复用已验收 venv。实际参数为 max-model-len=8192、n=1、limit=1、GPU memory=0.30、监督1800秒。本段只记录启动方案被采用，成功与否以该运行日志/回执为准。

没有通过 ops 的 VAL_ONLY 训练器入口，也没有复制/伪造 dataset manifest。`prepare_capability_eval.py` 只写准备态 `run-manifest.json`，而 ops 要求 `DATA_ROOT/manifest.json`；旧 r4 batch=2 又不适用于单行数据。此次直接 inference 避开这两处不必要衔接，同时保留真实 Gateway token、strict postprocessor 和 TQ readback。准备态 manifest 与独立 inference-evidence/launch-manifest 分别保留。

## 最短入口与证据边界

复用 `examples/inference/parallel_infer_verl.py`。该入口自己创建 VERL LLMServerManager、Gateway、AgentFrameworkRolloutAdapter 和 TransferQueue，实际启动固定学生模型；只生成、评分及读取 TQ，不创建 actor 优化器、不训练、不保存 checkpoint。不要另起一个普通 vLLM API 服务再接 `parallel_infer_api.py` 冒充相同证据。

普通 API eval 可测试 DSH 行为，但外部 API 返回文本不等于 Gateway 获得真实 token IDs/mask/logprob。此入口设置 `calculate_log_probs=True`；任务调用注入的 session-scoped Gateway endpoint，Gateway 从 backend 的 token 输出建立轨迹。原生 strict postprocessor 在生成时审计 DSH trace/receipt，CLI 再核实际 TQ readback。这里只能称固定策略 baseline，`global_steps=None` 不代表一次在线更新。

已有 `examples/dsh/prepare_capability_eval.py` 只准备一题 runtime-grounding，输出 `eval.parquet`、`task.yaml` 和准备 manifest。它不是四能力数据生成器；其 VAL_ONLY/TRAIN_FILE 环境字段原本用于训练器评估入口，此处只取实际数据/config/manifest，不启动训练器。

## 输入任务合同

- 数据行：`prompt` 与 `extra_info.tools_kwargs.task`，后者含 `name=dsh_architecture` 和受信 metadata。YAML 按同名配置 DSH agent、原生 sandbox、verifier 与固定 runtime；不同能力可用不同 YAML/run，避免共享不一致的 temperature/top_p。
- strict CLI 当前明确只接受 `dsh_architecture`。新能力若改 task 名称，必须先实现对应准入与审计入口，不能删除 strict 开关来宣称通过。
- policy/DSH 调度与 context：先以新任务准备器生产冻结样本、fixture、verifier、task config，保持同一 DSH Agent Loop。`prepare_capability_eval.py` 的单题历史评分不能冒充新能力 verifier。
- 记忆 A→B：一个外层案例需显式两个 Session 身份、允许持久传递产物及终局 credit 合同；当前通用 CLI 的“一个样本一次 session”不能自动完成它。多 context token chains 不等于跨 Session 持久记忆。
- RSI：固定候选范围/测试/采用或回滚合同后再接该入口；不以修过一次插件代替候选留出收益。

## 环境：复用已验收 venv，明确旧 editable 来源

```bash
cd /workspace/rebuild/uni-agent-g1-v2
export DSH_VENV=/workspace/venvs/uni-agent-rebuild-cf2d3f5
export PYTHON_BIN="$DSH_VENV/bin/python"
export PATH="$DSH_VENV/bin:$PATH"
export PYTHONPATH="$PWD:$PWD/verl"
export PYTHONNOUSERSITE=1
export DSH_RUNTIME_MODE=exe
export HF_HUB_OFFLINE=1
export CUDA_VISIBLE_DEVICES=0
unset RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
```

这是明确复用旧环境并通过 PYTHONPATH 选择当前已提交源码；旧 editable 指向 `uni-agent-cf2d3f5` 的历史事实已记录，不把它称作干净安装。启动前打印 `uni_agent.__file__`、`verl.__file__` 与 runtime path/hash，确认选择本次 checkout。Python 3.12.3、torch 2.11.0+cu130、vLLM 0.24.0、Transformers 5.5.3、Ray 2.55.1、NumPy 2.3.5、DSH 0.1.3a2；VERL `fefb080262e1c015a0ea05f958822a6a512dc795`；DSH binary SHA256 `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。

模型固定 `/workspace/models/Qwen3-4B-1cfa9a7`，revision `1cfa9a7208912126459214e8b04321603b3df60c`。不要安装/升级，也不要把 CPU 测试环境或 Harbor site-packages 加入 GPU PYTHONPATH。先确认无其他 GPU 工作，不能抢占既有任务。

## 准确 CLI 模板

先由准备器建立受信数据目录；以下 `<能力>-r1-data` 必须替换为真实新路径，核 manifest/hash 后执行。首批每能力最多两题、n=1、单并发。运行日志根为新目录 `/root/runs/dsh-<能力>-baseline-r1`，0700；不要复用准备器写过的 `run-manifest.json` 来记录不同 schema。

```bash
"$PYTHON_BIN" examples/inference/parallel_infer_verl.py \
  --data-path /root/runs/dsh-<能力>-r1-data/eval.parquet \
  --task-config /root/runs/dsh-<能力>-r1-data/task.yaml \
  --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
  --served-model-name Qwen/Qwen3-4B \
  --engine vllm --nnodes 1 --n-gpus-per-node 1 --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.30 --max-model-len 8192 \
  --gateway-count 1 --concurrency 1 --tool-parser hermes --limit 2 --n 1 \
  --require-result --dsh-strict-audit \
  --log-dir /root/runs/dsh-<能力>-baseline-r1/agent-logs \
  --dsh-trace-root /root/runs/dsh-<能力>-baseline-r1/artifacts/traces \
  --dsh-result-root /root/runs/dsh-<能力>-baseline-r1/artifacts/results \
  --result-path /root/runs/dsh-<能力>-baseline-r1/result.json \
  --inference-evidence-path /root/runs/dsh-<能力>-baseline-r1/inference-evidence.json
```

此 CLI 固定 prompt_length=4096，response_length 取 YAML 的最大 `agent.model.max_total_tokens`；上例仅适用于该值≤4096。`--max-model-len` 必须≥4096+response_length，不能照搬训练器的 8192/1024 含义。建议首次任务显式 max_total_tokens=4096、max_tokens_per_turn=512、run_timeout≤1200；合法完整动作若确需更大单 turn，先记录依据再改任务版本。历史 prepare_capability_eval 实际将每 turn 改为2048、run_timeout仍1800，不能误报为上述建议值。

严格模式要求 --n=1；temperature/top_p 来自 YAML（缺省0.8/0.9），要在新任务 YAML 显式固定，并在所有 before/after 评估保持一致。同题要多次 baseline，用独立 run；不会因 n=1 就自动确定性。

若任务需要隔离输入目录，可使用已有三个成组参数：`--dsh-episode-workdir-root`、`--dsh-episode-source-root`、`--dsh-episode-files`。全部必须绝对路径，files 为受信 JSON 路径/hash 清单；不能仅复制 prompt 而漏文件状态。这一路目前是原生 local，不经 Harbor/Modal。

## 监督、预算和终止

主线程把上述 argv 作为列表交给现有 `deployment.services.harbor_training_supervisor.supervise`：原生任务用 `health=lambda:None`，wall_seconds=2700、grace=30，私有新 root，显式 environment。它以 `start_new_session=True` 启动，写 `train.log`、`supervisor-result.json`、`exit-code`；文件名含 train 不表示发生参数训练。记录 source commit、模型/runtime/data/config/verifier hash 和实际 argv 到独立 `launch-manifest.json`。

不要在主shell直接无界执行 CLI。外层监督要独立于 SSH（stdin DEVNULL、脱离连接），定期读取日志。设置单独且短的 `RAY_TMPDIR`（例如 `/root/ray-cap-policy-r1`），在 launch manifest 记录其 Ray session 路径和自有 PID。禁止全局 `ray stop` 或 `pkill`。

**当前清理限制必须实测：** `parallel_infer_verl._generate()` 没有显式 finally shutdown；现有 supervisor 只在子进程仍运行时回收该进程组，自然退出并不自动证明 Ray 子进程已清理。结束后核 GPU PID 和专属 Ray session；残留仅按已记录的本轮身份回收，不能误杀其他任务。超时/失败保留原日志，不用一次 exit=0 掩盖残留。

## baseline 验收与准确审计入口

1. 真实学生请求经 DSH runtime→Gateway；每题 fresh session/trace/receipt，任务失败可如实0分，但基础设施或证据失败不能算正常完成。
2. `inference-evidence.json` completed、samples 数量与 --limit/实际数据一致、readback final_keys/scores/uid_status 完整；strict CLI 自动核 readback。
3. agent-logs 中 `trajectory.json`/`trajectory.npz` 与 DSH 回执存在，真实模型 token、mask、logprob、verifier identity 可追溯；记录逐题业务指标/失败原因，不只平均 reward。
4. 无优化器更新、无新 checkpoint；GPU/自有 Ray 资源释放后归档到 `/workspace/reports/<运行名称>/`。baseline 失败是能力诊断结果，不应反复跑旧满分题替代新任务。
5. `audit_qwen3_4b_online_rl.py` 依赖训练 run-manifest/消费目录；不能直接对这里新 schema 套用。`audit_v3_live_smoke.py` 又绑定特定 v3 prepared-run。首批以严格在线 postprocessor + TQ readback +新能力离线证据核对为准，后续如需统一审计只补薄适配，不能伪造训练消费记录。

另有 `run_v3_live_smoke.py` 仍固定旧 torch/vLLM 等版本门，不能将它当当前已验收环境的快捷入口直接启动。原生能力优先使用本文通用 CLI；Harbor训练、全异步、N0新环境GPU证明后置。
