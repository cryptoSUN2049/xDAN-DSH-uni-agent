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

## H0 完成后：真实学生提议 P

以下仍在原固定执行 checkout 中运行，沿用 `RSI_MANIFEST` 及外部记录的 `RSI_MANIFEST_SHA`。prepare 会重审原H0证据，而不是信任手填成功字段。P使用同一base模型，禁止工具调用，仅输出候选声明；不产生训练更新。

```bash
export RSI_PROPOSAL="${RSI_ROUND}-proposal"
"$PYTHON_BIN" - <<'PY'
import os
from examples.dsh.rsi_closed.proposal_registration import prepare_proposal
prepare_proposal(os.environ['RSI_MANIFEST'], os.environ['RSI_MANIFEST_SHA'],
    '/root/runs/' + os.environ['RSI_PROPOSAL'] + '-data',
    '/root/runs/' + os.environ['RSI_PROPOSAL'])
PY
export RSI_P_MANIFEST="/root/runs/${RSI_PROPOSAL}-data/preparation-manifest.json"
export RSI_P_SHA="$("$PYTHON_BIN" -c 'import sys;from examples.dsh.rsi_closed.prepare_worker_eval import digest;print(digest(sys.argv[1]))' "$RSI_P_MANIFEST")"
"$PYTHON_BIN" -m examples.dsh.rsi_closed.launch_proposal \
 --manifest "$RSI_P_MANIFEST" --manifest-sha256 "$RSI_P_SHA" --launch
```

查看真实 `proposal-audit.json`：格式reward0或registration_ready=false时保留失败，不调用注册器强行登记或让人代写候选。reward1也仅说明候选合法且改变了配置，不能证明收益。完整H0/P先归档，再进入登记。

## 登记未晋升候选，并运行 H1

下列注册函数会重新审核模型原文、SDK trace、原始token/receipt/TQ、父状态及监督证据；不接受用户传入任意candidate JSON。来源不可信或无变化会拒绝。

```bash
export RSI_REGISTRATION="/root/runs/${RSI_ROUND}-registration.json"
"$PYTHON_BIN" - <<'PY'
import os
from examples.dsh.rsi_closed.proposal_registration import register_verified_proposal
register_verified_proposal(os.environ['RSI_P_MANIFEST'], os.environ['RSI_P_SHA'],
    os.environ['RSI_REGISTRATION'])
PY
export RSI_H1_NAME="${RSI_ROUND}-candidate"
"$PYTHON_BIN" - <<'PY'
import json, os
from pathlib import Path
from examples.dsh.rsi_closed.prepare_worker_eval import prepare
root = Path('/root/runs') / os.environ['RSI_ROUND']
config = json.loads((root / 'baseline-config.json').read_text())
registration = json.loads(Path(os.environ['RSI_REGISTRATION']).read_text())
config.update(mode='paired', candidate_sha256=registration['candidate_sha256'],
    output_dir='/root/runs/' + os.environ['RSI_H1_NAME'] + '-data',
    run_root='/root/runs/' + os.environ['RSI_H1_NAME'])
prepare(**config)
PY
export RSI_H1_MANIFEST="/root/runs/${RSI_H1_NAME}-data/preparation-manifest.json"
export RSI_H1_SHA="$("$PYTHON_BIN" -c 'import sys;from examples.dsh.rsi_closed.prepare_worker_eval import digest;print(digest(sys.argv[1]))' "$RSI_H1_MANIFEST")"
"$PYTHON_BIN" -m examples.dsh.rsi_closed.launch_worker_eval \
 --manifest "$RSI_H1_MANIFEST" --manifest-sha256 "$RSI_H1_SHA" --side H1 --launch
```

paired准备器会创建两侧配置；这里仅运行H1，比较使用先前真实完成的parent-baseline H0，不能把未执行的新H0配置当结果。H0/H1保持同一pair、模型、任务源、预算、verifier和固定父active。完成后必须用原始审计比较逐题收益；不能只比较两个平均分。运行时使用的是未晋升候选临时overlay，生产active仍是父策略。
