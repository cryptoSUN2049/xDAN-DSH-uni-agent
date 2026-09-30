# R21 网盘 uv 环境复用

当前双卡 Pod `vo6u0t8x398bnm`，SSH `157.157.221.30:51913`，挂载原网络卷 `72jdno5cuk` 到 `/workspace`。

## 环境位置

- venv：`/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1`
- Python：上述目录的 `bin/python`。
- 锁定清单：`/workspace/verl-uni-agent-harbor-opd-rl/src/uni-agent/deployment/versions/uv-lanes/ua-verl-py312-vllm023.freeze.txt`。
- 清单 SHA256：`e9f87349997a81b7fbc31ef1ce74f9abb078c37600282d4684c63c75514c4dc7`。

实际 metadata：Python 3.12.3、Torch 2.11、vLLM 0.23、Transformers 5.8、Ray 2.54.1、Modal 1.5.5、W&B 0.30。当前实际 CPU preflight 已核对全部 273 项依赖，未重装。

目录中的 `ws1` 是历史命名。当前训练配置是 world size 2、FSDP1、`colocate_async`，目录名不决定 GPU 数量。

## 训练需要同时绑定的路径

- 固定训练源码：`/workspace/mimo-dsh-rl-20260928/run-src-r20`。
- CuPy overlay：`/workspace/mimo-dsh-rl-20260928/env-overlays/r10-cupy/packages`。
- NCCL 库：venv 内的 `lib/python3.12/site-packages/nvidia/nccl/lib`。
- 模型：`/workspace/models/MiMo-V2.6-Distill-Qwen-9B`，revision `2367e865d009c13ac81713a2878291d33ab28177`。
- 控制 helper：`/workspace/mimo-dsh-rl-20260928/audit-code/r21-operator-runtime`，冻结自 commit `b053bde`，独立于固定训练源码。

本轮使用冻结 operator 的 `environment(plan, cpu=...)` 校验并设置这些路径。仅 `source bin/activate` 不会完成源码/overlay/服务配置绑定；不要从旧 installed 包启动，也不要对该共享环境执行 `uv sync` 升级依赖。

## 当前回执与边界

- `evidence/r21-r20f-preflight.json`：273 项依赖、实际新任务 Parquet、原生 C4 loader 恢复检查通过；CUDA 未初始化。
- `evidence/r20f-ray-env-inheritance-validation-20261001.json`：实际 Ray CPU worker 继承 RL-Insight 启用变量和服务地址。
- `evidence/r20f-supervisor-startup-20261001.json`：后台监督器已启动；此启动回执不声称有效 C5 已验收。

本轮训练私有日志为 `/root/mimo-private/launch-r20f/train.log`；W&B run 为 `xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/mimo9b002549r20f`。固定成本截止是 2026-10-01 08:04:33 SGT，不因恢复或重启顺延。
