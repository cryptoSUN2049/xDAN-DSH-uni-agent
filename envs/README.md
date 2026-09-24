# APUS performance-9b 环境重建

当前数据质量验收完成前不启动 GPU。环境名称固定为：

| 名称 | 用途 | 资源 |
|---|---|---|
| `performance-9b-data` | 原始归档、格式转换、去重、来源补证、质量报告 | CPU Runpod |
| `performance-9b-harbor-rl` | ms-swift/VERL、Harbor、vLLM、W&B 训练与评测 | 双 RTX PRO 6000 |

## CPU 数据环境

在仓库根目录执行：

```bash
uv venv /workspace/envs/performance-9b-data --python 3.12
uv sync --project envs/performance-9b-data --no-install-project
```

运行时必须使用：

```bash
export VIRTUAL_ENV=/workspace/envs/performance-9b-data
export PYTHONNOUSERSITE=1
"$VIRTUAL_ENV/bin/python" ...
```

## Harbor/VERL GPU 环境

该配置只在数据 `training_ready=true` 后执行。Runpod 上从仓库根目录执行：

```bash
uv venv /workspace/envs/performance-9b-harbor-rl --python 3.12
uv sync --project envs/performance-9b-harbor-rl --no-install-project
```

GPU 版本必须在 Linux/CUDA Runpod 上锁定并回读 `uv.lock`；不能在 macOS 上生成后直接当作 CUDA 锁文件。安装后保存：

```bash
uv pip freeze --python /workspace/envs/performance-9b-harbor-rl/bin/python \
  > docs/performance-9b/environment-freeze-runpod.txt
```

训练启动前的强制环境验收：Python 3.12、`VIRTUAL_ENV` 对所有 Ray worker 一致、`PYTHONNOUSERSITE=1`、torch/vLLM/Ray/VERL/Uni-Agent/Harbor/W&B import 成功，且两卡显存和 CUDA capability 记录入 manifest。出现版本漂移时停止，不在训练中临时 `pip install`。

## 当前已知基线

历史实测的 Harbor/VERL 验收环境记录在 `docs/performance-9b/pipe-r11/pipeline-summary.jsonl`：torch 2.11.0、vLLM 0.23.0、Ray 2.54.1、Harbor 0.16.1、Modal 1.5.5、W&B 0.30.0。它是重建基线，不代表当前机器已经安装；重建后必须重新生成 freeze 和 import 验收证据。

