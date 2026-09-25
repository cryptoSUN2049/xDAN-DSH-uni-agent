# VERL SFT 适配状态

更新：2026-09-25

## 已验证

- 结构母本 `apus-sft-v1` 已导出为 VERL SFT Parquet：62,030/62,030，拒绝 0。
- Parquet 的 `messages`、`tools` 使用 JSON 字符串，避免动态工具参数生成不稳定 Arrow struct；APUS dataset adapter 在读取时解码。
- Qwen3.5-9B 的多轮 system/user/assistant 轨迹先完整渲染一次，再用 tokenizer 的 character offsets 标记 assistant body；assistant header、user、tool 和 padding 都不参与 loss。
- 普通样本 smoke：1,247 tokens、48 loss tokens。
- 真实 assistant tool-call 样本 smoke：1,341 tokens、135 loss tokens，VERL dataset 返回正常。
- 双 RTX PRO 6000 的真实 FSDP SFT pilot v3 已完成 16 步，训练、反向、验证和 checkpoint 均成功；W&B run 为
  [92602dg0](https://wandb.ai/xdan-ai/xDAN-performance-9b/runs/92602dg0)。

## 为什么保留最小 adapter

VERL 原生 `MultiTurnSFTDataset` 仍可作为底层训练器，但它的默认路径有两个与本数据实际不兼容的假设：

1. Arrow nested struct 假设所有工具参数共享固定 schema；本数据是动态工具参数。
2. 逐消息渲染假设单独 system 消息可被 Qwen3.5 template 渲染，且逐消息拼接等于完整对话渲染。

因此 APUS 只增加一个薄 adapter：Parquet JSON 字符串解码、完整渲染后的 offset mask，以及保留给诊断的完整 chat-template 校验。训练器、优化器、FSDP、W&B 仍使用 VERL 原生实现。mask 规则本身位于无 VERL 依赖的 `verl_sft_mask.py`，可单独回归测试。

2026-09-25 的真实运行暴露并修复了两个问题：第一，旧的逐消息累计 tokenization 在多轮 Qwen3.5 对话上触发 prefix instability；第二，把 Qwen3.5 的 vision processor 当作普通文本 tokenizer 调用会尝试解码字符串图片。当前实现分别用 full-render offsets 和 tokenizer 文本编码解决。

## VERL 原生脚本与本项目启动器

VERL 已经提供现成的 SFT 入口：`torchrun -m verl.trainer.sft_trainer`。可直接参考仓库中的
`verl/examples/sft/gsm8k/run_qwen2_5_0_5b_fsdp.sh`、
`verl/examples/sft/multiturn/run_qwen2_5_0_5b_fsdp.sh` 和
`verl/examples/sft/gsm8k/run_qwen3_30b_automodel.sh`。这些脚本的核心只有数据路径、模型路径、`engine=fsdp`（或 `automodel`）、批大小、总步数和日志配置。

本项目的 `examples/performance_9b/run_verl_sft.sh` 不是另写一套训练器，而是在这个原生入口外包一层：固定 workspace 环境、检查数据/模型、配置 `custom_cls`、记录启动命令和退出码，并把 W&B 与可选 rl-insight 接入。pilot v3 使用 2 卡、LoRA rank 16、bf16、FlashAttention2、动态 batch 和 16 步上限，已完成真实前向/反向、两次验证和两个 FSDP checkpoint。

## FSDP、Megatron 与 attention backend

当前选择的是 VERL SFT 的 PyTorch FSDP engine；Megatron 是另一条可选后端，不是 SFT 的必需项。`SDPA` 只是 PyTorch attention backend，也不是训练器。cu128 workspace 已安装并通过 CUDA forward smoke 的 `flash-attn==2.8.3.post1` 与 `causal-conv1d==1.7.0`，pilot v3 实际使用 `flash_attention_2`。这证明当前双卡 lane 可运行，不代表所有 CUDA 镜像都兼容；环境必须继续由 `uv-runbook.md` 的 freeze 文件重建。

## 仍未宣称

当前 adapter 会对完整轨迹中的所有 assistant 输出计算 loss，尚未使用审计字段中的 `target_message_index` 做逐目标消息监督；因此 pilot 只证明训练链路和 mask 机械正确，不等于最终蒸馏语义已经验收。20K 分域抽样、固定 validation/sealed split、长序列/packed 边界验证仍需单独完成。pilot 传入了 `rl_insight` logger，但原生 torchrun SFT 没有初始化 Ray，日志明确为 `Ray is not initialized; monitoring is disabled`；rl-insight 服务已启动，但本次不能宣称产生了 Ray monitor trace，W&B 与本地 JSONL 才是本次有效观测证据。

正式训练须遵守 `docs/performance-9b/uv-runbook.md`：venv、uv cache、runs 全部位于 `/workspace/verl-uni-agent-harbor-opd-rl/`，GPU lane 另行通过 workspace bootstrap 验收。
