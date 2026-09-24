#!/usr/bin/env bash
set -euo pipefail
ROOT=/workspace/verl-uni-agent-harbor-opd-rl
export RUN="$ROOT/runs/opd-live-acceptance-20260924"
export OPD_LIVE_AUDIT_DIR="$RUN/capture"
export OPD_LIVE_AUDIT_MAX_CALLS=64
export STEPS=1 WARMUP=0 RESPONSE=1024
mkdir -p "$RUN"
set +e
bash "$ROOT/runs/opd-live-audit-code/train-audit.sh"   trainer.val_before_train=False trainer.test_freq=-1 trainer.save_freq=1   trainer.experiment_name=live-opd-acceptance-20260924   ++ray_kwargs.ray_init.runtime_env.env_vars.PYTHONPATH="$ROOT/runs/opd-live-audit-code:$ROOT/src/uni-agent:$ROOT/src/uni-agent/verl"   ++ray_kwargs.ray_init.runtime_env.env_vars.OPD_LIVE_AUDIT_DIR="$OPD_LIVE_AUDIT_DIR"   ++ray_kwargs.ray_init.runtime_env.env_vars.OPD_LIVE_AUDIT_MAX_CALLS='"64"' > "$RUN/train.log" 2>&1
result=$?
printf '%s\n' "$result" > "$RUN/exit-code.txt"
exit "$result"
