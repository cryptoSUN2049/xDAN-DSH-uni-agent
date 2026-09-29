# Actual Hydra entry regression proof

The r11 launch failed before Ray initialization because Hydra's default relative `outputs/...` directory was inside frozen source with mode `0555`. The frozen source was intentionally read-only; changing its permissions would weaken the runtime contract.

This cloud CPU probe executed the exact frozen `mimo_observability.py` (SHA256 `f383a7f775de9504718308b970e2bfe181de6594894ffde654c26a973101f469`) from that same source working directory. It supplied `hydra.run.dir` under an independent private directory and `trainer.use_v1=false` so the real helper would reject execution before calling native Ray training.

The expected guard `ValueError` was observed at helper entry line 163, after Hydra successfully created its log and `.hydra/{config,hydra,overrides}.yaml`. No permission error occurred, no Ray instance started, the probe process exited, and the GPU compute-app list was empty. This proves actual Hydra bootstrap and output placement, not training success. The detached timeout process had already been reaped, so its numerical exit status was not captured; the report explicitly leaves `observed_exit_code` null rather than inventing one. `stdout.log` preserves the expected real traceback.

The launcher fix must set `hydra.run.dir=<private launch parent>/hydra`; its separate command-construction regression tests verify this override is supplied for both normal native and observed entrypoints. This probe used the unchanged frozen helper and did not exercise a not-yet-frozen launcher revision.
