# VERL SFT 适配状态

更新：2026-09-25

## 已验证

- 结构母本 `apus-sft-v1` 已导出为 VERL SFT Parquet：62,030/62,030，拒绝 0。
- Parquet 的 `messages`、`tools` 使用 JSON 字符串，避免动态工具参数生成不稳定 Arrow struct；APUS dataset adapter 在读取时解码。
- Qwen3.5-9B 的多轮 system/user/assistant 轨迹通过累计前缀 tokenization 处理；assistant generation header 置零，assistant 输出保留 loss mask。
- 普通样本 smoke：1,247 tokens、48 loss tokens。
- 真实 assistant tool-call 样本 smoke：1,341 tokens、135 loss tokens，VERL dataset 返回正常。

## 为什么保留最小 adapter

VERL 原生 `MultiTurnSFTDataset` 仍可作为底层训练器，但它的默认路径有两个与本数据实际不兼容的假设：

1. Arrow nested struct 假设所有工具参数共享固定 schema；本数据是动态工具参数。
2. 逐消息渲染假设单独 system 消息可被 Qwen3.5 template 渲染，且逐消息拼接等于完整对话渲染。

因此 APUS 只增加一个薄 adapter：Parquet JSON 字符串解码、累计前缀 tokenization、assistant header mask，以及对完整 chat-template 的等价校验。训练器、优化器、FSDP、W&B 仍使用 VERL 原生实现。

## VERL 原生脚本与本项目启动器

VERL 已经提供现成的 SFT 入口：`torchrun -m verl.trainer.sft_trainer`。可直接参考仓库中的
`verl/examples/sft/gsm8k/run_qwen2_5_0_5b_fsdp.sh`、
`verl/examples/sft/multiturn/run_qwen2_5_0_5b_fsdp.sh` 和
`verl/examples/sft/gsm8k/run_qwen3_30b_automodel.sh`。这些脚本的核心只有数据路径、模型路径、`engine=fsdp`（或 `automodel`）、批大小、总步数和日志配置。

本项目的 `examples/performance_9b/run_verl_sft.sh` 不是另写一套训练器，而是在这个原生入口外包一层：固定 workspace 环境、检查数据/模型、配置 `custom_cls`、记录启动命令和退出码，并把 W&B 与可选 rl-insight 接入。当前 9B 单卡 smoke 已用 FSDP SFT 原生训练器成功跑通 1 step；全量训练仍需先完成 loss-mask、长度截断和数据准入门禁。

## FSDP、Megatron 与 attention backend

当前选择的是 VERL SFT 的 PyTorch FSDP engine；Megatron 是另一条可选后端，不是 SFT 的必需项。`SDPA` 只是 PyTorch attention backend，也不是训练器。当前 workspace 的 PyTorch/CUDA 组合没有安装 `flash-attn`（同时也缺少 `causal-conv1d`），所以 smoke 使用 `model.override_config.attn_implementation=sdpa`。这表示可运行的兼容路径，不表示 FlashAttention 已被证明不兼容；后续应在独立环境安装并验证匹配的 FlashAttention wheel，再比较吞吐、显存和 packed-sequence 边界结果。

## 仍未宣称

这是格式和 tokenizer/loss-mask smoke 通过，不是训练 ready。当前 adapter 还没有把审计字段中的 `target_message_index` 实现为逐目标消息监督；现行路径会对所有 assistant 输出计算 loss，因此不能把现有 smoke 当成最终蒸馏数据的监督语义验收。20K 分域抽样、固定 validation/sealed split、GPU SFT 前向/反向后的长序列/packed 边界验证，以及 rl-insight 后端是否真正收到 trace，仍未完成。

正式训练须遵守 `docs/performance-9b/uv-runbook.md`：venv、uv cache、runs 全部位于 `/workspace/verl-uni-agent-harbor-opd-rl/`，GPU lane 另行通过 workspace bootstrap 验收。
