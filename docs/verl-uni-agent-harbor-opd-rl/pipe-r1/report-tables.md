|-------------------------|------------------------------------------------|
| reward/mean             | 0.24 |
| 有组内方差的组占比               | 0.5 (2/4 组) |
| 非零梯度的 step              | [1, 3] / 3 步 |
| actor/grad_norm 每步      | [0.02002, 0, 0.01514] |
| critic/score/mean 每步    | [0.333, 0.167, 0.219] |
| response_length/mean 每步 | [11752, 24629, 23842] |
| timing_s/gen 每步         | [1099, 842, 463] |
| 轨迹终止                    | completed 5 / error:AgentTimeoutError 1 / max_turns 16 / parse_error 2 / unknown 8 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |

|-------------------------|-------------------------|
| reward/mean             | 0.233 |
| 有组内方差的组占比               | 0.5 (1/2 组) |
| 非零梯度的 step              | [] / 1 步 |
| actor/grad_norm 每步      | [0] |
| critic/score/mean 每步    | [0.292] |
| response_length/mean 每步 | [14631] |
| timing_s/gen 每步         | [1002] |
| 轨迹终止                    | completed 1 / max_turns 9 / unknown 6 |
| OPD 非零 token            | N/A (route 2) |
| teacher_kl              | N/A (route 2) |
| RL 与 OPD 反号占比           | N/A (route 2) |
| held-out                | N/A (val disabled in smoke) |
