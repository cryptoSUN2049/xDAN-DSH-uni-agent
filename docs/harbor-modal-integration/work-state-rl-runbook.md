# 工作状态任务：原生在线 RL 人工复跑指南

本指南对应 `prepare_memory_training --family work-state-v1`。固定 DSH 0.1.3a2、Uni-Agent upstream 89733ec、VERL官方基线fefb080 **加 preserve-finish-reason-v1 源码补丁**；有效版本不是裸fefb080。集成源码必须使用实验报告记录的完整 Git SHA。复用已有 Python 环境，不在运行中的 checkout 更新源码。

**当前状态：r3已失败，r4尚未启动。** [r3原始结果](work-state-train-r3-result.md)显示step4周期评估WS06 A写只读来源被拒，训练child exit1；不是合法零奖励主动终止。调度修复已在本地实现并通过27项recipe回归：work-state train设置`trainer.val_before_train=False`、`trainer.test_freq=0`，保留8步、n4、step4/8保存；严格val/reload独立执行。该调度变更须以主线程最终提交和新manifest核实，不能直接重启旧r3清单。

DSH当前已是0.1.3a2 SDK/runtime，私有Release已存在，deployment lock固定b236源码与runtime SHA；旧截图“新版runtime未发布/仍需构建”不再适用。主线程已实查远端SDK与runtime-bin均为0.1.3a2，二进制SHA为d1a467…并匹配lock；本轮复用该环境，核hash后运行，不从零重建DSH或CUDA。

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
WORK_STATE_REPO=/workspace/rebuild/uni-agent-work-state-r4
# r4尚未部署/启动；执行前用主线程实际已部署的新checkout路径替换。
cd "$WORK_STATE_REPO"
# 将下行替换为实验报告中的完整集成SHA。
WORK_STATE_SHA=REPLACE_WITH_RECORDED_COMMIT
test "$(git rev-parse HEAD)" = "$WORK_STATE_SHA"
test "$(git -C verl rev-parse HEAD)" = fefb080262e1c015a0ea05f958822a6a512dc795
export PYTHON_BIN=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
export PYTHONPATH="$PWD:$PWD/verl"
unset PYTHONHOME RAY_ADDRESS PYTORCH_CUDA_ALLOC_CONF
export CUDA_VISIBLE_DEVICES=''
# 仅在新建、没有运行中进程的独立checkout显式应用；旧run源码不动。
"$PYTHON_BIN" -m deployment.checks.verl_source_overlay --repo "$PWD/verl" --apply
"$PYTHON_BIN" -m deployment.checks.verl_source_overlay --repo "$PWD/verl"
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

协议修复另有固定runtime检查；其模型端是本机scripted HTTP，不占GPU：

```bash
"$PYTHON_BIN" -m deployment.checks.dsh_finish_reason_canary \
 --runtime "$WORK_STATE_RUNTIME" --output "/root/runs/${WORK_STATE_LABEL}-finish-canary" --include-abort
```

验证stop、length、截断文本内打印工具块无副作用，以及terminal abort明确失败；检查通过后仍须真实GPU采样/训练。补丁清单在`deployment/versions/verl-runtime-patches.json`，prepare/check与run manifest记录复合身份及真实VERL导入目录，任何未知修改均拒绝。母checkpoint reload要求相同有效VERL身份。

## 4. 独立GPU学生评估（与训练分开执行）

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

本节val仍严格执行原安全/证据门：失败就保留该评估run的failed，不生成替代TQ、不放宽准入。它是独立诊断，不应作为第5节工程训练的隐式硬前置；按当前工程优先级，可先执行第5节，再在独立进程运行val/reload。不要把四题满分或非零奖励作为启动工程链路的条件。

## 5. 训练与证据

上一节`prepare`改成`--mode train`，所有目录和run-id替换为`WORK_STATE_TRAIN`，再运行对应`check/launch/audit`。新调度目标保持8步、n4、batch1、step4/8保存；同步训练，非全异步。work-state train关闭内嵌initial/periodic dev：有效配置应为`trainer.val_before_train=False`、`trainer.test_freq=0`。准备后用`check`核对新源码、新manifest和最终有效配置；不得把旧r3的True/4清单重新用于r4。该变更已通过27项recipe回归，待主线程提交/推送并固定新manifest；r4尚未启动。

训练上限7200秒。工程层验收是计划步数、可信完整组消费、checkpoint保存及独立reload；合法全0奖励/零梯度不主动打断这条流程。有效学习层另要求真实非零任务梯度、优势及参数/optimizer证据；能力提升再做同预算评估对照。训练自身出现安全/证据拒绝仍按原合同处理，本次解耦不豁免任何不合格轨迹。

观察：`<run>/supervision/train.log`、`supervisor-result.json`、`<run>/chains/groups/*/crosswalk.json`、`<run>/rollouts/*.jsonl`、`<run>/validation/*.jsonl`。checkpoint位于`/workspace/uni-agent-g1/checkpoint/<run-id>/global_step_N`。记录实际任务ID、完整组、奖励方差、梯度、参数差分、冻结base与optimizer步数；数据重复采样不增加独立任务数。

审计会重新验证原trace/fixture、来源与verifier摘要、冻结/展开字节、输出快照和实际消费；同分篡改也拒绝。exit0或GPU显存驻留均不能替代这些证据。

## 6. 独立reload与故障处理

母训练以exit0完成、真实checkpoint的结构和版本身份通过后，即可先验收独立reload；不因合法零奖励或零梯度阻止工程加载检查。非零任务梯度/参数变化是另一个验收层，未通过时明确报告“流程完成，尚无有效学习证据”。新建`WORK_STATE_RELOAD`身份；使用相同prepare参数，改为`--mode reload --resume-from /workspace/uni-agent-g1/checkpoint/<母run>/global_step_N --mother-run /root/runs/<母run>`。新的output/run目录必须独立，然后check/launch/audit。

reload绑定完整checkpoint文件SHA及母运行清单，显式加载model/optimizer/extra，仅评估；不会重新训练或删除母checkpoint。比较同预算开发任务结果，照实记录波动和失败；不以提分作为工程验收前置。

若失败：保留原目录/日志/回执，先查第一异常，再以新代码/新清单/新run复验。不要让PRINT_COMMAND占正式目录，不设置ALLOW_REUSE，不全局ray stop/pkill，不修改旧评分。不在`/workspace`放需要0700的私有运行目录；脱敏证据归档与checkpoint保留在云盘。

验收清单：[当前goal W0—W6](../../tasks/harbor-modal-integration/active-engineering-goal.md)。当前运行进度另见实验报告和handoff，本指南本身不证明GPU已通过。
