# 先 OPD 再 RL：算法严查、老师打分格式与改动方案（2026-09-19）

状态：待负责人决定。S1 于 04:50 UTC 暂停，停在第 12 步（`runs/pipe-s1/PAUSED`）。

## 0. 更正：S1 的老师打分格式没有问题

04:50 的报告说"学生模板删掉历史思考、老师原生模板保留思考并加 Reasoning effort 行，老师在学生格式下打分"。**这个结论是错的。** 当时渲染两个模板用的是开思考的对话，没有先核对 S1 的实际配置。

实际核实结果：

- **S1 关闭了思考。** `train-command.txt` 中是 `++data.apply_chat_template_kwargs.enable_thinking=False`，由 `train_tb21_lora_smoke.sh` 写死。第 12 步一条真实轨迹里有 25 个 `<think>` 块，全部为空。
- **网关从不重新渲染历史。** 生成的 token 原样追加，新消息单独渲染后接上（`continuous_token.py:195-202`、`241-289`）。所以不存在"删掉历史思考"。
- **老师看到的序列与 Qwen3.8 原生无思考格式逐字一致。** 两者都是 `<|im_start|>user\n…<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\nA1<|im_end|>\n<|im_start|>user\n…`。无思考时 Qwen3.8 模板也不加 Reasoning effort 行。
- **分词器一致。** 两个 `tokenizer.json` 的 vocab、merges 和各处理器完全相同；老师只多 7 个音频/TTS 专用 token（id 248070 起），学生不会生成。同一段 4,618 token 的文本编码逐 id 相同。

由此，之前的算法对照里"S1 蒸馏覆盖思考"也不成立。S1 蒸馏的只是动作 token，即 JSON 里的 analysis、plan 和 commands。第 12 步输出变长 48%，指的是动作文本变长，不是思考变长。

**含义：** VERL S1 是一个更干净的反例。它没有思考、老师在原生格式下打分、token 也对齐，结果仍然 −0.172 [−0.285, −0.060]。"格式不一致"和"思考 KL 导致变长"这两个嫌疑在 VERL 线上都被排除了。

## 1. 算法严查清单

| 项 | 怎么查的 | 结论 |
|---|---|---|
| 分词器 | `tokenizer.json` 逐字段比较，并实际编码同一段文本 | ✅ 一致 |
| 老师输入格式 | 网关拼接方式与 Qwen3.8 原生无思考渲染对比；真实轨迹 | ✅ 逐字一致（见第 0 节） |
| 位置对齐 | `teacher_manager.py`：`prompt_logprobs` 去掉第 0 位，第 i 行 = log p(token i+1 \| ≤ i)。loss 从 `prompt_length−1` 起读，乘 `response_mask`。数据：第 1–12 步每 token k1 均值 0.06–0.11，错一位会到数 nats | ✅ |
| 只在学生 token 上计算 | 环境输出和模板脚手架（空思考块、换行）的 mask 为 0 | ✅ |
| 符号 | 优势 = −k1 = log p_teacher − log p_student | ✅ |
| 截断 | 每 token k1 截断到 ±10（第 1 步最大 18.7，被截），老师 logprob 下限 −10 | ⚠️ 设计选择，不是 bug |
| 组合方式 | L = L_GRPO + 1.0·L_OPD。全对或全错的组 A_rl=0，这些组上只剩 OPD；4 条 0/1 奖励下这类组很常见 | ⚠️ 放大 OPD（H1） |
| 两项量级 | GRPO 优势除以组内标准差，4 条 1 对时为 ±1.5；k1 每 token 均值约 0.1，但尾部到 10 | ⚠️ |
| 多链 | terminus-2 的摘要或回退会把一个会话拆成几条链，只训练最长的一条（`trajectory_selection=longest`）；RL 和 OPD 同样受影响 | ⚠️ 两者共有 |
| **老师在无思考模式下的能力** | **未测。** Tinker 的"老师比原版 +0.167"是开思考测的 | ❓ OPD 在本线有没有意义的前提 |

没有发现实现 bug。剩下的问题在算法层面，不在实现层面。

## 2. 先 OPD 再 RL：从什么改到什么

```mermaid
flowchart LR
  subgraph 现在：联合（S1）
    A0[原版] --> S["60 步，每步<br/>L = L_GRPO + 1.0·L_OPD"] --> A1[结果]
  end
  subgraph 改成：分阶段
    B0[原版] --> PA["阶段 A：N_A 步<br/>TEACHER=1，DISTILL_USE_TASK_REWARDS=False<br/>L = L_OPD"]
    PA -->|"A 的 checkpoint<br/>数据接着往下取"| PB["阶段 B：N_B 步<br/>TEACHER=0<br/>L = L_GRPO"]
    PB --> B1[结果]
  end
```

| 位置 | 现在 | 改成 | 改动量 |
|---|---|---|---|
| 损失代码 | 联合：`use_task_rewards=True`，两项相加 | 阶段 A 用 `use_task_rewards=False`。VERL 已支持：`losses.py` 在该分支把 policy loss 置 0，系数固定 1.0 | 不改代码 |
| 训练脚本 | `DISTILL_USE_TASK_REWARDS` 默认 True，但没有冻结到 `stage-env.sh` | 把 `DISTILL_USE_TASK_REWARDS`、`DISTILL_LOSS_COEF`、`DISTILL_LOSS_MODE` 加进 `40_train.sh` 的冻结清单，每阶段的设置都有记录 | 1 行 |
| 阶段切换 | 一轮跑到底 | 新增 `run_opd_then_rl.sh`：<br/>① 阶段 A 在 `runs/<name>-opd` 跑 N_A 步；<br/>② 阶段 B 在 `runs/<name>-rl`，复制 A 的 `data/`（同一份 parquet，`data.pt` 让取题接着往下），`FROM_STAGE=train RESUME_MODE=resume_path RESUME_FROM_PATH=<A>/global_step_{N_A} TRAIN_STEPS=N_A+N_B TEACHER=0` | 约 40 行脚本 |
| 优化器状态 | 续跑时全部加载 | 待定：`actor_rollout_ref.actor.checkpoint.load_contents=['model','extra']` 可以丢掉 OPD 阶段的 Adam 动量，只保留权重、学习率调度和随机数状态 | 1 个开关 |
| 评测 | 第 12 步快检 | A 结束时做快检，看 OPD 伤了多少；B 结束时做全量 78×4，和只用 RL 配对 | 复用现有脚本 |

预计工作量：脚本加测试约 1 小时。费用与 60 步相同（沙箱约 72 美元）；阶段 A 占两张卡，阶段 B 只占一张。

## 3. 证据与建议

- **纯 OPD 本身就会退步。** Tinker E'（只用 OPD）第 8 步 −0.129，69% 跑满轮数；VERL S1（联合）第 12 步 −0.172。所以阶段 A 大概率交给阶段 B 一个更差的起点，RL 要先把退步追回来。
- **只用 RL 显著提升。** Tinker A' 在 eval-set-v1 全量上 +0.199 [+0.115, +0.282]；SWE +0.304，Terminal-Lego +0.140，都显著；输出长度不变。
- **文献：** 工业界多用分阶段而不是联合（DeepSeek-V4、Nemotron-Cascade 2、GLM-5），但前提是老师同源或先做 warmup、老师确有额外能力，并且多半做成单轮或 pivot（Tinker 文献调研 `opd-rl-literature-review-20260919.md`）。本线这些条件都不满足，而且老师无思考时的能力还没测。
- **Tinker 会话已计划"先 OPD 再 RL"对照：** 复用它第 8 步的纯 OPD checkpoint，再接 24 步 RL，几乎不额外花钱，就能回答"OPD 预热对 RL 有没有帮助"。

**建议：**

1. VERL 现在改跑只用 RL：从原版开始，60 步，同一份数据，`TEACHER=0`。它只占一张卡。
2. 空出来的 GPU1 用来测老师在无思考模式下的能力（Qwen3.8-27B，快检集，约 1 小时、约 10 美元）。这就是 Tinker 待论证清单里的 D1。
3. 如果 Tinker 的"先 OPD 再 RL"胜过只用 RL，并且老师在无思考模式下明显强于原版，再按第 2 节把分阶段搬到 VERL。

## 4. 格式守卫（专门防止格式问题复发）

当前无思考配置不需要修格式。一旦以后开启思考，就需要处理两件事：

- Qwen3.8 原生格式会在系统提示前加 Reasoning effort 行（默认 xhigh）；
- litellm 会剥掉以 `<think>` 开头的内容，可能触发 last-assistant rollback。

为防止格式悄悄偏离，建议在 `TEACHER=1` 启动前加一个预检：用网关真实的拼接代码拼一段多轮对话，再用老师模板和同样的 `apply_chat_template_kwargs` 渲染，逐 token 比较，不一致就拒绝启动。

以后真要开思考时的修法：老师的输入 = 老师原生格式的开头 + 网关第一次提示之后的 token；只有开头不同，logprob 按开头长度差平移即可。

## 5. OPD 打分实测审计（2026-09-19 05:30，S1 第 12 步真实轨迹）

脚本：`examples/harbor_opd_rl/diag_teacher_scoring.py`。证据：`pipe-s1/teacher-scoring-audit/report.json`。

输入是训练当时的真实 token id：每个会话的 `trajectory.npz`，共 29 条轨迹、约 78 万个位置。打分分三路计算：

- 生产配置：vLLM 0.23，前缀缓存 + 4096 分块，`processed_logprobs`，取数用 VERL 的 `extract_prompt_logprobs`；
- 关前缀缓存；
- HF transformers 独立参考：不分块、完整前向。

**实现层：全部通过**

| 项 | 结果 |
|---|---|
| vLLM 返回的 id 与"下一个 token"逐一比对 | 错位 0 |
| 生产 vs HF（loss token 上） | 平均差 0.0074，p99 为 0.115，最大 0.48，属于 bf16 噪声 |
| 关缓存 vs HF / 缓存命中重算 vs 首次 | 同一量级，前缀缓存和分块都不引入偏差 |
| 对照：错一位 | 平均差 0.57，p99 为 6.1，最大 22.9，检测足够灵敏 |
| VERL `no_padding_2_padding` + `kl_penalty_forward` vs 手工推导 | 差 0.0 |
| 复算第 12 步 k1 vs 日志 | 均值 0.0657 vs 0.0611，\|k1\| 0.1348 vs 0.1299。日志用训练时重算的学生概率和实际参与该步的批次，差异合理 |

**算法层：老师信号落在哪里**

| 字段 | token 占比 | 占 k1 总量 |
|---|---|---|
| analysis | 24% | 42.5% |
| plan | 19% | 21.3% |
| keystrokes | 39% | 30.6% |
| task_complete | 0.1% | ≈0 |

- **约 2/3 的信号落在说明文字上。** 贡献最大的是 " the"、" `"、" is"、" and"，OPD 主要在教老师的行文风格，而不是教决策（支持 H3）。
- **句末收尾 `.",` 出现 1,112 次，平均 k1 为 +0.134。** 学生每次收尾都被扣分，文字因此变长，这与 S1 第 12 步输出变长 48% 一致。
- **是否结束任务几乎不受老师影响。** 学生说 true 时老师也几乎同意（p=0.997），说 false 时老师 p(false)=0.96。
- **老师信号和成败不对齐。** 每 token k1 与奖励的相关系数 +0.58，即成功轨迹上被扣得更多；但成功轨迹更短（长度与奖励 −0.57），组内看不出一致方向。
- **第 12 步 8 组里有 6 组全对或全错，RL 信号为 0，这些组只剩 OPD。**

**对"先 OPD 再 RL"的含义：** 阶段 A 按现在的做法，主要会把老师的写作风格和篇幅教给学生，大概率像 Tinker E'（−0.129）和 S1（−0.172）那样退步，阶段 B 的 RL 要先把它追回来。一个针对性的变体是只在 keystrokes 上蒸馏：把老师信号限定在命令 token 上，需要给 VERL 的蒸馏损失加一个掩码。
