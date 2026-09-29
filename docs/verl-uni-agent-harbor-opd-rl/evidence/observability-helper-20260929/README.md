# Terminal observability acknowledgment helper

The helper `docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py` composes a CPU Ray actor around the unchanged native `TaskRunnerV1`. It retains both `self.native_runner` and the native job-scoped `self.monitor_hub` through terminal acknowledgment, including after native `Tracking.finish()` returns. It does not implement training, replay metrics, or alter shared collectors.

After successful native execution it reads the existing Prometheus API and requires exactly one finite value for each native metric: `training_global_step`, `actor_grad_norm`, and `critic_rewards_mean`, all with the exact project and experiment labels. The step must equal the configured absolute target. Missing, duplicate, malformed, non-finite or mismatched vectors fail acknowledgment. Zero gradients remain valid observability data and do not imply effective learning.

The wait is limited to 45 seconds and clipped to the explicitly extended absolute deadline (1790709401) minus 180 seconds of cleanup reserve. A successful or failed backend receipt is written once to the run's `observability-ack.json`. Native training failures skip acknowledgment; missing backend acknowledgment raises after preserving the native training artifacts.

Prometheus instant-query timestamps are not independent evidence of the original scrape time. Unique, never-reused experiment names are required to exclude historical series. This helper does not replace comparison against the original training log, W&B history, checkpoints, or Tempo spans.

Cloud CPU validation:

- RED: 15 tests failed because the helper did not yet exist (`red.log`).
- GREEN: 21 tests passed (`green.log`, `green.xml`).
- Coverage: approximately 98% combined lines/branches (`coverage.json`), 84 statements and 22 branches. The Hydra/native GPU bootstrap is excluded and is not claimed as verified.
- Local static Ruff check and format check passed for the helper and test.

The first coverage attempt found no coverage module in the fixed GPU environment. The final coverage run reused an existing cached coverage installation on the CPU host through process-local `PYTHONPATH`; neither shared environment was modified.

The original validation above preceded the user's explicit six-hour extension. Extended-deadline unit validation again passed 21 tests (`extended.*`).

After authorization, real CPU-only Ray integration was attempted using native RLInsightLogger and a distinct synthetic-preflight identity. Attempt 1 failed before actor creation because the Ray UNIX socket path exceeded its length limit. Attempt 2 serialized the actual wrapper successfully but failed real Prometheus acknowledgment: native finish dropped the last hub handle. Both failures are retained, not counted as passes.

The fix holds the native job-scoped hub before starting the native runner, with the same trainer.rl_insight configuration. Revised cloud CPU tests passed 21 tests with 95.50% combined coverage (`hub-retention.*`), including explicit hub lifetime/order checks. The existing CPU cached coverage package was reused; no shared environment was changed. Attempt 3 uses a fresh synthetic identity ending `-v3`; its backend result is recorded separately. Synthetic metrics and spans are never training acceptance, and no synthetic W&B run was created.

Attempt 3 **passed** at 2026-09-29 13:28:14 UTC (`status.json`, `native-probe-v3.log`). The exact helper SHA256 was `f383a7f775de9504718308b970e2bfe181de6594894ffde654c26a973101f469`. The actual Prometheus response contains the three exact project/experiment-labelled values 4, 0.125 and 0.75 (`observability-ack.json`). Tempo returned trace `b7208a94764dcf48d6be0e713a43eeed` with the synthetic preflight root span (`tempo-trace.json`). This proves CPU Ray serialization and native monitor transport after native finish; it does not prove r11 training or W&B delivery. Ray was shut down by this probe; `cleanup.json` independently checks the owned processes and empty GPU compute-app list. Original failed attempt statuses are retained as `attempt1-status.json` and `attempt2-status.json`.
