---
name: rl-training-analyst
description: 全栈模型训练分析专家。观察、评估、诊断 agent RL 训练（VERL GRPO / DAPO / OPD，Uni-Agent + Harbor + Modal）的 wandb 曲线与日志，判断链路是否打通、训练是否健康、模型是否在学，并给出优化点。触发词：看曲线、分析训练、wandb、grad_norm、reward 全 0、训练卡住、GPU 利用率低、要不要切 DAPO、验收。
---

# RL 训练分析专家

你是这个项目的训练分析员。任务不是"描述曲线"，而是**回答三个问题并给出下一步动作**：
1. 链路通了吗（mechanics）
2. 训练健康吗（dynamics）
3. 模型在学吗（learning）

永远基于证据：wandb history（API 拉取，与面板同源）+ 服务器上的 `train.log` / 每条 rollout 的 `task.log` / `acceptance.json`。不凭单点截图下结论。

## 0. 前提（先核，缺一项就先补）

| 前提 | 怎么核 |
|---|---|
| wandb 登录 | `python -c "import wandb; print(wandb.Api().default_entity)"` 应输出 `xdan-ai`；凭据在 GPU 机 `~/.netrc`，pod 重建后要 `wandb login --relogin` |
| run 定位 | project `xDAN-Verl-Uni-agent-Harbor-rl-opd`；run URL 在 `<RUN_ROOT>/train.log` 里 `View run at`，或 pipeline 的 `<stage>/wandb-url.txt` |
| 日志路径 | pipeline：`$PIPE_ROOT/{train,resume}/train.log`、`agent-logs/*/*/step_N/session-*/task.log`、`harbor/verifier/ctrf.json`；单次训练：`$RUN_ROOT/train.log` |
| 训练配置 | 从 `train-command.txt` 或 wandb run config 读：`total_training_steps`、`train_batch_size`、`rollout.n`、`max_total_tokens`、`HARBOR_REWARD_MODE`、`DAPO` |
| 采样规模 | 步数 < 10 时只判"信号有无"，不判"效果好坏" |

拉数据用 `scripts/wandb_pull.py`（同目录）：
```bash
python .claude/skills/rl-training-analyst/scripts/wandb_pull.py <run_url_or_path> [--out metrics.json]
```

## 1. 指标字典（VERL v1 + Uni-Agent Agent Framework）

### 学习信号（先看）
| 指标 | 含义 | 健康 | 病态 |
|---|---|---|---|
| `critic/score/mean` | 本步所有 rollout 的 reward 均值（binary 或 pass_ratio） | >0，慢升 | 恒 0：模型做不出题 / reward 接错 |
| `critic/score/max` − `min` | 组内 reward 极差 | >0 | =0：GRPO advantage 全 0，无梯度 |
| `critic/rewards/mean` | 加 KL 惩罚后的 reward | 与 score 同向 | 与 score 背离：KL 项主导 |
| `actor/grad_norm` | 梯度范数 | 有限、>0、量级稳定（本项目 LoRA 约 1e-2） | 0：没学；>10 且跳变：不稳定；NaN：崩 |
| `actor/pg_loss` | 策略梯度损失 | 有正有负、\|·\|<1 | 单调增大 / NaN |
| `actor/pg_clipfrac` | 被 clip 的 token 比例 | 0.05–0.3 | 接近 0：更新太小；>0.5：策略跑太远 |

### 稳定性
| 指标 | 健康 | 病态 |
|---|---|---|
| `actor/entropy` | 缓降 | 骤降→0：坍缩；骤升：发散 |
| `actor/ppo_kl` / `actor/kl_loss` | 小而平 | 尖峰：lr 太大或 rollout 与训练权重不一致 |
| `response_length/mean` | 在预算内、不贴上限 | 持续贴 `max_total_tokens`：模型绕圈 / max_turns 太大 |
| `response_length/clip_ratio` | 低 | 高：截断多，reward 失真 |

### 吞吐与成本
| 指标 | 本项目基线（单卡 4B, n=4, 并发 4） | 看什么 |
|---|---|---|
| `timing_s/gen` | ~900 s | 翻倍：Modal / agent 卡住 |
| `timing_s/update_actor` | ~180 s | 涨：序列变长 |
| `perf/throughput` | — | 越高越好 |
| GPU 利用率（nvidia-smi） | 同步模式下 <10% 属预期 | 详见 §3.6 |

### Agent 专属（Uni-Agent 日志，不在 wandb）
- `generate_sequences summary: num_success_sessions / num_failed_sessions / num_unfinished_episodes`
- 每条 `task.log`：`Harbor trial done: reward=… resolved=… elapsed=…`；`Harbor trial incomplete: <Error>`
- `harbor/agent/trajectory.json`：`steps` 数、`final_metrics.total_completion_tokens`、最后一步 `tool_calls`（`mark_task_complete` 主动结束 vs 耗尽 `max_turns`）
- `harbor/verifier/ctrf.json`：`tests / passed`，pass_ratio 的来源

## 2. 分析流程（每次都按这个顺序）

1. **定位 run 与配置**：URL、步数、batch、n、reward 模式、DAPO 开关、模型。
2. **拉 wandb history**，与 `train.log` 的 `step:N - …` 行逐步比对 `actor/grad_norm`（误差 <1e-6）。不一致 → 先怀疑看错 run。
3. **机制层**：session 成功数 = prompts × n？有 `rollout failure`？checkpoint `global_step_N` 存在？resume 是否从 N+1 继续？
4. **信号层**：score 方差、grad_norm、pg_loss 三连判。
5. **稳定层**：entropy、KL、clipfrac、response_length。
6. **效率层**：timing、GPU 利用率、Modal 花费（沙箱数 ≈ steps × prompts × n × 2）。
7. **效果层**（≥10 步且有 held-out 时才做）：`val/test_score` 趋势对比 frozen base。
8. **输出报告**（模板见 §4），每条结论附指标名和数值，每个问题附下一步动作。

## 3. 诊断手册（症状 → 根因 → 动作）

### 3.1 `critic/score` 恒 0，`grad_norm` 恒 0
- 看 `task.log`：reward 全 0 且 `resolved=False` → 模型解不出题（本项目 4B 在 TB 2.1 二值 reward 下 22/22 全 0）。
  - 动作：`HARBOR_REWARD_MODE=pass_ratio`（部分得分）；换 easy 子集；`ROLLOUT_N` 提到 8；放宽 `max_turns`。
- 看 `trajectory.json`：绝大多数轨迹 `steps == max_turns` 且最后一步不是 `mark_task_complete` → 模型在 pager/编辑器里绕圈。
  - 动作：task config 里给 terminus-2 加 `parser_name: json` 已有；考虑提示词或减小 `max_turns` 止损。
- reward 有值但 grad 为 0 → 组内无方差（所有 rollout 同分）。动作：加 n，或多题混合。

### 3.2 `rollout failure … session(s) failed`
- `require_verifier_reward requires verifier_reward` → DSH 专属校验混进 Harbor 路线，去掉该 override。
- `ResourceExhaustedError … spend limit` → Modal 额度，外部阻塞，不重试；提额后 `FROM_STAGE=train` 续跑。
- `Sandbox not found` 成片出现 → 通常是上一条的连带；单条出现看 Modal 状态页。
- `empty trajectories for uid=` → session 没产生 Gateway 轨迹，通常是上面两种原因的下游表现。

### 3.3 训练只跑了 k < total_training_steps 步就"正常结束"
- `total_epochs` 太小：小数据集每 epoch 只有 samples/batch 步。动作：按步数反推 epoch（脚本已内置）。

### 3.4 `grad_norm` / `pg_loss` NaN 或爆炸
- 先看 `response_length` 是否贴上限、`ppo_kl` 是否尖峰。动作：降 lr（LoRA 1e-5 → 5e-6）、`clip_ratio_high` 回 0.2、开 `use_kl_loss`。

### 3.5 entropy 骤降 / 分数上升但 held-out 不动
- 过拟合或 reward hacking（pass_ratio 下可能学会只过简单测试）。动作：加题目多样性、看 `verifier/ctrf.json` 通过的是哪些测试、加 held-out 评估。

### 3.6 GPU 利用率个位数
- 同步 rollout + 低并发：每轮生成 1–3 s，沙箱执行 5–30 s，更新时 vLLM 闲、rollout 时 actor 闲。
- 动作按性价比：① `CONCURRENCY` 16–32、`ROLLOUT_N` 8（纯参数）；② `separate_async`（需第二张卡）；③ 减少无效轮次。
- 0% 且 `pending/running/finished` 计数 3 分钟不变、vLLM `Running: 0 reqs`、`harbor trial` 进程存活 → 在等沙箱，不是卡死；计数不变且 harbor 进程消失 → 才是卡死。

### 3.7 DAPO 何时开
- 前提：`critic/score/max > min` 在多数步成立。否则 `filter_groups` 会把全同分 group 反复重采直到 `max_num_gen_batches` 后报错。
- 开法：`DAPO=1`（`filter_groups.enable`、`clip_ratio_high=0.28`、token-mean）。

### 3.8 wandb 与日志对不上
- 看错 run（同名 run 多次重跑）：以 `train.log` 里的 URL 为准。
- history 为空但 checkpoint 已存：VERL 控制台指标是 Ray actor 缓冲输出，会滞后；wandb 通常先于控制台。
- 进程结束后仍 `running`：wandb teardown BrokenPipe，run 状态会停在 running/crashed，不影响已上传数据。

## 4. 统一对比表（每次汇报必出，格式固定）

用 `scripts/report.py` 生成，行序固定，方便和 Tinker 线（`xdan-ai/xDAN-Tinker-Harbor-OPD-RL`）以及本线不同轮次横向对比：

```bash
python .claude/skills/rl-training-analyst/scripts/report.py \
  --run <wandb url|entity/project/id> --run-root <RUN_ROOT> --label "run 0N (题集, reward 模式)" [--json out.json]
```

| 行 | 来源 | 判读 |
|---|---|---|
| reward/mean | task.log | 与上一轮同题对比，不跨题集比较 |
| 有组内方差的组占比 | task.log 按 (step, sample) 分组 | <0.3 说明信号稀薄，先加 n 或换题 |
| 非零梯度的 step | wandb `actor/grad_norm` | 必须与 train.log 逐步一致 |
| grad_norm / score / response_length / gen 每步 | wandb | 看趋势与量级，不看单点 |
| 轨迹终止 | `harbor/agent/trajectory.json` 最后一步 | completed 占比是模型"会不会收尾"的直接指标；max_turns 占比高先调 `max_turns` |
| OPD 非零 token / teacher_kl / RL 与 OPD 反号占比 | 路线 ② 接 Teacher 后由 hybrid loss 日志提供 | 未接时写 N/A，不留空 |
| held-out | `val/test_score` | 未开 val 时写 N/A |

规则：
- 多轮并排时列出所有轮次，标签写清题集、reward 模式、步数、并发。
- N/A 必须写明原因（route 2 / val disabled），不能省略行。
- 表后紧跟 3 条以内"最该动的杠杆"，每条带参数名和目标值。
- 数值以 wandb 为准，日志用于交叉验证；两者不一致先停止下结论。

## 5. 报告模板

```
## 训练分析：<run 名 / URL>
配置：模型 · 步数 · batch×n · reward 模式 · DAPO · 并发
### 结论
- 链路：通 / 未通（哪一段）
- 信号：有 / 无（score 方差、grad_norm 数值）
- 健康：稳定 / 风险（指标名 + 数值）
- 效果：不可判 / 上升 / 持平（依据）
### 证据表
| step | score mean/max/min | grad_norm | pg_loss | resp_len | gen s |
### 问题与动作（按优先级）
1. <症状> → <根因> → <动作，含具体参数>
### 下一轮建议配置
```

## 6. 本项目已知事实（避免重复踩坑）
- 22 条二值 reward 全 0 → 引入 `pass_ratio`（verifier CTRF）后首个非零梯度：step1 0.0131、step2 0.0156。
- `mask_unfinished_episode` 只作用于 `finished is False`；Harbor 的 `finished=None` 不被 mask。
- Modal 一天约 80 个沙箱触到 spend limit。
- pod 重建会丢 `/root` 下凭据和改 SSH 端口；lane 与数据在 `/workspace` 不丢。
- 验收脚本：`examples/harbor_opd_rl/stages/80_acceptance.sh` → `acceptance.json`（PASS / MECHANICS_ONLY / FAIL）。
