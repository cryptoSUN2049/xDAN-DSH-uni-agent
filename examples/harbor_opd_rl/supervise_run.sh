#!/usr/bin/env bash
# Relaunch a detached training driver until its run is complete, so a crash (OOM, sandbox
# outage, killed process) never leaves a run half done while nobody watches. Runs on the
# GPU host, itself launched with launch-detached.sh.
#
#   bash examples/harbor_opd_rl/supervise_run.sh <driver-log> '<done check>' '<launch command>' [max-relaunches]
#   e.g. supervise_run.sh runs/pipe-s2-driver.log \
#          '[ -f runs/pipe-s2-rl/train/PASSED ] && grep -q global_step_60 runs/pipe-s2-rl/train/final-checkpoint.txt' \
#          'NAME=pipe-s2 ... bash examples/harbor_opd_rl/run_opd_then_rl.sh'
#
# Loop: wait until <driver-log> records "[detached] exit=" (launch-detached.sh writes it);
# stop when <done check> succeeds; otherwise relaunch <launch command> with the same log path,
# after moving the old driver log and every unfinished train/train.log under RUN_DIRS aside
# (40_train.sh overwrites train.log). The launch command must be safe to rerun: finished
# stages are skipped and training resumes from its newest checkpoint (run_opd_then_rl.sh and
# run_opd_round.sh with RESUME_MODE=auto are). Before relaunching it waits until no VERL trainer
# is alive (an eval on the other GPU also runs verl.trainer.main_ppo, and run_opd_round.sh
# refuses to start beside one). It never kills anything and gives up after max-relaunches (3),
# so a deterministic failure does not loop.
set -uo pipefail
DLOG="${1:?driver log}"; DONE_CHECK="${2:?done check}"; LAUNCH="${3:?launch command}"; MAX="${4:-3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${LAUNCHER:-${SCRIPT_DIR}/launch-detached.sh}"   # tests substitute a stub
RUN_DIRS="${RUN_DIRS:-}"          # space-separated run roots whose unfinished train.log to keep
POLL="${POLL:-120}"
TRAINER_WAIT_POLLS="${TRAINER_WAIT_POLLS:-120}"   # x POLL seconds
log() { printf '[supervise %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

relaunches=0
while true; do
  until grep -q '^\[detached\] exit=' "${DLOG}" 2>/dev/null; do sleep "${POLL}"; done
  if bash -c "${DONE_CHECK}"; then log "run complete ($(grep '^\[detached\] exit=' "${DLOG}" | tail -1))"; exit 0; fi
  if [[ ${relaunches} -ge ${MAX} ]]; then log "not complete after ${MAX} relaunches; giving up"; exit 1; fi
  log "driver exited before completion: $(grep '^\[detached\] exit=' "${DLOG}" | tail -1)"
  for _ in $(seq 1 "${TRAINER_WAIT_POLLS}"); do
    pgrep -f 'verl\.trainer\.main_ppo' >/dev/null || break
    sleep "${POLL}"
  done
  if pgrep -f 'verl\.trainer\.main_ppo' >/dev/null; then log "a VERL trainer is still alive; not relaunching"; exit 1; fi
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  for run in ${RUN_DIRS}; do
    if [[ -f "${run}/train/train.log" && ! -f "${run}/train/PASSED" ]]; then
      mv "${run}/train/train.log" "${run}/train/train.attempt-${ts}.log"
    fi
  done
  mv "${DLOG}" "${DLOG%.log}.attempt-${ts}.log"
  relaunches=$((relaunches + 1))
  log "relaunch ${relaunches}/${MAX}; previous driver log kept as ${DLOG%.log}.attempt-${ts}.log"
  bash "${LAUNCHER}" "${DLOG}" "${LAUNCH}"
  sleep "${POLL}"
done
