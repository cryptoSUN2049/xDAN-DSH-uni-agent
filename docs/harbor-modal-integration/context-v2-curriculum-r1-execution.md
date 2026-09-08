# Context v2：12 题完整课程启动准备

状态：CPU 准备核验完成后，主线程已确认 GPU 空闲并实际启动课程 supervisor `162712`（plan/supervisor.pid）；尚未完成训练/消费/效果验收。固定 integration `d3084f2a771804f011c4e641ecf0986c7166bc86`、VERL `fefb080262e1c015a0ea05f958822a6a512dc795`、Qwen3-4B `1cfa9a7208912126459214e8b04321603b3df60c` 与 DSH SDK/runtime 0.1.3a2。所有任务来源与 verifier bundle 保持原 v2，不修改 v1 和旧两步运行。

## 准备产物与核验

- data：`/root/runs/context-v2-curriculum-r1-data`；planned run：`/root/runs/context-v2-curriculum-r1`。
- 独立 plan：`/root/runs/context-v2-curriculum-r1-plan`，避免新增文件改变数据清单的原始闭包。
- 12 个唯一 train task ID、4 个唯一 validation task ID，身份无交叉；metadata split、verifier digest 与来源/输入文件摘要均检查通过。完整身份清单见配套 preparation JSON。
- 从 data cwd、绝对 PYTHONPATH 启动所选 Python，实际导入当前 checkout 的 context_verifier_v2，bundle `d8548f9c4173a78455e5b66a0d69686d8ded8385695bfcb4b3c172cd9841b546` 一致。
- 运行方式仍为既有 ops launcher → DSH/runtime/Gateway/TQ → sync GRPO，非 SFT、非 Harbor、非额外 DSH 外循环。

准备目录的 training.env 仍保留准备器默认两步/VAL_ONLY=True；此次运行的显式覆盖保存在 plan/launch-environment.json，不能仅 source 原 training.env 就宣称按12步启动。

## 可复用启动清单

plan 包含 `preparation-audit.json`、`launch-environment.json`、`training.argv.json`、`supervisor.argv.json`、`print-command.txt`。环境为显式白名单，无 API token、PAT、SSH 私钥或其他敏感环境值；不继承 RAY_ADDRESS/PYTHONHOME。不要修改这些清单来跳过源摘要核验。

主线程确认 GPU 空闲和本轮顺序后，在远端执行以下命令；主线程已使用该清单启动，本 run 不可再次执行以下启动命令；它保留为复建操作记录：

```bash
/workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python - <<'PY'
import json, pathlib, subprocess
p = pathlib.Path('/root/runs/context-v2-curriculum-r1-plan')
argv = json.loads((p / 'supervisor.argv.json').read_text())
with (p / 'supervisor.log').open('xb') as log:
    child = subprocess.Popen(argv,
        cwd='/workspace/rebuild/uni-agent-native-n0-r1',
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/root',
             'CUDA_VISIBLE_DEVICES': '', 'PYTHONUNBUFFERED': '1'},
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
(p / 'supervisor.pid').write_text(str(child.pid) + '\n')
print(child.pid)
PY
```

内联入口已经 compile 校验；启动前重新检查 integration/VERL HEAD、清单/source/input/runtime/model config 摘要和 cross-cwd verifier 导入，拒绝复用 run、`/tmp/dsh-cv2c1` 或 checkpoint。仅在通过后调用既有 `harbor_training_supervisor.supervise`，health 回调为空；这里复用进程监督能力，不依赖 Harbor 服务。

训练进程使用计划环境的 CUDA_VISIBLE_DEVICES=0；上面外壳 CUDA 为空不影响子进程明确覆盖。墙钟7200秒、轮询5秒、超时TERM宽限30秒，监督仅停止自己创建的进程组，后续须核后台Ray/vLLM资源归属，不能全局pkill。

## 参数与上游行为

| 项目 | 生效值 |
| --- | --- |
| 模式 / 算法 | sync / GRPO |
| train batch / 同题采样 | 1 / n=4 |
| 总步数 / epoch | 12 / 1 |
| save / test | 6 / 6，另 val_before_train=True |
| dev n | 1 |
| checkpoint | /workspace/uni-agent-g1/checkpoint/context-v2-curriculum-r1 |
| 内存 | 原课程 offload、LoRA16、GPU memory .30、max seq1 保持 |

`train_qwen3_4b_online_rl.sh` 实际命令透传步数/save/test，并已固定 total_epochs=1；ops 前台命令保留这些环境和尾参数。PRINT_COMMAND 分支漏列 test_freq/epochs，因此尾参数显式追加 `trainer.total_epochs=1 trainer.test_freq=6 trainer.default_local_dir=...`，已实际打印核验关键值。打印命令不是完整部署命令，不能直接拿它替代 ops 执行。

VERL `trainer/ppo/v1/trainer_base.py` 使用 StatefulDataLoader，batch1、drop_last=True，steps_per_epoch=12；`ppo/utils.py` 的 shuffle 使用 RandomSampler。一个完整正常 epoch 计划消费12题；同步失败组 refill 或提前中止可能改变尝试数量，因此必须报告实际消费，而非假定12步=12个有效唯一题。

## 验收与失败边界

分别统计12题中实际消费唯一数、48次计划训练尝试的实际完成/拒绝数、非零advantage组、逐族 reward/semantic/citation/严格准确率，以及 optimizer step、LoRA变化、base冻结。全部同分的组仍可完成工程步骤，但不能当作新任务学习信号。计划保存step6/12，不覆盖旧step1/2。12步学习率调度周期与旧两步不同，不称旧run精确延续。

按run/supervision/train.log和supervisor-result.json跟踪，再复用消费审计与独立reload。4题dev仍为公开开发集；本课程也不是封存泛化测试。模型revision属于固定声明身份，本次测量config与runtime/source摘要，不声称重新向Hub证明全部权重来源。
