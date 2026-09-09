# memory-resident-train-r1：已作废，不可启动

**状态纠正：此训练准备仅保留为历史证据，不可启动。** 同源码 `4168b628` 的真实 val r1 在 NativeMemoryFramework 构造时因上游默认注入非空 reward handles 被拒绝，说明此前 CPU 准备检查未覆盖真实入口的默认注入。主线程已停止该 val 的 owned 进程组。框架修复后必须使用新 commit、新 prepare 和全新 run；不得沿用本清单或覆盖原 JSON。原准备摘要和 JSON 保留，不能据此声称集成已通过。

2026-09-09，仅生成新训练数据和启动清单，未调用 `launch`，未占用/停止 GPU，未修改正在执行 val 的源码或产物。

- checkout：`/workspace/rebuild/uni-agent-memory-resident-r1`，实际 HEAD `4168b628f3a2ff4c301dcffb60f016f8ecb770f2`。
- VERL：`fefb080262e1c015a0ea05f958822a6a512dc795`。
- SDK/runtime：均为 `0.1.3a2`；实际二进制 SHA `d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb`。
- 模型：固定 Qwen3-4B 基座 `1cfa9a7208912126459214e8b04321603b3df60c`，`RESUME_MODE=disable`；不是 val 生成的 checkpoint。
- 数据：`/root/runs/memory-resident-train-r1-data`，1 train / 1 validation、constraints 固定诊断族；两条身份不同不代表独立场景或隐藏留出集。
- 清单：`manifest.json` SHA `2897f8faebf86dc599317bb782d76eab6fdeb4996fb4856ad8a4fe859c9341c7`。
- 清单 44 个 source 均被 Git 跟踪，tracked diff 为空；4 个准备产物 hash、runtime/model 文件摘要、跨 cwd 导入与 SDK/runtime 探针均通过。现有未跟踪 `dsh-memory-resident/` 是正在运行任务的指标目录，未清理或修改。
- 准备时独立 run、checkpoint、Ray 目录均不存在；只有 data 和 `/root/runs/memory-resident-train-r1-plan/preparation-audit.json` 已创建。

真实生成的 argv 选择 `NativeMemoryFramework`、all trajectories、旧静态 postprocessor 三项清空；sync、train n4、val n1、batch1、LoRA16、1 step、save/test1，GPU memory .30、8192+8192 tokens、actor/optimizer offload。墙钟上限7200秒，checkpoint指向 `/workspace/uni-agent-g1/checkpoint/memory-resident-train-r1`。

以下为原清单的历史启动命令，本次**未执行，现已作废，禁止照此启动**。待修复版本固定后，须重新 prepare 新数据、新 run 并使用新 manifest；此处命令仅保留用于审计：

```bash
cd /workspace/rebuild/uni-agent-memory-resident-r1
env -u PYTHONHOME -u RAY_ADDRESS -u PYTORCH_CUDA_ALLOC_CONF \
 CUDA_VISIBLE_DEVICES='' PYTHONPATH="$PWD:$PWD/verl" \
 /workspace/venvs/uni-agent-rebuild-cf2d3f5/bin/python \
 -m examples.dsh.capabilities.prepare_memory_training launch \
 /root/runs/memory-resident-train-r1-data/manifest.json
```

启动器会再次 CPU 校验，并在真正子进程环境中设置 CUDA=0、核 GPU 空闲、创建私有 roots、执行 owned supervisor。若本 checkout 或清单变了，应新建 run 重新 prepare，不覆盖当前清单。完整 argv/environment 见 [原始准备审计](memory-resident-train-r1-preparation.json)。

验收边界：当前 `training=false`、未证明 n4 消费或权重更新。如果实际 B 四条同分，应报告零优势/无新学习信号；不能人工改变奖励制造方差。后续须另查真实链消费及版本绑定、参数/optimizer与checkpoint；本准备不代表训练成功。
