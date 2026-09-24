# Qwen3.8-Max 蒸馏数据复核

2026-09-24。用户要求补搜Qwen3.8-Max。已对照《数据画像》并检索HF `qwen3.8`（返回上限100项，不声称穷尽全部），读取以下3库固定revision卡。没有下载全量或改变当前1K配方。

## 候选与用途

| 来源 | 卡片规模与教师 | 建议 |
|---|---|---|
| [r0b0tlab/qwen3.8-max-distillation-50k](https://huggingface.co/datasets/r0b0tlab/qwen3.8-max-distillation-50k) | 49772条；qwen3.8-max-preview。数学16597、代码14057、推理11690、IF7302、tool126 | 数学/指令/通用推理研究候选，不是长程Agent主料；当前不加入产品训练 |
| [r0b0tlab/qwen3.8-max-glm5.2-kimi-k3-distillation](https://huggingface.co/datasets/r0b0tlab/qwen3.8-max-glm5.2-kimi-k3-distillation) | 57937条：Qwen48283、GLM5307、Kimi4347；不同SFT/工具/agent/canonical视图 | 优先从canonical追溯Qwen来源，再筛目标能力；不能把全部工具轨迹归给Qwen |
| [bunnycore/qwen3.8-max-glm5.2-kimi-k3-sft-balanced](https://huggingface.co/datasets/bunnycore/qwen3.8-max-glm5.2-kimi-k3-sft-balanced) | 同一混合库sft_balanced重打包，57937条 | 读取便利的候选，非新增独立数据；与上游二选一，必要时回连canonical身份 |

固定revision：单教师 `ab9f8b289423c249fc0054507f045a12efb54b1b`；混合库 `7a3473446840bcc397928cd8183d4b3ba3ca13a7`；balanced镜像 `6c7c5daa0d2642321a076ddf003c1516be6b7620`。

这里teacher是Max-Preview，不自动等于后续最终Max版本；更不是本地27B教师。三个名字不可互换。

## 放行前真实缺口

1. **质量与执行**：单教师卡明确评分是启发式，未逐题独立验真。99%含代码块/boxed不等于正确。只有126条工具题，不能承担工具Agent基础。
2. **评测污染**：题目来源包含GSM8K/MATH/HumanEval/MBPP/ARC/IFEval等，卡明确包含benchmark splits。随机90/5/5不保证我们评测独立，必须按原始题ID/题面/任务族排除重叠。
3. **来源用途条款**：单教师卡license=other，明确提示Model Studio输出的训练用途限制及部分上游非商用来源。本报告只转述该卡的限制提示，不替代适用协议核验；对APUS产品训练先保持未放行。去掉某些NC题不自动解决教师服务条款。
4. **混合库不能绕过上游问题**：混合卡的部分上游许可描述与单教师卡冲突，例如SciQ。逐来源原始许可核对，不采信较宽松的一项；镜像也不产生新权利。
5. **读取与计数**：多config可能是同一数据的不同导出视图，不能把它们相加。画像记有自动发现文件导致膨胀风险；加载时显式固定文件、config、revision，用canonical ID/hash验收。
6. **监督坐标**：GLM预tokenized数据不能直接用于APUS；使用结构化messages由实际tokenizer重新渲染，验证mask。卡称mask通过是上游实现结论，不是我们的验收结果。
7. **覆盖**：混合库卡称86.7%单轮、84.6%reasoning，多语言仅0.8%。不能因教师为Qwen便认定它补齐中文办公/翻译。

## 当前配方决定

保留Fable＋GPT5.6核心400及工作领域600的v2目标；Qwen Max进入“补充候选/条件审计”，当前训练配额0。若用途条款、数据污染与质量验收通过，先抽样约100条（审计样本，不是训练配额），比较指令、短推理、多语种及工具子集的独立价值，再做同token预算替换实验。

不把r0b0tlab的单教师50k、混合库和各镜像全部并入。排除将27B评测轨迹（例如TB2.1成功答案）误当Max训练数据。

[当前主配方](agent-sft-data-plan-v2.md) · [强教师复核](strong-teacher-sft-review.md)
