pipe-r4 train: wandb https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/m848n94f (state=finished)
| 指标                      | pipe-r4 train |
|-------------------------|---------------|
| reward/mean             | 0.804 |
| 有组内方差的组占比               | 0.5 (17/34 组) |
| 非零梯度的 step              | [1, 2, 3, 4, 5, 6] / 6 步 |
| actor/grad_norm 每步      | [0.10352, 0.10156, 0.08936, 0.10791, 0.11523, 0.09131] |
| critic/score/mean 每步    | [0.916, 0.767, 0.566, 0.6, 0.872, 0.915] |
| response_length/mean 每步 | [24692, 20869, 21035, 25802, 14649, 14351] |
| timing_s/gen 每步         | [969, 1001, 519, 745, 253, 295] |
| 轨迹终止                    | completed 113 / error:AgentTimeoutError 7 / error:RewardFileNotFoundError 2 / max_turns 113 / parse_error 1 / unknown 2 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |

pipe-r4 resume: wandb https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/6mm8e04j (state=finished)
| 指标                      | pipe-r4 resume |
|-------------------------|----------------|
| reward/mean             | 0.991 |
| 有组内方差的组占比               | 0.214 (3/14 组) |
| 非零梯度的 step              | [7] / 1 步 |
| actor/grad_norm 每步      | [0.15332] |
| critic/score/mean 每步    | [1] |
| response_length/mean 每步 | [3628] |
| timing_s/gen 每步         | [481] |
| 轨迹终止                    | completed 76 / max_turns 2 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |

