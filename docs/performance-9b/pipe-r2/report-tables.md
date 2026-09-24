pipe-r2 train: wandb https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/dzlqgapu (state=finished)
| 指标                      | pipe-r2 train |
|-------------------------|---------------|
| reward/mean             | 0.471 |
| 有组内方差的组占比               | 0.55 (11/20 组) |
| 非零梯度的 step              | [1, 2, 3, 4, 5, 6] / 6 步 |
| actor/grad_norm 每步      | [0.05273, 0.00653, 0.00909, 0.01471, 0.02405, 0.01245] |
| critic/score/mean 每步    | [0.595, 0.265, 0.186, 0.572, 0.604, 0.653] |
| response_length/mean 每步 | [2600, 19802, 19644, 10702, 13004, 11513] |
| timing_s/gen 每步         | [525, 509, 1229, 395, 127, 557] |
| 轨迹终止                    | completed 34 / error:AgentTimeoutError 2 / max_turns 72 / parse_error 14 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |

pipe-r2 resume: wandb https://wandb.ai/xdan-ai/xDAN-Verl-Uni-agent-Harbor-rl-opd/runs/eg1ix7eo (state=finished)
| 指标                      | pipe-r2 resume |
|-------------------------|----------------|
| reward/mean             | 0.333 |
| 有组内方差的组占比               | 0.2 (2/10 组) |
| 非零梯度的 step              | [7] / 1 步 |
| actor/grad_norm 每步      | [0.00891] |
| critic/score/mean 每步    | [0.283] |
| response_length/mean 每步 | [10207] |
| timing_s/gen 每步         | [883] |
| 轨迹终止                    | completed 9 / max_turns 22 / parse_error 10 / unknown 1 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |

