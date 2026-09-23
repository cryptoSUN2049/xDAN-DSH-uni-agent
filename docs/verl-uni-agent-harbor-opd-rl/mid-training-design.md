# Performance-9B Mid-training 专项设计

状态：方案阶段，服务 `performance-9b`；尚未启动 mid-training。本文与 [训练体系 v2](training-system-v2-design.md) 和 [唯一入口](architecture.html) 配套。

## 1. 为什么需要 mid-training

纯 base 预训练模型拥有知识，但不一定拥有稳定的工具调用、长程状态维护、代码仓库操作、研究工作流、失败恢复和可验证输出格式。直接将它送入高成本 Agent RL，会遇到两类问题：

1. 模型几乎采不到有用轨迹，RL 的有效组比例低，梯度稀疏。
2. 模型能完成任务但行为格式、上下文利用和工具边界不稳定，reward 容易优化到 harness 漏洞。

mid-training 的目标是把模型放到“可探索状态”：不追求把所有任务答案背下来，而是增加正确行为、工具反馈、长程恢复和可验证推理在学生分布中的概率质量。

## 2. 与预训练、SFT、OPD、RL 的边界

| 阶段 | 主要输入 | 主要目标 | 典型 loss/反馈 |
|---|---|---|---|
| Continued pretraining | 高质量领域文本、代码、文档、轨迹文本 | 补知识、语言/代码分布和领域先验 | causal LM loss，通常不依赖任务 reward |
| Mid-training | Agent 轨迹、工具反馈、长上下文、任务 scaffold、失败恢复、合成课程 | 形成可探索行为与稳定状态转移 | causal LM + action/tool mask + 结构/格式辅助 loss |
| SFT | 精选成功示范、反例、安全和指令对 | 建立可控行为、格式和对话策略 | response/action token CE，样本级权重 |
| OPD | student 自己的 rollout + teacher token probability | 在真实 student 状态迁移专家能力 | sampled-token PG / top-k / KL，必须保留 mask 与 policy identity |
| RLVR | 在线环境、verifier、reward | 在可验证任务上改变策略 | GRPO/PPO/DAPO 等，依赖 mixed group 和可靠 reward |

同一份“合成轨迹”可以被不同阶段消费，但必须生成不同 manifest，不能仅复制 JSONL 后改目录名。

## 3. 数据生产方案 `performance-9b-mt-v1`

### 3.1 四类合成数据

1. **能力 scaffolds**：由 27B/强模型为任务生成计划、工具 schema、检查点和完成条件；学生训练时必须看到真实工具反馈，不能只学计划文本。
2. **成功轨迹**：强模型在隔离环境中完成任务，保存完整消息、工具输入输出、状态快照、verifier 结果和 token mask。
3. **失败/反例轨迹**：保留错误工具调用、超时、错误恢复和 reward-hacking 尝试，标记失败原因；可用于拒答、纠错、偏好和 critic 数据，不直接当正向 CE 标签。
4. **难度变体**：对同一任务改变初态、预算、依赖、干扰信息和工具可见性；变体必须通过 semantic contamination 与任务族分组审计。

### 3.2 数据字段

每个 episode 必须含：`episode_id`、`parent_task_id`、`source_revision`、`generator_model`、`generator_policy_version`、`scaffold_version`、`tool_schema_hash`、`environment_image_digest`、`trajectory`、`state_snapshots`、`verifier_version`、`reward_breakdown`、`failure_taxonomy`、`difficulty`、`novelty_cluster`、`license`、`split`、`token_budget`、`thinking_mode`。

必须区分：模型错误、任务不可解、工具错误、沙箱启动失败、verifier 失败、超时和预算耗尽。否则合成数据会把基础设施噪声变成错误监督。

### 3.3 质量门

- **结构门**：消息角色、tool call、参数 schema、终止状态、tokenize 和 mask 可重放。
- **执行门**：成功样本在干净环境重跑；代码通过测试；研究/数学样本有可验证答案或 rubric。
- **教师门**：至少一个独立 grader 或规则 verifier；teacher agreement 只作为证据之一，不能替代执行验证。
- **反作弊门**：移除 git 历史、禁用网络泄漏、限制文件/进程权限，记录 harness 版本。
- **去重门**：prompt/task/repo exact hash、MinHash/embedding、AST/patch fingerprint；同源变体只能进入同一 split group。
- **分布门**：按领域、语言、长度、turn、工具类型、难度和失败类型采样；长轨迹不能因 token 数量自动压倒短轨迹。

## 4. 训练算法与目标

### 4.1 推荐第一版：masked causal LM + curriculum

首轮不引入复杂的新 loss，使用 VERL/HF 的 causal LM 作为基线，按 token mask 区分：

- assistant reasoning/action token：正常 loss；
- tool output、环境日志和外部 observation：默认不计 loss；
- system/policy metadata：不计 loss；
- 关键格式 token（tool name、arguments、termination）：可增加有限权重；
- 失败轨迹：只进入纠错/偏好子集，不与成功轨迹等权。

按课程顺序消费：格式与短工具调用 → 多轮工具反馈 → 代码/仓库任务 → 长程研究和失败恢复。每个阶段保持 10–20% 通用回放，防止灾难性遗忘。

### 4.2 可选算法消融

| 实验 | 改动 | 需要回答的问题 |
|---|---|---|
| MT-CE | masked causal LM | 仅行为轨迹是否足够？ |
| MT-CE+format | 对工具/终止 token 加权 | 格式稳定性是否改善而不损害能力？ |
| MT-CE+replay | 加入通用/数学/中文 replay | 能否降低领域遗忘？ |
| MT-DPO | 成功/失败同任务偏好对 | 偏好损失是否比失败 CE 更稳？ |
| MT→RLVR | mid-training 后进入 verifier RL | 有效 group 与 RL 收益是否提高？ |

不建议第一版同时改变模型架构、optimizer、precision、loss 和数据分布；否则无法归因。

### 4.3 长上下文与优化器

先固定 32K 或当前可稳定验证的长度，再逐步扩到 64K/128K；每次扩长单独报告吞吐、有效 token、位置分布和能力回归。MiMo 专题提到 mid-training 以 256K 为主并延展到 1M，同时涉及 optimizer/精度转换；这属于大规模系统路线，不能直接当作 9B 两卡默认配置。

第一版保持 AdamW/现有 LoRA 或全参数训练合同不变。若引入 Muon、QAT、FP8/MXFP 等优化器或精度变化，必须建立独立 ablation，记录 optimizer state、resume、梯度 scaler 和 checkpoint 兼容性。

## 5. 9B 两轨执行矩阵

| 轨道 | 初始化 | mid-training | 后续 |
|---|---|---|---|
| A 研究主线 | Qwen 8–9B base | `MT-CE`，10–30k 高质量 episodes | SFT → RLVR → OPD 对照 |
| B 产品对照 | 官方 instruct/reasoning | `MT-CE` 小剂量 targeted，保留原行为 | RLVR；必要时 DPO |
| C 教师 | 27B 独立能力门 | 不与 9B 混训 | 生成 scaffold、评分 student prefix |

每轨保留 base、MT、SFT、RL、OPD checkpoint，并在 fixed dev 上逐阶段评测。只有当 MT 提高工具格式、有效 group 或长程恢复，同时通用能力没有显著回退，才扩大数据量。

## 6. 与 MiMo 方法的对应关系

MiMo 专题报告把生产线拆成：Agent 导向 mid-training、任务/环境/评分生产、MixRL 形成领域专家、MOPD 整合互补能力、独立评测与受控反馈。对本项目可落地的部分是：

- 将任务合成、scaffold、rollout、verifier 和 sample mixer 做成版本化数据工厂；
- 在 RL 前先用 mid-training 提高学生进入有效轨迹的概率；
- 只有已有独立变强且互补的专家时才做 OPD/MOPD；
- 保留失败和反例，报告失败 taxonomy 与 reward fidelity；
- 将长任务、teacher prefix 和完整 student rollout 分开做成本/收益消融。

MiMo 报告披露的合成比例、规模、优化器或长上下文设置不能直接视为 9B 的配方；我们只能把机制转成受控实验。

## 7. 验收与 Infra

mid-training 每 step/epoch 必须写入：`data_version`、source/domain/length 分布、有效 loss tokens、mask 比例、tool-call parse rate、trajectory replay success、failure taxonomy、validation、GPU throughput、成本和 checkpoint identity。

止损条件：格式解析率下降、通用/数学/中文 fixed dev 回退、长轨迹占比超预算、重复率上升、合成成功率与独立 verifier 不一致、有效 RL group 没有改善。所有停止写入 `stop_reason.json`，并保留可重放样本。

## 8. 最小可行实验

1. 选 5k–10k 个跨领域高质量 episodes，生成 `performance-9b-mt-v1` manifest。
2. base 与 instruct 两轨各做 1–2k step/等 token smoke，固定 8–16 个 dev 任务。
3. 对比 MT-CE、MT-CE+replay、无 mid-training 三组；不接 RL，先确认行为与通用能力。
4. 选择一组进入 4–8 步 RLVR，比较 effective group fraction、timeout、token budget 和 independent pass rate。
5. 只有完成该消融，才进入 9B+27B OPD；否则 teacher 只是在放大错误数据分布。
