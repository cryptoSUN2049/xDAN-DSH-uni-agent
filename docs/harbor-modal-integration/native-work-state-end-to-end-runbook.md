# 原生工作状态 RL：从固定部署到结果复跑

当前流程：DSH SDK/runtime → Uni-Agent/Gateway在线采样 → 原奖励 → VERL训练 → checkpoint → 独立reload评估。DSH保持唯一任务执行循环。本阶段不需要Harbor、Docker、Modal或SFT。

**验收状态**：旧四族r4完成8步执行与独立四题收尾，但有效参数更新未通过。独立短课程现已验证真实非零梯度、参数变化及两题独立reload/fresh评估，见[短课程操作指南](work-state-short-course-runbook.md)与[最终评估报告](work-state-short-reload-final-result.md)。两课程身份与结论分开。下列为可手工执行的分阶段入口，不是已验收的空白主机一键安装承诺。当前状态看[goal](../../tasks/harbor-modal-integration/active-engineering-goal.md)及[handoff](../../tasks/harbor-modal-integration/handoff.md)。

## 0. 选择实验与准备机器

Linux x86_64，Python3.12、Git、uv、可用NVIDIA驱动及兼容GPU。已有RunPod直接复用环境；空白主机先完成这些系统前提。本项目不提供宿主机驱动安装器。训练用97,887MiB单卡已运行；其他GPU容量须单独预检。

每次固定完整本仓Git SHA，不能边训练边pull。Uni-Agent upstream89733ec、VERL fefb080加preserve-finish-reason-v1、DSH0.1.3a2/b236969、Qwen3-4B revision1cfa9a7。精确组件与发布物hash在`deployment/versions/`，具体实验源码身份以run manifest为准，旧锁内的历史integration revision不代表当前checkout。

目录：源码`/workspace/rebuild/<新名>`；环境`/workspace/venvs/<环境名>`；模型`/workspace/models`；checkpoint`/workspace/uni-agent-g1/checkpoint/<run>`；私有运行`/root/runs`；脱敏证据`/workspace/reports`。不要将容器盘当checkpoint持久盘。GitHub/模型下载认证由机器账户准备，密钥不写入仓库。

## 1. GitHub固定源码

在已有仓库执行下列脚本。`RUN_CODE_SHA`必须填入已推送的40位实验提交，`RUN_REPO`是尚不存在的新路径。

```bash
set -euo pipefail
: "${RUN_CODE_SHA:?Set the exact published 40-character experiment commit}"
: "${RUN_REPO:?Set a new absolute checkout path}"
bash deployment/bootstrap/checkout.sh "$RUN_CODE_SHA" "$RUN_REPO"
cd "$RUN_REPO"
python3 deployment/checks/verl_source_overlay.py --repo "$PWD/verl" --apply
python3 deployment/checks/verl_source_overlay.py --repo "$PWD/verl"
```

只有新建且未运行的checkout可以apply补丁。复跑原母实验应使用其原提交；使用新编排器时，新run记录新提交并保留母checkpoint原提交，不伪造相同SHA。

## 2A. 当前GPU：复用环境

```bash
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
"$PYTHON_BIN" -m deployment.checks.verl_source_overlay --repo "$PWD/verl"
```

已有环境可能editable指向历史checkout；显式PYTHONPATH与prepare/check会核实际导入源码。不要把这种复用称为独立环境复建。

## 2B. 新环境：安装固定依赖及DSH发布物

仅在需要独立安装时执行，不与2A重复：

```bash
export DSH_TRAIN_VENV=/workspace/venvs/work-state-fresh-r1
export DSH_UV_CACHE=/workspace/cache/uv
export UV_PYTHON=/usr/bin/python3.12
export UV_LINK_MODE=copy
bash deployment/bootstrap/install-verl.sh
export PYTHON_BIN="$DSH_TRAIN_VENV/bin/python"
export PYTHONPATH="$PWD:$PWD/verl"
```

安装器使用VERL锁文件，并应用已锁wheel hash的NumPy2.3.5兼容修正，再安装本仓；不自动安装DSH。两份DSH wheel来自固定私有Release `cryptoSUN2049/xDAN-DSH-Exp` / `dsh-sdk-0.1.3a2-b236969-linux-x64`。现有GPU已保存在`/workspace/artifacts/dsh-g1-v2-b236969/`；新机器须先从该Release下载，不能从浮动latest替换。

```bash
export DSH_WHEEL_DIR=/workspace/artifacts/dsh-g1-v2-b236969
"$PYTHON_BIN" - <<'PY'
import hashlib, json, os
from pathlib import Path
lock = json.loads(Path('deployment/versions/g1-deployment-lock.json').read_text())['dsh']
root = Path(os.environ['DSH_WHEEL_DIR'])
for name, key in [
    ('deepseek_harness_sdk-0.1.3a2-py3-none-any.whl', 'sdk_wheel_sha256'),
    ('deepseek_harness_runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64.whl', 'runtime_wheel_sha256'),
]:
    assert 'sha256:' + hashlib.sha256((root / name).read_bytes()).hexdigest() == lock[key], name
PY
uv pip install --no-config --python "$PYTHON_BIN" --no-deps \
 "$DSH_WHEEL_DIR/deepseek_harness_sdk-0.1.3a2-py3-none-any.whl" \
 "$DSH_WHEEL_DIR/deepseek_harness_runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64.whl"
uv pip check --no-config --python "$PYTHON_BIN"
```

模型复用`/workspace/models/Qwen3-4B-1cfa9a7`；缺失时通过环境内huggingface_hub的`snapshot_download`下载`Qwen/Qwen3-4B`固定revision`1cfa9a7208912126459214e8b04321603b3df60c`至独立目录。当前prepare绑定声明revision及列出的配置hash，不应声称已逐字节锁定所有模型权重。空缓存下载/宿主驱动/新主机最终验收仍单列待办。

## 3. CUDA与任务环境检查

确认GPU没有其他作业后运行`deployment/checks/gpu_smoke.py`；它实际做CUDA前后向，不等于模型训练。随后按[课程指南第3节](work-state-rl-runbook.md#3-真实dsh工具检查无模型)执行work_state_runtime_canary及finish_reason_canary。前者核真实DSH工具、A冻结→B读取，后者核停止/截断语义；均不生成学生训练证据。

## 4. 数据准备、预检、训练启动

下列在同一Bash会话执行。数据由任务生成器产生，无需SFT教师生成。prepare只创建数据和manifest；check只读预检；launch才启动GPU。

```bash
export WORK_STATE_RUNTIME="$("$PYTHON_BIN" -c 'from deepseek_harness_runtime import bundled_runtime_path;print(bundled_runtime_path())')"
export WORK_STATE_TRAIN="ws-train-$(date -u +%Y%m%dT%H%M%S)"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir "/root/runs/${WORK_STATE_TRAIN}-data" \
 --run-root "/root/runs/${WORK_STATE_TRAIN}" --run-id "$WORK_STATE_TRAIN" \
 --runtime-executable "$WORK_STATE_RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family work-state-v1 --mode train
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training check \
 "/root/runs/${WORK_STATE_TRAIN}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
 "/root/runs/${WORK_STATE_TRAIN}-data/manifest.json"
```

可在tmux中前台执行；监督器限定本run时长和进程组。默认8train/4公开dev、8步/n4/同步训练，关闭初始和周期内联评估，step4/8保存。实际消费独立任务数需事后统计，不能假定8步覆盖8题。

## 5. 训练审计

```bash
"$PYTHON_BIN" -m examples.dsh.capabilities.audit_memory_training \
 "/root/runs/${WORK_STATE_TRAIN}" \
 --memory-root "/root/runs/${WORK_STATE_TRAIN}/chains" \
 --run-id "$WORK_STATE_TRAIN" \
 --output "/root/runs/${WORK_STATE_TRAIN}/consumption-audit.json"
```

必须检查监督器退出、实际消费、梯度/奖励/优势、checkpoint文件和版本谱系。模型和optimizer差分分别使用`deployment/checks/checkpoint_delta.py`、`optimizer_delta.py`，输入本run step4/8的对应actor工件。差分不通过必须保留，不因训练exit0宣称更新；合法全零不会阻止独立加载工程验证。

## 6. 独立reload与评估

复用第4节prepare参数，换全新run及output目录，mode改为reload，追加：

```bash
 --resume-from "/workspace/uni-agent-g1/checkpoint/${WORK_STATE_TRAIN}/global_step_8" \
 --mother-run "/root/runs/${WORK_STATE_TRAIN}"
```

然后check、launch、原消费audit。固定四题可用`--evaluation-task-id`逐题隔离，每题独立run。失败题保留原失败，全部任务结果汇总；成功题必须有实际validation消费而不只是TQ提交。串行控制器命令见[课程指南](work-state-rl-runbook.md#四题分别运行并统一报告)，设计见[收尾设计](work-state-independent-evaluation-plan.md)；只有对应实跑报告才能证明GPU验收通过。

## 7. 故障与保存

| 现象 | 操作 |
| --- | --- |
| 输出目录已存在 | 保留旧目录，新run-id重试；预检不占正式run目录 |
| GPU占用 | 查实际进程归属，不全局ray stop/pkill |
| finished=false / max-tokens | 保留任务失败；不补写finished=true或有效样本 |
| 轨迹/奖励hash或绑定错误 | 停止该批，修复后用新源码与新run |
| 全零奖励/梯度 | 记录为无有效学习，查真实业务输出，不人为造差异 |
| 独立eval中题失败 | 单题隔离保留结果，不能把未落盘提交当已消费 |

最终归档原始trace/NPZ/receipt/实际消费与运行清单至/workspace，排除凭据/私有环境文件；checkpoint已在持久盘，代码经commit/push固定。更新goal、handoff和报告。严格区分工程执行闭环、有效更新和能力提升。
