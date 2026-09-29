# Terminal observability acknowledgment helper

The helper `docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py` composes a CPU Ray actor around the unchanged native `TaskRunnerV1`. Its `self.native_runner` reference remains alive through terminal acknowledgment, including after native `Tracking.finish()` returns. It does not implement training, replay metrics, or alter shared collectors.

After successful native execution it reads the existing Prometheus API and requires exactly one finite value for each native metric: `training_global_step`, `actor_grad_norm`, and `critic_rewards_mean`, all with the exact project and experiment labels. The step must equal the configured absolute target. Missing, duplicate, malformed, non-finite or mismatched vectors fail acknowledgment. Zero gradients remain valid observability data and do not imply effective learning.

The wait is limited to 45 seconds and clipped to the original deadline minus 180 seconds of cleanup reserve. A successful or failed backend receipt is written once to the run's `observability-ack.json`. Native training failures skip acknowledgment; missing backend acknowledgment raises after preserving the native training artifacts.

Prometheus instant-query timestamps are not independent evidence of the original scrape time. Unique, never-reused experiment names are required to exclude historical series. This helper does not replace comparison against the original training log, W&B history, checkpoints, or Tempo spans.

Cloud CPU validation:

- RED: 15 tests failed because the helper did not yet exist (`red.log`).
- GREEN: 21 tests passed (`green.log`, `green.xml`).
- Coverage: approximately 98% combined lines/branches (`coverage.json`), 84 statements and 22 branches. The Hydra/native GPU bootstrap is excluded and is not claimed as verified.
- Local static Ruff check and format check passed for the helper and test.

The first coverage attempt found no coverage module in the fixed GPU environment. The final coverage run reused an existing cached coverage installation on the CPU host through process-local `PYTHONPATH`; neither shared environment was modified.

No real Ray serialization/export preflight or r11 training was launched within the remaining authorized window. Actor retention has CPU double coverage, not a completed backend integration test. No synthetic observations were written to the shared collector or W&B. Real native acknowledgment, trace correlation and training acceptance remain pending.
