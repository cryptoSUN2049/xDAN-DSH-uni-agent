# Performance-9B 数据与训练路线研究笔记

日期：2026-09-23

## 结论

目标若是“全面高性能 9B”，不能把 OPD→RL 作为唯一训练路线。主路线应是：高质量 cold-start SFT 建立能力底座，再将可验证子任务送入 RLVR；同时保留一条从官方 instruct/reasoning checkpoint 出发的产品对照线。

DeepSeek-R1 报告显示，base 直接 RL 可以产生推理行为，但容易出现可读性和语言混杂问题；加入少量 cold-start 数据后再做 RL 更稳健，而且大模型推理蒸馏到小模型优于直接在小模型上做 RL。参考：[DeepSeek-R1](https://arxiv.org/abs/2501.12948)。Qwen3 报告强调 thinking/non-thinking 双模式和可调 thinking budget，适合把行为预算作为训练字段，而不是只追求更长 CoT。参考：[Qwen3 Technical Report](https://arxiv.org/abs/2505.09388)。Llama 3.1 的官方说明采用多轮 SFT、rejection sampling 和 DPO，并强调合成数据的质量过滤与跨能力平衡。参考：[Llama 3.1](https://ai.meta.com/blog/meta-llama-3-1/)。

## 本地数据盘点

当前数据画像约 78 集、122.9 GB、估计 1,089 万行，但 S/A 级只是小部分；本地 S 级母本主要是 `GLM-5.1-Reasoning-1M-Cleaned` 与 `hermes-agent-reasoning-traces-glm-5.1`。FABLE 轨迹需要先重组完整会话，`General-Distillation-Prompts-1M` 和 VIBE prompts 需要大规模去重与污染审计，不能直接当 SFT 行数使用。

优先候选：代码/Agent 使用 FABLE、Hunter coding agent、SWE-rebench/Terminal-Lego 与自有 Harbor 轨迹；数学使用 DeepMath、Nemotron Math 等可验证题；工具与办公使用 Hermes、Spreadsheet-RL；搜索与研究使用 OpenResearcher；指令约束使用 IF 多约束数据；安全使用安全 SFT 和工具返回 prompt-injection 轨迹。许可证、来源、重复、基准污染必须在训练 manifest 中逐样本记录。

## 推荐训练矩阵

| 轨道 | 起点 | 用途 |
|---|---|---|
| A 主研究轨 | 官方 9B base → cold-start SFT → RLVR | 可解释、可测量，研究真实增益 |
| B 产品轨 | 官方 9B instruct/reasoning → 小规模 targeted SFT → RLVR | 快速得到可用候选，防止二次对齐退化 |
| C 教师线 | 27B teacher 只生成/打分，不参与 9B 优化器 | 产生高质量轨迹和困难样本 |

SFT v1 按样本数的起始配比：软件工程/代码/Agent 30%；通用推理、数学、科学 20%；工具调用、规划、多轮 15%；普通指令、写作、对话 10%；中文/多语种 10%；安全、拒答、注入、事实校准 10%；长上下文、压缩、记忆 5%。最终按有效 token 数复核，避免长 CoT 让数学/推理意外占满训练。

首轮使用 10–30 万条高质量样本（约 1–3B 有效 tokens，按长度裁剪和预算限流），通过验证后再扩容。每个样本至少记录 `source/teacher/license/domain/language/difficulty/verifier/quality/contamination`。

## 数据门槛

1. license 与来源白名单；schema、tool call、对话角色可解析。
2. prompt hash、MinHash/embedding 近重复清理；与所有 sealed/eval 集做 n-gram 和语义污染检查。
3. 代码样本必须可执行并通过测试；数学/结构化任务必须有可验证答案。
4. teacher agreement、verifier 或人工 rubric 至少满足一种强证据；拒答与安全数据要保留良性对照。
5. 同一任务尽量保留 thinking/non-thinking 成对版本，并标注 token/turn budget。
6. RL 训练池用 9B pilot 估计 pass@4，只选约 0.2–0.8 成功率的题；全对/全错题移到 eval 或低权重池。

## 执行阶段

`G0` 冻结数据 manifest、许可证与污染报告；`G1` 做 2–4 步 SFT smoke 和 fixed validation；`G2` 做 10–30k 条 cold-start SFT；`G3` 做 4–8 步 RLVR pilot 并启用自动止损；`G4` 进行正式 RL，按数学/代码/Agent 分池交替；`G5` 做 rejection sampling/DPO 与安全回归；`G6` 对 base、SFT、RL checkpoint 运行 sealed benchmark。

每一步都保存 checkpoint、W&B run、manifest、验证结果和停止原因；RL 必须同时记录有效混合组比例、短组、基础设施失败、token/turn 预算和成本。

## Ornith 外部参考

[Ornith-1.5 官方训练说明](https://ornith.ai/ornith_1_5.html) 与 [Hugging Face model card](https://huggingface.co/ornith-ai/Ornith-1.5-9B) 报告其路线包含 continued pretraining、mid-training、post-training，并联合优化任务生成、scaffold 与 rollout；官方页面还将闭环描述为“模型提出任务、生成任务 scaffold、产生 RL rollout”。其 reward 设计强调 validity、frontier difficulty、novelty、task alignment、reward fidelity 和 hack resistance，这正好说明 RL 题池与 verifier 是一等训练资产。9B BF16 约 19 GB，可单 80 GB GPU 服务。其公开结果包括 SWE-bench Verified 70.6、Terminal-Bench 2.1 46–47、GPQA Diamond 86.4，但使用特定 harness、上下文长度和五次平均，不能直接与本项目分数横比。应将其作为外部基线和方法参考，而不是直接复制数据或结论。

Ornith 的方法可转成我们的三个工程改动：先用 base/instruct pilot 估计每个任务的成功率，再把主 RL 池放在 frontier 区间；为每个任务保留 scaffold、工具约束和 verifier 版本；将 novelty 与 reward-fidelity 作为准入字段，防止“通过了但学的是漏洞”。这不是把任务生成器直接接进生产训练，而是先把 `performance-9b-data-v1` 的题池校准做好。
