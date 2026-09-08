# M2 真实训练准备与薄启动入口

2026-09-08；既有 G1 批准范围细化，不启动模型/GPU，不修改 task manifest。

新增 `examples/harbor/prepare_m2_training.py`：显式参数提供私有 run-spec、训练机可读的 task-dir、output-dir、task-config-path、registration-token-file、worker-token-file。读取当前 task.toml 镜像与整目录 digest，核对冻结 spec 的唯一 task_ref/release；从同目录 instruction.md 生成精确 prompt。注册 hash 复用 RunSpec 规范化（Mac路径保留，不被训练机路径改写）；训练机 credential 路径另外传入。

生成 train.parquet、heldout.parquet、私有 Task YAML、无 token 明文的 launch.json。两份 parquet 使用不同 sample_id/index/split/data_source，题目完全一致，明确仅工程评估，不代表未见题泛化。真实 group/session/partition 仍来自 Framework，不从 dataset 填充可信 context。

新增 `examples/harbor/train_m2_online_rl.py`：读取 launch.json，复用已有 `examples/dsh/train_qwen3_4b_online_rl.sh`；只生成末尾 Hydra overrides：Task YAML、注册 kwargs、Harbor registration postprocessor、替换完整 postprocessor kwargs（先删除旧 trace_root/result_root）、固定单Gateway/单并发。配置值用实际Hydra grammar表达、argv传递，不用shell拼接执行；token值不进入argv/env/PRINT_COMMAND。

底座真实执行末尾接受 "$@"，但 PRINT_COMMAND 分支不打印 "$@"。薄入口 print 模式读取底座打印的命令并追加同一 overrides，生产执行仍只调用底座。测试用Hydra真实解析器合成参数，证明旧postprocessor kwargs已移除、新参数有效；PRINT_COMMAND不可启动训练或探测GPU。

参数/产物目录必须在仓库外且私有。Task YAML含worker token且为0600；launch.json只含token文件路径。禁止覆盖既有输出；当前spec不匹配当前task镜像/目录即失败，不拿旧摘要继续运行。保留底座模型路径、license、依赖及训练超参检查，不复制大脚本。

测试：动态读取镜像；不同sample身份与相同prompt；原始instruction/目录hash核验；私有文件与token不出现在launch/print；真实Hydra override解析、真实PRINT_COMMAND底座调用；同题评估限制记录。真实GPU训练、reward组内差异与提升验证由下一轮处理。

## 可调用入口

在训练机本项目 checkout 根目录运行；下面路径替换为本次真实私有文件，output-dir 必须尚不存在。run-spec 保留 controller 规范化的原字段，task-dir 使用训练机的同内容 checkout，两个 token 文件使用训练机实际安全副本。

```bash
python -m examples.harbor.prepare_m2_training \
  --run-spec-path /workspace/private-m2/run-spec.json \
  --task-dir "$PWD/examples/harbor/m2-file-write" \
  --output-dir /workspace/private-m2/prepared \
  --task-config-path /workspace/private-m2/prepared/task.yaml \
  --registration-token-file /workspace/private-m2/registration-token \
  --worker-token-file /workspace/private-m2/worker-token \
  --train-count 2 --heldout-count 1

PRINT_COMMAND=1 python -m examples.harbor.train_m2_online_rl \
  --launch /workspace/private-m2/prepared/launch.json

MODEL_PATH=/workspace/models/Qwen3-4B MODEL_LICENSE_APPROVED=1 \
PYTHON_BIN=python LOW_VRAM=1 TOTAL_TRAINING_STEPS=1 \
python -m examples.harbor.train_m2_online_rl \
  --launch /workspace/private-m2/prepared/launch.json
```

最后一条会实际启动训练，只在模型/控制隧道/资源均就绪且本次运行获授权时使用；本批测试没有执行它。运行参数如 LoRA rank、rollout n、response length、checkpoint reload 的设置沿用底座环境变量。末尾固定单 Gateway、单任务并发，与当前controller/worker合同一致。

PRINT_COMMAND 保留底座已有预览并追加全部 Harbor overrides；底座预览本身不是生产脚本每一个参数的完整列举。注册token与worker token均不会进入print输出。`task.yaml`包含worker token，必须始终留在私有目录，不能commit。

## 验收结果和已发现行为

12 tests passed（4.01秒）；真实 Hydra override parser 和 ConfigLoader 应用确认先删除旧DSH postprocessor kwargs再装Harbor字段；真实bash底座PRINT_COMMAND调用通过；Ruff check/format全部通过。初始测试实际发现JSON `\\n`不会被Hydra还原为换行，已改为保留argv中的真实换行并针对引号、反斜线、末尾反斜线增加往返检查。

train与heldout是同题不同样本身份；不作为未见任务泛化评估。VERL可重建运行uid，dataset中的sample_id与split用于记录，两者不替代Framework真实group/session/partition。该固定简单任务也不能保证GRPO组内奖励差异或非零学习信号；首轮目标是确认新runtime+Harbor完整工程链路。

入口未硬编码镜像或任务digest，后续主进程更新task.toml后必须生成匹配的新RunSpec，否则准备阶段拒绝。未修改底座训练脚本或task manifest，未启动GPU。
