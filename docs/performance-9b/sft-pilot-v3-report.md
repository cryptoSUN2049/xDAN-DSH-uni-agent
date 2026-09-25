# Performance-9B VERL SFT pilot v3

更新时间：2026-09-25 05:08 UTC

## 结果

双 RTX PRO 6000 Blackwell 的 cu128 lane 已完成一次真实 VERL FSDP SFT pilot。运行退出码为 `0`，前向、反向、验证、W&B 同步和 FSDP checkpoint 均成功。

| 项目 | 值 |
|---|---|
| Runpod | `db7kewdkd71js6`，SSH `157.157.221.177:11403` |
| 环境 | `performance-9b-sft-py312-cu128`，Torch 2.8.0+cu128 |
| 模型 | `/workspace/models/Qwen3.5-9B` |
| 数据 | `/workspace/apus-data-cleaning/reports/verl-sft-v1` |
| 训练 | FSDP、bf16、FlashAttention2、LoRA rank/alpha `16/16`、dynamic batch |
| 规模 | 512 train samples、64 validation samples、16 steps、2 GPUs |
| 运行目录 | `/workspace/verl-uni-agent-harbor-opd-rl/runs/performance-9b-sft/verl-sft-cu128-pilot-v3-20260925T0508Z/` |
| W&B | [92602dg0](https://wandb.ai/xdan-ai/xDAN-performance-9b/runs/92602dg0) |
| Checkpoint | `global_step_8`、`global_step_16`，每个包含双 rank model/optimizer/extra state |

末步指标：`train/loss=1.1307890`、`train/grad_norm=0.85546875`、`val/loss=1.0285366`。16 步均有有限梯度；loss、grad norm、global tokens、显存和验证 loss 同时写入 `metrics.jsonl` 与 W&B。训练结束时两张 GPU 显存均为 0 MiB，未遗留训练进程。

## 运行中发现并修复的问题

1. 全量尝试在第 1 个真实训练 step 后触发 `chat template prefix is not token-prefix stable`。根因是 Qwen3.5 模板依赖最后一个 user turn，逐消息累计渲染不是稳定 token prefix。全量运行目录为 `verl-sft-cu128-full-20260925T0432Z`，该目录保留失败证据。
2. 第一版修复后，pilot v2 把 Qwen3.5 的 vision processor 当作文本 tokenizer 调用，触发图片解码错误。文本路径现在明确调用 tokenizer，并请求 `return_offsets_mapping=True`。
3. 当前 adapter 改为完整渲染一次，再按 `<|im_start|>assistant` 到 `<|im_end|>` 的 character offsets 生成 assistant body mask。纯逻辑位于 `examples/performance_9b/verl_sft_mask.py`，本机回归测试覆盖普通多轮与缺失结束标记。

## 观测边界

W&B 和本地 `train.log`/`metrics.jsonl` 已完成对账。rl-insight 服务已启动并传入 logger，但 native `torchrun` 没有初始化 Ray，日志为：`Ray is not initialized; monitoring is disabled`。因此本次只能标记“rl-insight 服务可用、Ray monitor trace 未验收”，不能把 logger 配置当成后端 trace。

## 训练决策

这不是全量训练完成的证明。旧全量配置的 29,582 steps 不能按 pilot 的启动时间直接外推；在当前 batch/长度设置下，未经独立吞吐测量就启动长跑会带来多日成本。下一步应先固定已审计的 20K 分域子集和 sealed validation，重跑有界 pilot，确认数据准入、长序列截断、checkpoint 可读性和能力曲线，再决定是否扩展到 59,164 条训练分片。
