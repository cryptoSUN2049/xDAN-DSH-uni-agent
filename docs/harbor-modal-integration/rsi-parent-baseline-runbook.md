# 受控 RSI：先运行父策略真实开发基线

本入口复用已实现的 worker 准备器和监督器。目标是取得固定父策略 H0 的两类真实结果，为学生提议提供可信诊断；本步骤 `training=false`，不创建子候选或晋升。设计与后续 P/H1 合同见 [RSI 下一阶段](native-rsi-student-next-stage-design.md)。

任务一调用真实 runtime inspection，父策略禁止该调用时应安全返回 unavailable，合法失败为零分。任务二读取唯一允许的工程约束文件并准确引用事实。两者都经过固定学生、DSH、Gateway、严格轨迹审计和 TQ 消费，不能用控制器合成结果代替。

## 固定部署与 CPU 准备

先按[部署指南](native-work-state-end-to-end-runbook.md)创建新 Git checkout；使用包含 RSI overlay 适配的完整已推送提交，应用并验证固定 VERL 补丁。复用现有 venv，显式设置该 checkout 的 PYTHONPATH。以下命令在 Bash 中执行，每次使用新名字：

```bash
set -euo pipefail
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
export RSI_ROUND="rsi-student-$(date -u +%Y%m%dT%H%M%S)"
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
"$PYTHON_BIN" -m deployment.checks.verl_source_overlay --repo "$PWD/verl"
"$PYTHON_BIN" - <<'PY'
import json, os
from pathlib import Path
from deepseek_harness_runtime import bundled_runtime_path
from examples.dsh.rsi_closed import prepare_worker_eval as prep
from examples.dsh.rsi_closed.worker_tasks import prepare
from uni_agent.tasks.dsh.rsi_candidates import initialize
name = os.environ['RSI_ROUND']
root = Path('/root/runs') / name
root.mkdir(mode=0o700, exist_ok=False)
cases, model = root / 'cases', Path('/workspace/models/Qwen3-4B-1cfa9a7')
prepare(cases)
parent = {'schema':'dsh.rsi-profile.v1','profile':'sdk-minimal','allowed_tools':['str_replace_editor']}
pins = prep.input_pins(cases, model, name, 4096, parent)
ids = initialize(root / 'registry', parent, pins)
config = dict(cases_root=str(cases), model_path=str(model), pair_id=name,
    registry_root=str(root / 'registry'), pins_sha256=ids['pins_sha256'],
    parent_active_sha256=ids['active_sha256'], mode='parent-baseline',
    runner_python=os.environ['PYTHON_BIN'], runtime_executable=str(bundled_runtime_path()),
    output_dir=str(root / 'prepared'), run_root=str(root / 'workers'),
    max_tokens=4096, per_turn=512, wall_seconds=1800)
prep.write_json(root / 'baseline-config.json', config)
prep.prepare(**config)
path = root / 'prepared/preparation-manifest.json'
print(json.dumps({'manifest':str(path),'sha256':prep.digest(path)}))
PY
export RSI_MANIFEST="/root/runs/$RSI_ROUND/prepared/preparation-manifest.json"
export RSI_MANIFEST_SHA="$("$PYTHON_BIN" -c 'import sys;from examples.dsh.rsi_closed.prepare_worker_eval import digest;print(digest(sys.argv[1]))' "$RSI_MANIFEST")"
"$PYTHON_BIN" -m examples.dsh.rsi_closed.launch_worker_eval \
 --manifest "$RSI_MANIFEST" --manifest-sha256 "$RSI_MANIFEST_SHA" --side H0
```

这里仅初始化 operator 指定的固定父策略，不伪造学生候选。预检不创建正式 `workers/H0` 目录；不能手工建立此目录或复用已有运行目录。原始源/模型/固定补丁与 active 身份必须通过校验，拒绝时定位差异，不关闭校验。

## 真正启动 GPU

确认 GPU 空闲后执行（监督器也检查）：

```bash
"$PYTHON_BIN" -m examples.dsh.rsi_closed.launch_worker_eval \
 --manifest "$RSI_MANIFEST" --manifest-sha256 "$RSI_MANIFEST_SHA" --side H0 --launch
```

这是有界两题推理，最多 1800 秒；监督器只管理本次进程组。远程无人值守应使用独立日志和会话保存该启动命令，不能因 SSH 观察超时就重启任务。

## 验收与后续

核 `workers/H0/supervisor-result.json`、原始 inference evidence、validation dump、trace/NPZ/receipt 与 `runtime-binding.json`。退出成功只表明子进程结束；还需原始消费审计、固定 policy 实际加载、两题逐题结果、active 未变。安全且完整的零分是有效诊断；截断、越权、来源不可信单列。

随后由 `proposal_registration.audit_parent` 重审完整原始证据，才能准备真实学生 P。P 输出合法也不能立即晋升；必须注册未选中候选、执行 H1 配对比较、满足无回归与增益条件，再做真实加载及回滚。没有增益就保留拒绝结果。当前指南不是这些后续节点已通过的声明。
