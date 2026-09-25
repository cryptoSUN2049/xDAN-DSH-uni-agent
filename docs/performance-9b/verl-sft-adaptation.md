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

## 仍未宣称

这是格式和 tokenizer/loss-mask smoke 通过，不是训练 ready。20K 分域抽样、固定 validation/sealed split、GPU SFT 前向/反向和 W&B/VERL 训练观测仍未完成。

正式训练须遵守 `docs/performance-9b/uv-runbook.md`：venv、uv cache、runs 全部位于 `/workspace/verl-uni-agent-harbor-opd-rl/`，GPU lane 另行通过 workspace bootstrap 验收。
