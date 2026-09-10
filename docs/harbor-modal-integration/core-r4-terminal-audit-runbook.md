# core-train-r4 终态审计操作单

本单为已批准P1的既有工具操作顺序；尚未执行终态审计。14:43 SGT实际完成9/16，训练仍在运行。不得因为checkpoint8出现而启动并行GPU评估，也不得把当前新源码4232df3用于重解释r4原源码511bd71的预算。

## 1. 等待可信终态

登录当前GPU后，只读检查以下文件及本run进程。观察超时不等于作业结束；禁止重复launch或全局ray stop。

```bash
cat /root/runs/core-train-r4/supervision/supervisor-result.json
cat /root/runs/core-train-r4/run-manifest.json
```

开始正式成功收尾前要求监督器exit_code=0、run-manifest status=completed、metrics最后step=16、最终checkpoint16存在。若正常任务失败或预算导致非零退出，先保留终态原因并分类，不能修写状态文件。r4 PID快照21105/21295仅供定位，重连必须核真实进程与命令。

## 2. 原版本准入与消费审计

```bash
cd /workspace/rebuild/uni-agent-core-511bd71
export PYTHONPATH="$PWD:$PWD/verl"
CORE_PY=/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python
CORE_AUDIT=/workspace/reports/core-train-r4-final
mkdir "$CORE_AUDIT"
"$CORE_PY" - <<'PY'
from pathlib import Path
from examples.dsh.capabilities.prepare_memory_training import check
check(Path('/root/runs/core-train-r4-data/manifest.json'), after_run=True)
print('source/runtime/manifest checks passed')
PY
"$CORE_PY" -m examples.dsh.capabilities.audit_memory_training \
 /root/runs/core-train-r4 --memory-root /root/runs/core-train-r4/chains \
 --run-id core-train-r4 --output "$CORE_AUDIT/consumption.json"
```

`mkdir`故意不使用-p；已有报告必须先阅读，不能覆盖。check只验证它覆盖的合同，不代替终态/消费/学习核验。审计需核原始token、trace、receipt和完整组键；另按实际消费task ID统计家族与独立实例。520是可用训练任务，n4重复采样不能算4个新任务。未消费拒绝组保留原因，不计有效样本。

## 3. 参数和optimizer（CPU串行）

仅在训练进程终态后读取本项目自产checkpoint，沿用weights_only=True。以下工具会以非零退出码报告“没有有效变化”，这不是让人删除报告或自动重试的理由。

```bash
CORE_CK=/workspace/uni-agent-g1/checkpoint/core-train-r4
"$CORE_PY" -m deployment.checks.checkpoint_delta \
 "$CORE_CK/global_step_8/actor/model_world_size_1_rank_0.pt" \
 "$CORE_CK/global_step_16/actor/model_world_size_1_rank_0.pt" \
 --output "$CORE_AUDIT/checkpoint-8-to-16.json"
"$CORE_PY" -m deployment.checks.optimizer_delta \
 "$CORE_CK/global_step_8/actor/optim_world_size_1_rank_0.pt" \
 "$CORE_CK/global_step_16/actor/optim_world_size_1_rank_0.pt" \
 --output "$CORE_AUDIT/optimizer-8-to-16.json"
```

分别记录退出码和原始报告。若optimizer报告仅因moments全零失败，需额外只读报告实际step/finite/zero状态；不得放宽原审计器。比较8→16只覆盖后半程，不能单独证明初始→最终无变化或已有学习；结合全部16步reward/adv/grad、零初始化LoRA B是否仍零、base冻结和初始化来源报告。文件hash变化本身也不证明参数有效更新。

## 4. 独立reload与原始证据归档

按[既定reload协议](core-memory-reload-protocol.md)逐族首条公开dev，使用原511bd71 checkout与step16，四题独立新run串行执行。预先记录母checkpoint摘要，各题后复核不变；失败题有终态和原始原因后继续其余题，身份/工件损坏则先处理。不得把公开dev称封存测试，或将任意分数提高归因于训练。

把母run（含manifest、trace、receipt、rollouts、crosswalk、监督器日志）、准备清单、metrics快照、四题reload及审计报告归档到/workspace/reports；模型checkpoint保留在/workspace/uni-agent-g1/checkpoint。归档清单排除凭据，逐项核内容/摘要后再记为持久化完成；/root/runs会随Pod销毁，不可作为最终唯一证据位置。

退出结论分三列：执行成功 / 有效学习 / 能力提升。任务合法低分可以完成执行层；零梯度不能完成有效学习；四题reload不能完成P2效果对照。P2/P3继续保持未完成。
