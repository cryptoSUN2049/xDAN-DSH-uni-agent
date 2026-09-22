# 领域 RL 专家培养与 MOPD 接入方案

> 日期：2026-09-22  
> 工作树：`verl-mopd` / `worktree-verl-mopd`  
> 范围：为 9B、27B 的同源领域专家设计可验证的 RL 培养路线，再接入 MOPD。本文是研究和工程方案，不代表已经获得 GPU 预算，也不代表下列领域教师已经训练完成。

## 结论先行

MOPD 的教师不是“找几款榜单更高的模型”，而是从共同起点分化出的、在不同任务分布上有可重复优势的冻结策略。最稳妥的形式是：

```text
共同 SFT 起点 S0
      ├── 领域 A 的可验证 RL ── 冻结教师 T_A
      ├── 领域 B 的可验证 RL ── 冻结教师 T_B
      └── 学生仍从 S0 初始化
                         ↓
       学生自己 rollout → 按任务路由教师 → MOPD
```

MiMo MOPD 论文公开的受控实验使用 Math、Instruction Following、SWE 三个领域；MiMo-V2-Flash 工业实验列出 Math、Code、IF、SWE、Tool Use 五类教师。教师均由领域专项 RL 得到，学生和教师从同一 SFT 起点分化；论文同时报告，用能力更强但分布差异更大的 Qwen3-235B 替换同源数学教师会造成蒸馏退化。[MOPD §3.1、§4.3、§4.4.2](https://arxiv.org/html/2606.30406v1)

对我们的首轮实施，建议使用 **SWE/代码修复 + Terminal/工具操作** 两个领域。它们复用当前 Harbor、SWE 和 Terminal-Lego 资产，能用执行结果产生奖励；数学、指令遵循、网络安全、视觉编码和业务模拟器作为后续扩展。

## 一、教师的定义与合同

### 1. 教师资格

教师必须同时满足四个条件：

1. 从固定的共同起点 `S0` 训练或经过完整审计的兼容 checkpoint；
2. 在定义好的领域任务和环境中，相对 `S0` 有可重复的能力增量；
3. 对学生的实际前缀能够返回 token log-prob 或等价的 Top-K 概率信号；
4. 在独立任务上通过能力、遗忘、长度、工具行为和成本检查。

“模型更大”“公开榜单更高”“生成示范看起来更好”都不能替代教师资格评测。

### 2. 每个教师的不可变记录

```yaml
teacher_id: t_swe_9b_r1
student_origin: <S0 checkpoint hash>
model_revision: <immutable model hash>
tokenizer_hash: <tokenizer.json hash>
chat_template_hash: <template hash>
tool_schema_hash: <tool/parser hash>
domain: swe
train_source: <dataset manifest>
reward_contract: <verifier and reward version>
train_split: <explicit split>
heldout_split: <explicit split>
rl_algorithm: <GRPO/PPO/etc.>
training_budget: <steps, tokens, GPU hours>
qualification_report: <paired results and uncertainty>
logprob_interface: <prefill/top-k contract>
```

当前 VERL 实现对精确 token 目标要求学生和教师的 `tokenizer.json` 一致，并会检查实际模型身份；同一家族不自动保证模板、added tokens、EOS 和工具消息兼容。跨 tokenizer 只能先走示范数据/SFT 路线，不能直接冒充 token 级 MOPD。

## 二、教师来源：什么可以直接用，什么必须自训

| 来源 | 能否直接当 MOPD 教师 | 适用方式 |
|---|---|---|
| 同一 `S0` 分支出的领域 RL checkpoint | 可以，完成实际加载和资格评测后 | 首选 |
| 同架构、同 tokenizer 的公开领域 RL 模型 | 可能可以，必须验证前缀评分和模板 | 候选教师或对照 |
| 只提供文本生成 API 的强模型 | 通常不可以 | 生成 SFT 示范、任务或评审参考 |
| 不同 tokenizer/模板的公开专家 | 不直接可以 | 文本/轨迹蒸馏，另开跨 tokenizer 实验 |
| 我们已有的连续训练 step | 不自动可以 | 先证明它们是不同领域专家，而不是同一专家的不同时间点 |

可复用的公开资产包括：

- `MiMo-V2.6-Distill-Qwen-9B`：官方模型卡将其定义为基于 Qwen3.5-9B 的 SFT checkpoint，训练数据覆盖 Code、Cyber、General、Visual，可作为 9B 的候选共同起点或基线；它不是领域 RL 教师。[官方模型卡](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B)
- `DeepSWE-Preview`：基于 Qwen3-32B、只使用 RL 训练的 coding agent，使用 R2E-Gym 与执行测试奖励；可以作为 coding 能力对照或数据来源，但模型规模、模板和工具合同不等于当前 9B/27B MOPD 可直接使用。[官方模型卡](https://huggingface.co/agentica-org/DeepSWE-Preview)
- `R2E-Gym`：提供可执行 SWE 环境、unit tests、任务和训练说明，可用于构建代码专家；官方仓库明确区分训练 split 和 SWE-bench 评测。[官方仓库](https://github.com/R2E-Gym/R2E-Gym)
- `SWE-smith`：提供 52K task instances、250+ 环境和 SWE-agent 训练资产，可用作扩展代码修复数据；需要按我们的工具、版本和污染审计重新制备。[官方仓库](https://github.com/SWE-bench/SWE-smith)

## 三、领域专家地图

下表中的“RL 目标”是训练目标；不是简单的 benchmark 名称。每个教师都要绑定环境、验证器和独立 held-out 集。

| 优先级 | 领域教师 | RL 目标 | 环境/数据起点 | 主要验证器 | MOPD 价值 | 当前建议 |
|---|---|---|---|---|---|---|
| P0 | `T_code` | 找到正确修改、保留回归行为、完成提交 | Harbor SWE、R2E-Gym、SWE-smith、SWE-rebench | 隐藏 unit/regression tests、patch 合法性 | 迁移定位、编辑、测试和收尾策略 | 首个专家 |
| P0 | `T_terminal` | 在多轮 shell/tool 交互后达到正确环境终态 | Terminal-Lego、Harbor terminal 任务 | 文件、进程、配置、输出和终态检查 | 整合工具规划、恢复、命令选择 | 与 `T_code` 配对 |
| P1 | `T_math` | 在可验证题上提高正确率，并控制无效长思考 | BigMath/ORZ/公开可验证数学题 | 解析答案、程序验证、单元测试 | 复用论文路径，信号干净 | 先在 9B 小规模验证 |
| P1 | `T_if` | 满足精确格式、约束、内容和多轮修改要求 | IFBench/IFEval 及自建约束 | 逐条 verification functions | 补足通用遵循，不依赖行业知识 | 与工具领域分开评估 |
| P1 | `T_cyber` | 在隔离靶场完成安全分析和修复，不越权 | 受控 CTF/漏洞修复 sandbox | exploit/patch tests、权限和安全策略 | 与 coding 互补但风险高 | 先只做离线验证 |
| P1 | `T_visual_code` | 根据截图/UI 状态完成代码修改和测试 | 视觉编码任务、浏览器 sandbox | screenshot diff、DOM/测试、构建结果 | 验证多模态/代码融合 | 需要视觉输入链路 |
| P2 | `T_sql` | 查询、更新或生成报表，同时满足业务约束 | 版本化数据库和 schema | exact result、constraint、query safety | 可与 coding/terminal 形成工具专家组 | 可先做文本+DB环境 |
| P2 | `T_retail` | 按订单、库存、退款规则完成售后操作 | τ-bench retail 或自建模拟器 | DB state、金额、政策和确认流程 | 第一个跨行业示范 | 必须补政策违规奖励 |
| P2 | `T_airline` | 在票价、航班和乘客约束下完成改签/取消 | τ-bench airline 或自建模拟器 | DB state、价格、动作顺序 | 测试长链工具决策 | 先小规模 |
| P2 | `T_telecom` | 诊断套餐/服务问题并完成配置或工单 | τ-bench telecom 或自建模拟器 | DB state、通信政策、工单终态 | 跨行业路由示例 | 需要增加流程合规判分 |
| P3 | `T_finance` | 对账、异常定位、可追溯报表生成 | 版本化账务数据库 | 金额守恒、匹配率、证据链、权限 | 业务价值高 | 无可靠审计环境前不训练 |
| P3 | `T_manufacturing` | 在物料、设备、交期约束下排程 | 离散事件排程仿真器 | 硬约束、交期、成本/吞吐 | 与工具决策互补 | 需先建设 simulator |

### 关键判断

- **纯 coding 可以做，而且是当前最现实的首个示范。** 但仅训练一个 SWE 专家还不能证明多教师整合；至少需要它与 Terminal 专家在逐题表现上有互补差异。
- **跨行业也可以做，但行业名称不是训练定义。** 必须把业务政策、可用工具、状态变化和成功判据做成可执行环境。
- 业务知识问答没有可执行验证器时，先做 SFT/偏好数据，不直接做 RL 教师。

## 四、每个领域的 RL 目标设计

### A. SWE / 代码修复

**状态**：仓库 revision、问题描述、工具 schema、历史命令/补丁/测试输出。  
**动作**：搜索、查看、编辑、运行测试、提交。  
**主奖励**：隐藏测试通过且 patch 合法。  
**辅助诊断**：回归测试数、修改文件数、工具轮数、超时、token、最终 patch 可读性。

不要直接奖励“代码行数少”或“思考更短”；这些先记录，用于分析长度膨胀是否来自错误循环。DeepSWE 的公开方案采用稀疏 ORM：测试通过为 1，失败或超时为 0；这是可复用的基线，但我们的时间限制和测试集合必须独立登记。[DeepSWE 模型卡](https://huggingface.co/agentica-org/DeepSWE-Preview)

### B. Terminal / Tool Use

**状态**：初始文件系统、进程/服务、环境变量、任务约束和工具返回。  
**动作**：shell、文件编辑、查询、服务控制、finish。  
**主奖励**：目标终态完全匹配。  
**必须补的约束**：禁止破坏性越权、禁止修改 grader、禁止依赖随机外部状态、必须正常收尾。

单纯终态奖励可能允许“绕路成功”。因此保留轨迹级成功奖励，同时单独做动作审计和越权惩罚；不能把所有行为规则都粗暴加进同一个长度惩罚。

### C. 数学 / 可验证推理

**状态**：题目和标准化回答格式。  
**动作**：生成推理和答案。  
**主奖励**：答案解析正确或程序验证通过。  
**诊断**：平均尝试数、无效思考、答案格式、长度分布。

MiMo MOPD 论文在 Math 专家上使用可验证答案 RL；其公开超参数只应作为参考，不应直接宣称适合我们的 9B/27B。[MOPD 附录 A](https://arxiv.org/html/2606.30406v1#A1)

### D. 指令遵循

IFBench 提供约束模板和 verification functions，并另有 IF-RLVR 训练约束；这类任务适合做可验证奖励，而不是用主观“回答好不好”替代验证器。[IFBench 官方仓库](https://github.com/allenai/IFBench)

**奖励**应按约束逐条判定：格式、关键词、长度、语言、结构和多轮修改。保留每条约束的明细，避免只有一个总分导致无法定位退化。

### E. 跨行业工具任务

以 retail 为例，一条训练样本应包含：订单/用户初始状态、政策、可用工具、目标和隐藏验证。奖励可拆为：

```text
业务终态正确 × 金额/数据正确 × 政策合规 × 安全行为
```

实际实现应把每项记录为独立诊断，再定义是否允许进入主 RL reward。τ-bench 的官方说明强调每个 domain 有 policy、tools、tasks；其默认奖励偏向数据库终态与沟通结果，不能自动覆盖所有政策违规，因此需要我们的额外审计。[τ-bench 官方仓库](https://github.com/sierra-research/tau2-bench)

## 五、数据分层与教师训练流程

### 数据桶

每个领域至少分为四桶：

1. `rl_train`：用于在线采样和参数更新；每轮轨迹消费后丢弃或按不可变 run manifest 保存。
2. `teacher_selection`：选择 checkpoint、调学习率和课程；不能作为最终能力报告。
3. `heldout_eval`：只用于资格评测；不得参与训练、调参或教师选择。
4. `mopd_prompts`：学生 MOPD 采样题，可与训练题来源相近，但必须有单独污染规则和最终测试题。

任务记录至少绑定任务 ID、环境镜像 digest、仓库/数据库 revision、工具版本、领域、split、leakage group 和 verifier 版本。公开 benchmark 的 test split 不得直接变成 RL 训练集。

### 单个专家的训练步骤

```text
1. 固定 S0、tokenizer、template、工具和 verifier
2. 审计并冻结领域 rl_train / selection / heldout
3. 做 base smoke：轨迹能生成、环境能重置、奖励可重现
4. 运行小规模 RL：检查全零/全一组奖励、长度、超时和工具错误
5. 扩大训练：每次记录权重、优化器、数据 cursor 和环境版本
6. 在 heldout 上配对评估 S0 与候选教师
7. 评估跨域遗忘、成本和行为约束
8. 导出 HF checkpoint，实测加载和前缀 log-prob
9. 通过资格门后冻结，才进入 MOPD
```

MiMo-V2.6 的公开 9B 模型卡把 Code、Cyber、General、Visual SFT 数据分开报告，可作为共同起点或数据配方参考；它不是这四个领域的 RL 教师。其后续领域 RL checkpoint 的成绩也必须按领域理解，不能当成一个统一模型的成绩。[MiMo-V2.6-Distill-Qwen-9B](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B)

## 六、教师资格门

教师资格采用配对差值和不确定性，不设置未经实验依据的“自动止损分数”。建议至少报告：

| 门 | 通过含义 |
|---|---|
| 加载门 | 新进程实际加载预期权重，hash、tokenizer、template 和工具版本一致 |
| 环境门 | verifier 在固定镜像内可重复，成功/失败样本可回放 |
| 专项能力门 | 教师在独立领域集相对 S0 有稳定、可解释的提升 |
| 互补门 | 不同教师在跨域逐题结果上有差异，而不是同一模型的两个训练 step |
| 行为门 | 超时、越权、死循环、异常长度和错误收尾没有不可接受恶化 |
| 评分门 | 教师能对学生实际前缀返回 token log-prob/Top-K；mask、EOS、工具消息对齐 |
| 遗忘门 | 其他领域没有无法接受的回退，或回退被明确记录为整合代价 |

如果专项能力门不通过，停止把该 checkpoint 叫教师，先修数据、环境或 RL 配方。不要通过提高 MOPD 权重来掩盖教师没有能力增量。

## 七、9B / 27B 的最短验证路线

### 9B 工程优先

```text
候选 S0：现有合格 9B SFT 或 MiMo-V2.6-Distill-Qwen-9B
    ├─ SWE 小规模 RL → T_code_9B
    ├─ Terminal 小规模 RL → T_terminal_9B
    └─ S0 → MOPD 学生 9B
```

先完成一位 `T_code_9B` 的资格训练，再训练 `T_terminal_9B`。不要一开始启动两个教师和一个学生的完整长跑。第一轮工程验收只需要验证：rollout、teacher prefill、一次更新、保存、新进程恢复和下一批更新；能力实验再另设预算。

### 27B 能力验证

如果 9B 证明两位教师确实互补，再从同一个 27B SFT 起点训练对应专家。可比较：

- `27B 专家 → 27B MOPD 学生`；
- `27B 专家 → 9B 学生`；
- `9B 专家 → 9B 学生`。

跨规模路线必须重新验证 tokenizer、added tokens、template、tool parser 和教师前缀评分，不能把 27B 教师直接替换进当前配置。

## 八、MOPD 的教师接入方式

学生生成自己的轨迹，任务携带 `teacher_domain`，按领域路由到冻结教师。教师不重新采样，也不更新参数；它对学生历史做 prefill：

```text
student rollout: (x, y_1, ..., y_T)
teacher prefill: q(y_t | x, y_<t)
student score:   p(y_t | x, y_<t)
loss:            PG / corrected Top-64 reverse / Flash ORM
```

MiMo 论文的 Top-K 目标使用教师 Top-64 候选，并在截断目标中补偿 `-p+q` 项；我们已在 VERL 分支实现独立 recipe，但当前仍没有合格的真实领域教师和 GPU 闭环。[MOPD §3.2](https://arxiv.org/html/2606.30406v1#S3.SS2)

V2.6 报告还公开了 MOPD2/Multi-Prefix 方向：将完整学生 rollout、教师轨迹前缀或 SFT 示范前缀分别用于单轮蒸馏。这扩大了教师来源，但不能把 SFT 示范直接称为 RL 教师；首次验收仍应先做标准同源 teacher-prefill MOPD。

## 九、当前项目的推荐顺序

### P0：coding 闭环

- [ ] 确认 9B 共同起点：现有 S0 与 `MiMo-V2.6-Distill-Qwen-9B` 做加载、模板、工具、短任务对照。
- [ ] 冻结 SWE/Terminal 训练与 held-out manifest；补齐现有 4 train + 2 engineering validation 之外的正式任务。
- [ ] 训练 `T_code_9B`；完成专项资格评测和 HF 实际加载证明。
- [ ] 训练 `T_terminal_9B`；确认跨域表现和互补性。
- [ ] 做 `S0 vs mixed-RL vs MOPD` 对照，报告成功率、长度、工具轮数、成本和不确定性。

### P1：论文近似领域

- [ ] 加入 Math 或 IFBench 其中一个，复用公开 verifier；不要同时加入两套新数据和新 loss。
- [ ] 分别验证 token-level MOPD 与 prefix 复用变体。
- [ ] 记录同源教师与外部强教师的初始 KL 和训练稳定性。

### P2：跨行业示范

- [ ] 从 retail、airline、telecom 中选一个构建 sandbox。
- [ ] 增加全过程政策合规检查，不只使用终态数据库奖励。
- [ ] 做业务教师与代码教师的 MOPD 路由对照。
- [ ] 在独立模拟器版本和未见任务上报告迁移。

## 十、不能从公开资料推出的结论

- MiMo 没有公开每个教师的完整 checkpoint 清单、训练日志、全部任务内容和私有生产超参数；公开论文的领域名称不能被扩写成未披露的模型数量。
- MiMo-V2.5 官方模型卡说明后训练使用 SFT、agentic RL 和 MOPD，并举出 math、safety、complex agentic tool-use 等方向，但没有给出一份可直接下载的完整教师 registry。[MiMo-V2.5-Pro 模型卡](https://huggingface.co/XiaomiMiMo/MiMo-V2.5-Pro)
- MiMo-V2.6-Distill-Qwen-9B 是 SFT 起点，不是领域 RL 专家集合。[官方模型卡](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B)
- 公开 benchmark 分数不能直接预测我们的 Harbor 任务收益；环境、工具、模板、任务版本和 reward 都改变了学习问题。

## 参考资料

1. [MOPD: Multi-Teacher On-Policy Distillation for Capability Integration in LLM Post-Training](https://arxiv.org/html/2606.30406v1)
2. [MiMo-V2.5-Pro 官方模型卡与训练说明](https://huggingface.co/XiaomiMiMo/MiMo-V2.5-Pro)
3. [MiMo-V2.6-Distill-Qwen-9B 官方模型卡](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B)
4. [R2E-Gym 官方仓库](https://github.com/R2E-Gym/R2E-Gym)
5. [SWE-smith 官方仓库](https://github.com/SWE-bench/SWE-smith)
6. [DeepSWE-Preview 官方模型卡](https://huggingface.co/agentica-org/DeepSWE-Preview)
7. [IFBench 官方仓库](https://github.com/allenai/IFBench)
8. [τ-bench 官方仓库](https://github.com/sierra-research/tau2-bench)
9. [MiMo-V2.6 技术报告 PDF](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Flash-RL/blob/main/MiMo_V2_6_technical_report.pdf)
