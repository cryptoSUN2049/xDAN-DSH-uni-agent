# VERL S1 与 Tinker stage1 的算法对照（2026-09-19）

依据：VERL `train_tb21_lora_smoke.sh`、`runs/pipe-s1/train/train-command.txt`、`verl/trainer/distillation/losses.py`、S1 第 1–12 步指标；Tinker `tinker_cookbook/rl/data_processing.py`、`distillation/train_on_policy.py`、`recipes/distillation/harbor_opd_rl.py`、`examples/harbor-stage1/modal_controller.py`、计划 `stage1-teacher-ablation-v1-20260919-0327.md`。

## 相同

- 数据：阶梯 A（500 道），二值奖励，每组 4 条，LoRA rank 32，学习率 1e-4，Student Qwen3.5-9B、Teacher Qwen3.8-27B。
- 组内相对优势：同一题 4 条轨迹比较，每条轨迹一个优势，赋给它的全部模型 token。
- 蒸馏形式：按 Thinking Machines 的 on-policy distillation 做法，每 token 奖励 = −(log π_student − log π_teacher)（k1 反向 KL），走策略梯度，不直接反传 KL。
- 联合时两项逐 token 相加：VERL 是 RL 损失 + 系数 × 蒸馏损失（同一掩码、同一 token 平均），等价于优势相加；Tinker 直接把 −系数 × KL 加到优势上。
- 每批一次参数更新：VERL `ppo_mini_batch_size = train_batch_size`、`ppo_epochs=1`，S1 第 1–12 步 `pg_clipfrac` 与 `ppo_kl` 全为 0，PPO 裁剪从未触发，实际是普通策略梯度；Tinker `importance_sampling` 本就不裁剪。
- token 加权：VERL 的 token-mean 按整批 token 总数归一，与 Tinker 的求和只差每步一个常数，Adam 基本吸收。
- 全对或全错的组都保留（只剩蒸馏信号）。

## 影响结论的差异

| | VERL S1 | Tinker |
|---|---|---|
| 优势是否除组内标准差 | 除（`norm_adv_by_std_in_grpo` 默认 true）：4 条 1 对时 +1.5 / −0.5，S1 日志 ±1.5 印证 | 不除：+0.75 / −0.25 |
| 结果 | 同样系数 1.0，RL 相对蒸馏强约 1.7–2 倍 | — |
| 蒸馏覆盖 | 全部回复 token 含思考，系数 1.0；每 token 值截断 ±10（第 1 步最大 18.7，截断生效） | B'：`</think>` 之后，系数 1.0；F'：含思考，系数 0.1；不截断 |
| Teacher 打分格式 | 对网关拼出的 token 序列直接打分；与 Qwen3.8 原生格式是否一致、历史思考是否保留：**未核实** | 查出格式不一致是嫌疑，修渲染器（`qwen3_5_preserve_thinking`）后重跑 |
| 对照组 | 只有联合一种，无只用 RL 的对照 | A' 只 RL、B' 联合、E' 只 OPD、F' 联合含思考 |

## 次要差异

- 异步：VERL colocate_async，S1 每步 10%–41% 轨迹由上一步策略生成，无异策略修正（旧对数概率用当前权重重算，比值恒为 1）；Tinker 同步。
- 采样与训练对数概率不一致：Tinker 用采样对数概率做重要性比值；VERL 不修正，实测 KL 0.0002–0.002。
- 优化器：VERL AdamW β2 0.999、权重衰减 0.01、梯度裁剪 1.0、前 3 步预热；Tinker Adam β2 0.95、无预热，cookbook 未显式设权重衰减与梯度裁剪。
- LoRA 缩放与作用层：Tinker 服务端未核实，名义学习率相同不代表实际步长相同。
- 每步规模与环境：VERL 8 题 × 4、60 步、terminus-2 JSON、50 轮、上下文 36,864、时限 1800 秒；Tinker 16 题 × 4、32 步、原生工具调用、32 轮、上下文 65,536、按任务声明时限。
- 失败处理：VERL 一组有效少于 2 条整组丢弃并补题，超时轨迹目前被丢弃而非记 0（todo H7）；Tinker 评分失败丢整组，超过半批失败中止。

## 含义

两线结论不能直接互证：差异落在决定"蒸馏是否有害"的三个旋钮上（RL/蒸馏相对权重、是否蒸馏思考、Teacher 打分格式）。VERL 线要回答"OPD 在这里帮不帮忙"，需要一组只改 `TEACHER=0` 的对照；要复现 Tinker 结论，则先对齐 `norm_adv_by_std_in_grpo=False`、同步模式、蒸馏跳过思考（VERL k1 暂无此选项）。
