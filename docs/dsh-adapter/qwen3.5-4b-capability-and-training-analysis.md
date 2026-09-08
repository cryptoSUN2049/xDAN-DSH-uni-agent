# Qwen3.5-4B benchmark 与 Uni-Agent 快速提效分析

2026-09-08；本地代码基线 `9b7dbdb78cb5f0bb0f28e90515050ea5d476d8cf`，verl `fefb080`。本轮研究分析，不修改产品代码、不启动模型/GPU/付费服务。

## 直接执行

### 结论

Qwen3.5-4B 已有较强的知识、指令遵循和视觉基础。结合本仓能力，最值得优先投入的是 **任务内记忆、DSH工具使用与错误恢复**，其次是边界清晰的代码修复。开放式长程规划、GUI、跨会话记忆和自动RSI的接线与验证成本更高。

“最快复用已有完整训练实验”优先 MemAgent/HotpotQA；“最快服务当前DSH产品目标”优先 DSH 工具生命周期和诊断恢复。两者都先补齐Qwen3.5模型适配，不能直接换掉旧Qwen3-4B模型名。

### 官方benchmark画像

来源：[用户指定的 Qwen/Qwen3.5-4B 官方模型卡](https://huggingface.co/Qwen/Qwen3.5-4B)。以下为发布方报告的各基准分数，不是本次实测，也不把不同基准的分数当成同一种成功率。

| 能力 | Benchmark | 4B | 同表9B | 判断 |
| --- | --- | ---: | ---: | --- |
| 综合知识 | MMLU-Pro | 79.1 | 82.5 | 已有较强通用基础，首轮不必重新追求知识榜单 |
| 专业推理 | GPQA Diamond | 76.2 | 81.7 | 模型具备推理潜力，不能据此推断Agent可靠性 |
| 常规约束遵循 | IFEval | 89.8 | 91.5 | 简单格式/指令接近饱和，纯格式训练未必划算 |
| 更复杂指令 | IFBench | 59.2 | 64.5 | 复杂约束组合仍有空间 |
| 工具调用 | BFCL-V4 | 50.3 | 66.1 | 4B与9B差15.8分；值得设计工具能力实验，不据此保证可追回差距 |
| 交互业务Agent | TAU2-Bench | 79.9 | 79.1 | 说明Agent能力高度依赖场景；并非4B所有Agent任务都差 |
| 长程规划 | DeepPlanning | 17.6 | 18.0 | 两者都低；仅增模型尺寸不是已证明的解法 |
| 长上下文理解 | LongBench v2 | 50.0 | 55.2 | 长窗口不等于可靠保留和利用信息 |
| 代码生成 | LiveCodeBench v6 | 55.8 | 65.6 | 有基础，优先考虑可执行、可验证的小任务 |
| OCR | OCRBench | 85.0 | 89.2 | 视觉基础可用，但本项目视觉任务训练闭环需另外建设 |
| GUI操作 | OSWorld-Verified | 35.6 | 41.8 | 感知分数与完整GUI任务成功不能混同 |

模型卡注明TAU2 airline场景采用Claude Opus 4.5 system card提出的修正；不能与设置不同的leaderboard直接比较。模型默认thinking，推荐输出预算普通问题32768、复杂竞赛81920 tokens；这些是官方使用建议，不是所有表格行完整的逐项复现实验设置。短预算或关闭thinking的本地结果不能默认复现模型卡分数。

模型是已经post-trained的Qwen3.5-4B，不是Base checkpoint；4B为dense语言模型，配视觉编码器，采用Gated DeltaNet/attention混合结构。官方窗口262144 tokens，是上下文容量，不是跨会话记忆证明，也不是首轮训练预算要求。

### Uni-Agent提供的额外证据

1. 随库 `docs/source/benchmark/inference.md:12` 报告 **ReAct + Qwen3.5-4B，SWE-Bench Verified 45.2，Avg@1、100 turns、64K context**。这是上游/随库评估参考，不是DSH分支复现，也不是训练后结果。
2. `examples/mem_agent/README.md:11–20` 报告 **Qwen3-4B（不是3.5）** 在8K–1M八种长度的HotpotQA boxed-answer token-LCS宏平均 **53.5→58.0，+4.5分**。说明记忆训练路径有历史参考，不承诺Qwen3.5也提升4.5分。
3. `examples/quickstart/training/train_qwen3p5_dense.sh` 默认明确是Qwen3.5-4B + GRPO，但为Megatron/mbridge + colocate_async，默认8节点×8卡、128K response和并发256，无LoRA配置。不能原样作为单卡快速试跑。
4. DSH旧历史训练使用Qwen3-4B；4步update/reload证明旧训练链曾运行，不证明新模型兼容或能力收益。

本地源码位置统一相对 `.Codex/worktrees/harbor-modal-integration/`。

### 训练机会排序

| 优先级 | 训练目标 | 已有资产 | 最小新增工作 | 验收指标 |
| --- | --- | --- | --- | --- |
| 首选A：最快实验闭环 | 任务内记忆与信息保留 | MemAgent、HotpotQA数据适配、分块、reward、训练/评估脚本 | 新模型tokenizer重新分块；改为合适的小拓扑；验证Qwen3.5模型/引擎 | 相同上下文预算下答案质量；不同长度分桶；成功任务token/时延 |
| 首选B：最贴DSH目标 | 工具选择、参数、动态ID、执行与清理 | DshAgent、verifier、trace/receipt、GRPO与严格group准入 | Qwen3.5专用启动/reload适配；冻结runtime；编写未泄漏答案的任务变体 | 实际任务成功且正确清理率；错误调用/越权/误拒绝率 |
| 第二批 | 诊断与有界恢复 | diagnostic-recovery、transfer-composition、真实事件projector | 从smoke中移除直接给出的修复代码；增加真实故障和正常control | 最终恢复成功率、无效重试数、是否破坏正常任务 |
| 第二批 | 小范围代码修复 | ReAct/Mini-SWE/Claude Code、SWE任务与测试reward | 选小仓库/短测试，固定镜像与任务；降低长任务预算 | 隐藏测试通过率、无回归率、每成功任务成本 |
| 后续 | 跨会话记忆/长期规划 | 多chain记录、MemAgent思路、设计文档 | 持久存储/检索/权限、跨session任务、可信评分 | 新session信息利用、长期任务完成；不只统计压缩率 |
| 后续 | 视觉GUI、自动RSI、OPD | 模型视觉能力、部分框架/verl能力 | 新环境/评分/控制器；OPD教师接口仍明确阻断 | 独立端到端验收；不能据底座支持直接标为可用 |

若只需尽快获得一条新模型学习曲线，优先A。若当前交付目标是DSH专长，优先B。不要在DSH外再包MemAgent执行循环：可以先用独立MemAgent实验验证训练机制，再把有效策略迁入DSH自身context生命周期。

### 新模型适配的实际前置

- 旧DSH启动器 `examples/dsh/train_qwen3_4b_online_rl.sh:184–191` 强制model_type=qwen3及旧4B结构。Qwen3.5使用qwen3_5，不能删除检查后假定兼容。
- 旧DSH parser默认hermes；Qwen3.5专用recipe默认qwen3_coder。必须固定新模型revision、tokenizer/processor、chat template和thinking设置，以一次真实tool call验证。
- verl已有 `verl/models/transformers/qwen3_5.py` 及monkey_patch支持，但packed线性attention、kernel、LoRA覆盖/同步/reload均需在所选版本和GPU验证。
- MemAgent默认4张训练卡+4张rollout卡、separate_async、TP4，且不是LoRA入口。单卡不能只改GPU_IDS；要改训练拓扑。
- 当前AgentFrameworkRolloutAdapter在teacher_client非空时仍抛ValueError，因此OPD不是首轮可直接打开的开关。DSH专用SFT链也未完整交付。
- Context7检索到的浮动main摘要与本仓固定版本存在差异，本分析不把其“所有后端支持/不支持”推断当版本结论。训练参考以本仓固定Qwen3.5实现和实跑为准。

### 建议的最小验证序列

1. **先不更新权重**：固定模型与Harness，用小批任务测试thinking/非thinking、few-shot、parser和工具描述。记录“没有学会”与“工程接口坏了”的不同失败。
2. **只选一个任务族**：例如MemAgent信息保留，或DSH工具生命周期；不要同时引入Harbor、Modal、跨会话记忆和新奖励。
3. **按来源/模板分组切分**：train、validation、sealed test相互独立，避免同一生成模板仅换变量后泄漏。探索样本量只能用于判断方向，不承诺统计显著。
4. **先做rollout校准**：同一prompt采样多条完整合法轨迹，统计有效group比例、reward方差、成功率和token消耗。难度校准仅使用训练/校准集，不看最终test。
5. **有学习信号再做GRPO**：全部同分的group没有任务优势信号；安全且完成的失败可保留，unfinished/证据错误/不安全轨迹仍需拒绝。
6. **短训练与独立reload**：预先固定attempt/group/token/时间预算；先验证有限梯度、可训练张量变化、权重同步与独立加载。几个optimizer step是工程门禁，不是提分保证。
7. **只用validation选checkpoint**：最终比较冻结原模型与选定checkpoint，在相同Harness、解码和token/工具预算下执行sealed test。报告paired差值、置信区间、通用能力回归和每成功任务成本。

## 深度交互

### 低分不等于最容易通过RL提升

GRPO在每个prompt的group内中心化奖励。n≥2且同组全0、全1或同样partial reward时，任务优势为0；有其他正则项也不等于学到了任务成功策略。选择模型偶尔能做对、且可真实验证的任务，比直接挑战最难规划任务更可能产生高效学习信号。

如果模型连合法动作都很少产生，应先用训练集示范/few-shot建立基线；必要时另建verified SFT数据与训练路径。若few-shot已经解决问题，先比较提示方案成本，再决定是否值得做权重内化。

### 先提升可靠性，再谈“通用智能增强”

工具正确选择、参数引用、诊断恢复和记忆保留直接对应当前业务成功率。MMLU/GPQA高分并不保证这些环节可靠；但为了提升它们，也不必重训整个知识底座。结果应写成“某个冻结任务分布上提升”，不能把小实验外推为普遍超过9B或更大模型。

### 把模型变化与Harness变化分开归因

先固定H0比较W0/W1，再固定W0比较H0/H1。改变思考预算、检索提示、工具文档、执行重试次数会影响任务分数，必须与权重训练收益分开报告。当前最经济的目标是降低每个真实成功任务的成本，而不是让训练reward曲线更好看。

## 核查与限制

已通过浏览器读取官方模型卡，并从HTML表格结构逐项核对分数列；对照本仓当前代码、README及两位独立子代理审计。没有执行Qwen3.5推理、训练或benchmark，没有承诺训练时间、GPU显存可行性或提升百分点。
