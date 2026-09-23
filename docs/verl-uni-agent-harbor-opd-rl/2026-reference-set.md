# Performance-9B：2026 主参考文献集

更新时间：2026-09-23。主方案只采用 2026 年公开论文、技术报告和官方材料作为设计依据；2025 年材料不参与路线选择、超参数或能力结论，仅在必要时作为历史背景标注。

## A. Mid-training 与合成环境

1. **SYNTHAGENT: Mock Worlds, Real Skills: Building Small Agentic Language Models with Synthetic Tasks, Simulated Environments, and Rubric-Based Rewards** — ACL 2026 Long Paper 570。<https://aclanthology.org/2026.acl-long.570.pdf>
   - strong teacher 生成任务、工具生态和 underspecified instruction；mock user/tool 提供稳定环境；从执行工作流提取 subgoals，构建 execution-grounded rubric。
   - 对本项目的可用结论：合成任务必须同时生成环境、用户信息、工具响应和 verifier，不能只生成 prompt/answer；稳定环境是 advantage 可解释性的前提。

2. **ExpRL: Exploratory RL for LLM Mid-Training** — arXiv:2606.17024。<https://arxiv.org/abs/2606.17024>
   - 将参考答案作为 reward scaffold 而非直接 imitation target，用 on-policy trace 和 process/outcome reward 做 mid-training。
   - 对本项目的可用结论：mid-training 可先训练分解、验证、自纠错等 primitive，再进入稀疏 RL；SFT 与 sparse GRPO 应做对照。

3. **MiMo V2.6 专题报告** — 本地研究报告。<file:///Users/gumpm5/Documents/Code/xDAN-Project-Hope-2026/1-Growth/edge-navigation/MiMo-V2.6专题报告.html>
   - 作为 2026 生产蓝图参考：Agent mid-training、任务合成、scaffold、rollout、verifier/rubric、sample mixer、MixRL 与 MOPD2。
   - 报告中未公开的规模/配方不当作事实；只迁移机制并做小规模消融。

## B. OPD、RLVR 与 credit assignment

4. **On-policy Distillation with Verifiable Reward (OPDVR)** — arXiv:2608.24696。<https://arxiv.org/abs/2608.24696>
   - 将 sampled-token OPD 的隐式 reward 按轨迹正确性门控，使正确轨迹获得非负、错误轨迹获得非正的蒸馏信号，并兼容 GRPO。
   - 对本项目的可用结论：优先做标准 OPD、RLVR、OPDVR 三臂小消融，不能把 teacher token loss 无条件加到 reward 上。

5. **AgentOPSD: Recursive Self-Distillation for Agentic Reinforcement Learning** — arXiv:2608.05987。<https://arxiv.org/html/2608.05987v1>
   - 把 token-level teacher/student gap 聚合到 turn-level，并以历史依赖的递归 belief 做 credit assignment。
   - 对本项目的可用结论：Agent 任务应以 tool/environment turn 为 credit 单位；不能只按 token 平均 advantage。

6. **RetireOPD: Self-Retiring On-Policy Distillation for Agentic Reinforcement Learning** — arXiv:2609.20784。<https://arxiv.org/abs/2609.20784>
   - teacher 先用环境 reward 优化；student 联合 RL+OPD，并在 teacher 差距不再缩小且达到目标成功率后自适应退出 teacher。
   - 对本项目的可用结论：OPD 不是固定全程开；controller 应记录 teacher/student discrepancy、teacher success fraction 和 retirement decision。

7. **RISE: Recursive Improvement via Self-Extrapolating Policy Distillation** — arXiv:2609.05295。<https://arxiv.org/abs/2609.05295>
   - 从 RLVR trajectory 的 checkpoint/anchor 位移构造合成 teacher，递归结合 outcome reward 与 token target。
   - 对本项目的可用结论：可作为 27B teacher 成本过高时的后续自蒸馏候选；不进入第一轮 9B+27B OPD 验证。

## C. 其他 2026 方向

8. **Chain-based Distillation for Effective Initialization of Variable-Sized Small Language Models** — arXiv:2605.07783。<https://arxiv.org/html/2605.07783v1>
   - 通过逐级 anchor 与 bridge distillation 缩小 teacher/student 规模和词表差异。
   - 对本项目的可用结论：如果未来需要不同 9B 架构或低资源初始化，再评估；当前 Qwen 9B/27B tokenizer 不一致时不得直接套用。

## 采用规则

- **主方案**：优先采用 2026 论文的机制，先做可证伪小消融，再扩大。
- **不采用**：2025 年论文的指标、训练配方和结论不作为 `performance-9b` 放行依据。
- **外部榜单**：Ornith-1.5、其他模型卡只作为 baseline 和方法线索；不同 harness/context/重复次数的分数不横向合并。
- **证据分层**：论文实验、官方模型卡、本地复现、工程推导分开记录；任何“未公开”不得补写成已知。
