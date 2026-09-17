pipe-r3 train: wandb https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/pg4xsj19 (state=finished)
| 指标                      | pipe-r3 train |
|-------------------------|---------------|
| reward/mean             | 0.419 |
| 有组内方差的组占比               | 0.55 (11/20 组) |
| 非零梯度的 step              | [1, 2, 3, 4, 5, 6] / 6 步 |
| actor/grad_norm 每步      | [0.00934, 0.02185, 0.01648, 0.01721, 0.02625, 0.02966] |
| critic/score/mean 每步    | [0.212, 0.577, 0.071, 0.504, 0.532, 0.678] |
| response_length/mean 每步 | [17537, 7055, 19547, 12187, 10302, 4894] |
| timing_s/gen 每步         | [707, 387, 1354, 124, 235, 595] |
| 轨迹终止                    | completed 43 / error:AgentTimeoutError 2 / error:RuntimeError 1 / max_turns 62 / parse_error 13 / unknown 1 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |

pipe-r3 resume: wandb https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/zlimfmcf (state=finished)
| 指标                      | pipe-r3 resume |
|-------------------------|----------------|
| reward/mean             | 0.419 |
| 有组内方差的组占比               | 0.2 (2/10 组) |
| 非零梯度的 step              | [7] / 1 步 |
| actor/grad_norm 每步      | [0.01514] |
| critic/score/mean 每步    | [0.451] |
| response_length/mean 每步 | [11414] |
| timing_s/gen 每步         | [801] |
| 轨迹终止                    | completed 7 / max_turns 28 / parse_error 6 / unknown 1 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |

