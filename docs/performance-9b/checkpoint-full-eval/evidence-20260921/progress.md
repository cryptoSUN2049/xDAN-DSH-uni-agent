# Full evaluation progress — 2026-09-21 13:46 UTC

Training completed 60/60. The full evaluation campaign is not complete.

| Version | Coverage | Success rate | Difference vs base | Paired 95% CI |
|---|---|---|---|---|
| Base | 78 × 4 | 64.10% | — | — |
| RL step60 | 78 × 4, attempt2 complete | 46.15% | −17.95 pp | [−25.00, −10.90] pp |
| RL step40 | 78 × 4, attempt1 complete | 47.76% | −16.35 pp | [−24.36, −8.65] pp |
| OPD step12 | 311/312, attempt2 incomplete | withheld pending completion | — | — |
| RL step20 | 311/312, attempt2 incomplete | withheld pending completion | — | — |
| OPD step10 | running GPU0 | — | — | — |
| OPD step11 / RL step59 / S1 step12 | pending | — | — | — |
| RL step58 | corrupted checkpoint, unavailable | — | — | — |

OPD12 missing: tasks-eval/terminal-lego-15k__task_10836, one sample; tmux runtime error.
RL20 missing: tasks-eval/terminal-lego-15k__task_08999, one sample; verifier timeout.
These are infrastructure-incomplete samples. Supplement only these, preserving all existing valid 0/1 scores and original attempts.

Both completed checkpoints are statistically below base under the frozen eval-set-v1 protocol. No claim that step60 is significantly worse than step40 without their direct paired comparison.

Behavior metrics use a separate verdict definition in the existing script; their solve_rate must not replace the primary framework resolved metric. Step60 token median 13,089 vs base 9,807; timeout share 33.3% vs 12.8%. Step40 median 11,324; timeouts 24.4%.

Modal metered $795.03 / billed $848.13 at check; recorded workspace limit $900, not newly queried via API. GPU0 occupied (~54GiB at one snapshot), GPU1 free. Background queue active since 2026-09-20 15:20 UTC. No new resource purchases.
