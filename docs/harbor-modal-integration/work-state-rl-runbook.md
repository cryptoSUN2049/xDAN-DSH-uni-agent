# 工作状态任务：原生在线 RL 人工复跑指南

本指南对应 `prepare_memory_training --family work-state-v1`。固定 DSH 0.1.3a2、Uni-Agent upstream 89733ec、VERL fefb080；集成源码必须使用实验报告记录的完整 Git SHA。复用已有 Python 环境，不在运行中的 checkout 更新源码。

## 1. 本次任务与边界

| 任务族 | 学生需要完成 | 判定依据 |
| --- | --- | --- |
| WS01 | 交接已完成步骤、依赖与配置，新会话恢复迁移计划 | 实际config正确、依赖顺序有效、已完成动作不重复 |
| WS03 | 保存组件事实并建立索引，新会话选兼容组件 | 实际组件组合满足事务/协议或格式/地域/保留期要求 |
| WS05 | 保存有范围和版本的事实，新会话处理陈旧/冲突建议 | 当前scope/revision与安全权威规则正确 |
| WS06 | 完整短请求不必额外持久化，直接完成计算配置 | 实际配置及空计划正确；目前不证明自主判断何时保存 |

默认8 train（每族variant0、seed101/202）、4公开dev（每族variant1、seed303）。这是4族工程课程；种子变化不是新结构，dev不是封存测试。真值、oracle仅控制端可见，模型只接收实际源文件与允许路径。

A在DSH中读来源并自行维护记忆文件；控制器冻结真实字节，B新会话从索引及公开请求继续。A阶段reward固定0，链的终局业务奖励来自B，完整A/B仍参与同组credit。合法错误/缺失记忆不被修补；越权、篡改、未完成会话按合同拒绝。DSH保持唯一Agent Loop。

## 2. SSH与固定目录

登录：`ssh root@216.243.220.178 -p 14465 -i ~/.ssh/id_ed25519`。以下在同一个Bash会话执行，`WORK_STATE_REPO`指向已由GitHub部署的固定checkout。先从对应实验报告填写SHA，禁止用浮动main替代。

```bash
set -euo pipefail
WORK_STATE_REPO=/workspace/rebuild/uni-agent-work-state-r1
cd "$WORK_STATE_REPO"
# 将下行替换为实验报告中的完整集成SHA。
WORK_STATE_SHA=REPLACE_WITH_RECORDED_COMMIT
test "$(git rev-parse HEAD)" = "$WORK_STATE_SHA"
test "$(git -C verl rev-parse HEAD)" = fefb080262e1c015a0ea05f958822a6a512dc795
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
export CUDA_VISIBLE_DEVICES=''
WORK_STATE_RUNTIME="$("$PYTHON_BIN" -c 'from deepseek_harness_runtime import bundled_runtime_path;print(bundled_runtime_path())')"
WORK_STATE_LABEL="work-state-$("$PYTHON_BIN" -c 'import uuid;print(uuid.uuid4().hex[:10])')"
WORK_STATE_VAL="${WORK_STATE_LABEL}-val"
WORK_STATE_TRAIN="${WORK_STATE_LABEL}-train"
nvidia-smi
```

## 3. 真实DSH工具检查（无模型）

```bash
"$PYTHON_BIN" -m deployment.checks.work_state_runtime_canary \
 --runtime "$WORK_STATE_RUNTIME" --output "/root/runs/${WORK_STATE_LABEL}-canary"
```

覆盖8种结构变体，真实SDK工具读写、缺文件返回、拒绝越权、A字节冻结→B读取与实际配置评分。控制器oracle写入仅在此检查存在；这些调用没有学生token，不能冒充训练回执或模型能力。

## 4. 准备并启动GPU学生基线

```bash
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training prepare \
 --output-dir "/root/runs/${WORK_STATE_VAL}-data" \
 --run-root "/root/runs/${WORK_STATE_VAL}" --run-id "$WORK_STATE_VAL" \
 --runtime-executable "$WORK_STATE_RUNTIME" --runner-python "$PYTHON_BIN" \
 --model-path /workspace/models/Qwen3-4B-1cfa9a7 \
 --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
 --family work-state-v1 --mode val
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training check \
 "/root/runs/${WORK_STATE_VAL}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.prepare_memory_training launch \
 "/root/runs/${WORK_STATE_VAL}-data/manifest.json"
"$PYTHON_BIN" -m examples.dsh.capabilities.audit_memory_training \
 "/root/runs/${WORK_STATE_VAL}" --memory-root "/root/runs/${WORK_STATE_VAL}/chains" \
 --run-id "$WORK_STATE_VAL" --output "/root/runs/${WORK_STATE_VAL}/consumption-audit.json"
```

`prepare/check`不加载GPU，`launch`使用清单的`CUDA_VISIBLE_DEVICES=0`，拒绝已占用GPU。可在tmux中运行，监督器对本run设wall-clock限制。基线要求真实执行/完整消费与逐族结果可审计，不要求四题全满分。

## 5. 训练与证据

上一节`prepare`改成`--mode train`，所有目录和run-id替换为`WORK_STATE_TRAIN`，再运行对应`check/launch/audit`。默认8步、n4、batch1，step4/8保存；同步训练，非全异步。初始及定期dev均为真实新会话。训练上限7200秒；未到步数/无有效梯度不能算完整验收。

观察：`<run>/supervision/train.log`、`supervisor-result.json`、`<run>/chains/groups/*/crosswalk.json`、`<run>/rollouts/*.jsonl`、`<run>/validation/*.jsonl`。checkpoint位于`/workspace/uni-agent-g1/checkpoint/<run-id>/global_step_N`。记录实际任务ID、完整组、奖励方差、梯度、参数差分、冻结base与optimizer步数；数据重复采样不增加独立任务数。

审计会重新验证原trace/fixture、来源与verifier摘要、冻结/展开字节、输出快照和实际消费；同分篡改也拒绝。exit0或GPU显存驻留均不能替代这些证据。

## 6. 独立reload与故障处理

训练与数值门通过且存在真实checkpoint后，新建`WORK_STATE_RELOAD`身份；使用相同prepare参数，改为`--mode reload --resume-from /workspace/uni-agent-g1/checkpoint/<母run>/global_step_N --mother-run /root/runs/<母run>`。新的output/run目录必须独立，然后check/launch/audit。

reload绑定完整checkpoint文件SHA及母运行清单，显式加载model/optimizer/extra，仅评估；不会重新训练或删除母checkpoint。比较同预算开发任务结果，照实记录波动和失败；不以提分作为工程验收前置。

若失败：保留原目录/日志/回执，先查第一异常，再以新代码/新清单/新run复验。不要让PRINT_COMMAND占正式目录，不设置ALLOW_REUSE，不全局ray stop/pkill，不修改旧评分。不在`/workspace`放需要0700的私有运行目录；脱敏证据归档与checkpoint保留在云盘。

验收清单：[当前goal W0—W6](../../tasks/harbor-modal-integration/active-engineering-goal.md)。当前运行进度另见实验报告和handoff，本指南本身不证明GPU已通过。
