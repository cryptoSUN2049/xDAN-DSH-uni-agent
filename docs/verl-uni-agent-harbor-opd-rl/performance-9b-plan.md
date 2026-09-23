# Performance-9B：9B 全能模型与训练体系专项计划

状态：`performance-9b` 分支，方案阶段；旧评测任务仍在远端，未强行清理或抢占 GPU。

## 1. 目标

训练一个在代码/软件工程、数学与科学推理、工具调用、中文/英文指令、安全和长上下文上都可测量提升的 9B 模型，并把训练过程建设成可复现的 VERL + Uni-Agent + Harbor/Modal + W&B/verl-insight 生产闭环。

本项目不把 Terminal-Bench 单项高分当成“全能”。每个候选必须同时报告能力、行为预算、失败分母、成本、许可证和 benchmark 污染状态。

## 2. 起点与对照

主研究线采用 **官方 8–9B base → cold-start SFT → verifier RL → 可选 OPD/整合**。推荐先评估 `Qwen/Qwen3-8B-Base`，固定 `Qwen/Qwen3-8B` instruct/reasoning 作为产品对照；当前 Qwen3.5-9B 线的 OPD12/RL60 不作为新主线起点，因为已有能力回退和行为膨胀，继续训练无法分离历史影响。

同时保留两臂小矩阵：

| 臂 | 起点 | 目的 |
|---|---|---|
| A | 官方 8–9B base | 测量 SFT、RL 和 OPD 的真实增益，最可解释 |
| B | 官方 instruct/reasoning checkpoint | 测量产品起点的 targeted SFT/RL，避免把先验浪费掉 |

两臂共享数据 manifest、验证集、预算和评测配置；只改变起点。每臂先跑 2–4 步 control-only，不能凭经验直接选择一条长跑。

27B teacher 的职责分三层：先独立能力门；再在相同 student prefix、tool feedback、thinking/action mask 上做 on-policy scoring；最后才进入 OPD。teacher 不进入 9B 的优化器，也不能用 teacher 分数冒充 9B 能力。

## 3. 数据版本 `performance-9b-data-v1`

这里需要区分三个概念：**mid-training 数据、SFT 数据和 RL rollout**。它们都可能由 teacher 或模型合成，但消费方式、loss mask、质量门和能力目标不同，不能因为“合成”就放进同一个 JSONL。

MiMo 专题报告（[本地报告](/Users/gumpm5/Documents/Code/xDAN-Project-Hope-2026/1-Growth/edge-navigation/MiMo-V2.6专题报告.html)）给出的关键启发是：Agent 导向的 mid-training 用代码、通用、视觉、研究轨迹和高质量通用数据，目的是把模型塑造成可探索、可长程工作的状态；任务合成、scaffold、rollout、verifier/rubric 和 sample mixer 是一个数据生产系统。报告还记录前代 V2-Flash 在特定 mid-training 阶段加入约 5% 合成推理数据，但这不是 MiMo V2.5/V2.6 的统一配方，不能直接复制成我们的比例。

因此本项目增加一条 **SYN-MT** 生产线：用 27B/强模型生成候选任务、工具轨迹、反例和难度变体；用可执行 verifier、结构解析、teacher agreement、去重/污染审计和人工抽样过滤；最终以少量高质量样本进入 mid-training 或 SFT。模型自生成的困难任务进入 RL task pool 时，必须另存 scaffold、reward contract、novelty 和 hack-resistance 证据。

### 3.0 数据消费分层

| 层 | 目标 | 样本形式 | 主要门槛 |
|---|---|---|---|
| `MT-v1` | 增加工具、长程、代码/研究状态的可探索概率 | 多轮轨迹、工具反馈、失败恢复、长上下文压缩 | 状态完整、tool schema 可解析、长度/语言平衡 |
| `SFT-v1` | 建立稳定格式、指令、推理、代码和安全行为 | 监督消息、成功/反例对、thinking/no-thinking pair | teacher/verifier 质量、去重、许可证、污染 |
| `OPD-v1` | 在 student 自己的状态上吸收 teacher token 信号 | student prefix + teacher logprob + masks | tokenizer/template 对齐、同一 policy version、teacher 可靠 |
| `RL-v1` | 通过环境反馈改进可验证能力 | task/scaffold/rollout/verifier/reward | pass-rate frontier、mixed group、infra 清洁 |

### 3.1 四层资产

1. **SFT clean**：经过许可证、schema、去重、可执行/可验证和质量审计的高质量样本。
2. **OPD teacher**：student 自身 rollout，由 27B 以不可变版本打分；保留 student sampling logprob、training-policy logprob、teacher logprob、mask 和 policy version。
3. **Online RL**：Harbor/Modal 可复现任务，按 source × difficulty × family 分层；目标是每组出现有效 reward 差异。
4. **Sealed eval**：永不进入训练和调参；冻结 task/repo/patch family、版本和 verifier digest。

### 3.2 SFT v1 初始配比

按有效 token 重平衡，而非简单按行数：

| 能力 | 目标比例 |
|---|---:|
| 软件工程、代码、Agent | 30% |
| 通用推理、数学、科学 | 20% |
| 工具调用、规划、多轮 | 15% |
| 一般指令、写作、对话 | 10% |
| 中文、多语种 | 10% |
| 安全、拒答、注入、事实校准 | 10% |
| 长上下文、压缩、记忆 | 5% |

第一版控制在 10–30 万条高质量样本（约 1–3B 有效 tokens，需按真实长度复核）。大规模 prompt library 只用来做 teacher 生成、课程和覆盖率分析，不直接当 SFT 行数。

### 3.3 数据治理字段

每条记录最少包含：`sample_id`、`source`、`source_revision`、`license`、`domain`、`language`、`difficulty`、`teacher`、`verifier`、`quality_score`、`contamination_status`、`prompt_hash`、`semantic_cluster`、`token_budget`、`thinking_mode`、`split`。

切分按 task/repo/patch family 分组，执行 exact、7-gram、MinHash、embedding/semantic near-duplicate 和 AST/patch fingerprint 审计。现有 lexical audit 通过不等于没有语义污染。

### 3.4 RL 题池

先用 base/instruct pilot 估算 `pass@4`，将主 RL 池放在 0.2–0.8 成功率区间；Terminal-Lego/SWE 的 easy 全对、hard 全错题进入 eval 或低权重池。初始分布建议 easy 20%、medium 60%、hard 20%，再依据实际 pass-rate 调整。每个 GRPO group 记录 expected/valid/admitted/effective 四个分母，目标 effective group fraction ≥50%，infra failure 和 task failure 分开。

## 4. G0–G6 执行门

| 阶段 | 内容 | 必须通过 |
|---|---|---|
| G0 | manifest、许可证、污染、split、GPU/Modal/W&B preflight | 无身份冲突、额度和资源可用 |
| G1 | 2–4 步 SFT smoke + fixed validation + reload | loss/梯度有限、checkpoint 可恢复、报告对账 |
| G2 | 10–30k 高质量 cold-start SFT | 多能力维度不回退，token/行为预算稳定 |
| G3 | 4–8 步纯 RLVR pilot | effective group、失败分类和自动止损生效 |
| G4 | 数学/代码/Agent 分池交替 RL | 每池有独立验证和成本/有效更新报告 |
| G5 | 27B OPD、rejection sampling/DPO、安全回归 | teacher 合同、mask、paired ablation 完整 |
| G6 | 独立 reload、sealed benchmark、全 checkpoint matrix | base/SFT/RL/OPD 可比较，结果完整可复核 |

## 5. 9B + 27B OPD 真实验证顺序

在当前 2×96GiB RTX PRO 6000 节点上：

1. 清点 GPU0 旧评测进程并完成交接，记录 UUID/PID，不强杀。
2. GPU1 做 27B teacher 单题短上下文 logprob probe。
3. 两卡并行做 9B student + 27B teacher 的 1 step、2 prompts、2 rollouts smoke。
4. 运行 4–8 步 OPD pilot，固定 8–16 个任务，检查 teacher/student token 对齐、distillation loss、梯度、显存峰值和成本。
5. 做 checkpoint save → 新进程 reload → fixed validation。
6. 通过后跑 20 步有界 OPD；另起同配置纯 RL 对照；最后才考虑 OPD→RL 长跑。

历史 pipe-r4 证明 teacher `gpu_memory_utilization=0.85` 会 OOM；默认从 0.70、4096 batched tokens、最多 4 sequences 探针开始，不能直接提高吞吐。若是 48GiB RTX 6000，则只把纯 RL作为正式路线，27B OPD 先不放行。

## 6. 评测矩阵

每个保留 checkpoint 都记录：TB2.1、SWE-bench Verified、固定 dev、数学/科学子集、工具调用/多语言/安全行为集。所有版本使用相同 harness、上下文、temperature、top-p、turn/token/time budget 和 verifier。报告必须包含任务级 paired diff、CI、完整性、超时、tokens、turns、infra failure、成本和污染状态。

主参考改为 [2026-reference-set.md](2026-reference-set.md)。外部基线包括 [Ornith-1.5 官方说明](https://ornith.ai/ornith_1_5.html) 和 [Ornith-1.5-9B model card](https://huggingface.co/ornith-ai/Ornith-1.5-9B)；其自生成任务/scaffold/rollout 闭环和 frontier difficulty 值得借鉴，但其 harness、上下文和多次平均口径不同，不能直接横比。2025 年论文不参与本分支的路线、超参数或放行决策。

## 7. Infra 专项交付

- P0：W&B `val-core/*`/`val-aux/*`、failure、staleness、turn、budget 接入标准报告。
- P1：控制器按 step 输出 `CONTINUE/PAUSE/ROLLBACK`，保存 `stop_reason.json`，PAUSED run 不自动重启。
- P2：Uni-Agent/VERL/Harbor 统一 step/group/sample/policy/checkpoint identity，短组和 infra failure 不静默进入训练。
- P3：复用现有 `uni_agent/rl_insight` facade/adapter，补训练 timeline、verifier、budget、checkpoint sync；W&B 面板按能力、学习信号、行为、系统、成本分组。
- P4：数据 manifest、semantic contamination、pass-rate probe、benchmark matrix 和静态 HTML 报告。

## 8. 近期交付顺序

1. 合并本研究笔记和本计划，确认 `performance-9b-data-v1` schema。
2. 实现 P0 报告字段与离线 S2 回放。
3. 完成 G0 资源清场和 27B 单题 probe。
4. 完成 9B+27B 1-step/4-step OPD smoke 与 reload。
5. 再执行高质量 SFT smoke，随后才进入有限规模正式训练。

任何阶段未通过都保留证据并停在该阶段，不用扩大训练规模掩盖基础设施或数据问题。
