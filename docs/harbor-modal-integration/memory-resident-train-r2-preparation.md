# memory-resident-train-r2：CPU 准备通过，等待 val-r2 验收

本批仅 prepare/check，未 launch、未训练。2026-09-09 在新独立 checkout `/workspace/rebuild/uni-agent-memory-resident-r2` 完成；旧 train-r1 作废清单和失败证据均未覆盖。

| 核验项 | 实测 |
|---|---|
| 集成 HEAD | `c5dacdc7ff90ad7cb15e826b41b0f6748c2139f0` |
| VERL | `fefb080262e1c015a0ea05f958822a6a512dc795` |
| SDK/runtime | `0.1.3a2` / `0.1.3a2` |
| Runtime 字节 SHA | `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb` |
| 学生模型 | 固定 Qwen3-4B 基座 `1cfa9a7208912126459214e8b04321603b3df60c`；`resume=disable` |
| 真实源码 | 44 个文件均 Git 跟踪，tracked 与 staged diff 均空，hash 通过 |
| 数据 | 4 个文件 hash 通过；constraints 单族、1 train / 1 validation |
| 清单 SHA | `89b26d155ff29a132cf049c51d07a641f93c5984a148027af5990cb1e6ba2b42` |
| 跨 cwd | 在新 data 目录隐藏 CUDA 后导入，framework 与 stage 都来自 r2 checkout |
| 运行状态 | run、checkpoint、Ray roots 均未创建；无 GPU 启动 |

准备清单位于 `/root/runs/memory-resident-train-r2-data/manifest.json`，完整 source/input 摘要与 CPU 审计位于 `/root/runs/memory-resident-train-r2-plan/preparation-audit.json`，本地副本见 [准备审计 JSON](memory-resident-train-r2-preparation.json)。环境沿用已验收 venv `/workspace/venvs/uni-agent-rebuild-cf2d3f5`；该 venv 的旧 editable 路径由明确的 r2 绝对 PYTHONPATH 定位，另有跨目录真实 import 路径证据。

真实 argv 选择 NativeMemoryFramework、all trajectories、静态 postprocessor=null；sync、n4/val1、batch1、1 step、save/test1、LoRA16、GPU memory .30、8192+8192 token预算、actor/optimizer offload，墙钟7200秒。Checkpoint目标为 `/workspace/uni-agent-g1/checkpoint/memory-resident-train-r2`。

**等待主线程 val-r2 实际验收后再决定启动。** 本次未执行以下命令：

```bash
cd /workspace/rebuild/uni-agent-memory-resident-r2
env -u PYTHONHOME -u RAY_ADDRESS -u PYTORCH_CUDA_ALLOC_CONF \
 CUDA_VISIBLE_DEVICES='' PYTHONPATH="$PWD:$PWD/verl" \
 /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
 -m examples.dsh.capabilities.prepare_memory_training launch \
 /root/runs/memory-resident-train-r2-data/manifest.json
```

若源码或清单改变，重新 prepare 新 run。当前 val 没有产生训练 checkpoint，不能把本次基座称为 val 训练后的模型。固定诊断族的 train/val 不是独立能力留出；n4 全同分时必须报告零优势/无新增学习信号，不能制造奖励方差。CPU准备通过不替代真实构造、A/B采样、消费、更新和reload验收。
