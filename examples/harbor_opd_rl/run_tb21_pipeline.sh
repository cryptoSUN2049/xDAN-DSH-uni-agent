#!/usr/bin/env bash
# One-command driver for the Terminal-Bench 2.1 + Harbor (terminus-2, Modal) +
# VERL LoRA GRPO pipeline on a single GPU host. Each stage is its own
# reproducible script under stages/ and can be run by hand with the same env;
# this driver only orders them, skips stages that already PASSED, and supports
# FROM_STAGE=<name> (restart there) and SKIP_STAGES="a b".
#
#   PIPE_ROOT=/workspace/verl-uni-agent-harbor-opd-rl/runs/pipe-r1 \
#   TRAIN_STEPS=3 ROLLOUT_N=4 TASK_FILTER=easy DAPO=0 \
#   bash examples/harbor_opd_rl/run_tb21_pipeline.sh
#
# Stages: env -> data -> oracle -> rollout -> train -> delta -> resume -> summary
set -euo pipefail
STAGES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stages"
PIPE_ROOT="${PIPE_ROOT:?absolute pipeline run root}"
FROM_STAGE="${FROM_STAGE:-}"
SKIP_STAGES="${SKIP_STAGES:-}"
ORDER=(env data oracle rollout train delta resume summary)
mkdir -p "${PIPE_ROOT}"
printf '{"stage":"driver","status":"start","utc":"%s","detail":{"argv":"%s","from":"%s","skip":"%s"}}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$0" "${FROM_STAGE}" "${SKIP_STAGES}" >> "${PIPE_ROOT}/pipeline-summary.jsonl"

started=0
for s in "${ORDER[@]}"; do
  [[ -z "${FROM_STAGE}" || "${s}" == "${FROM_STAGE}" ]] && started=1
  if [[ ${started} -eq 0 ]]; then echo "[driver] skip ${s} (before FROM_STAGE)"; continue; fi
  if [[ " ${SKIP_STAGES} " == *" ${s} "* ]]; then echo "[driver] skip ${s} (SKIP_STAGES)"; continue; fi
  if [[ "${s}" == "${FROM_STAGE}" ]]; then rm -f "${PIPE_ROOT}/${s}/PASSED"; fi
  if [[ -f "${PIPE_ROOT}/${s}/PASSED" && "${s}" != summary ]]; then echo "[driver] skip ${s} (PASSED $(cat "${PIPE_ROOT}/${s}/PASSED"))"; continue; fi
  script=$(ls "${STAGES_DIR}"/*_"${s}".sh)
  echo "[driver $(date -u +%H:%M:%S)] ==> ${s} (${script})"
  if ! bash "${script}"; then
    echo "[driver] stage ${s} FAILED; evidence under ${PIPE_ROOT}/${s}; rerun with FROM_STAGE=${s}" >&2
    printf '{"stage":"driver","status":"failed_at","utc":"%s","detail":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${s}" >> "${PIPE_ROOT}/pipeline-summary.jsonl"
    exit 1
  fi
done
echo "[driver] done: $(cat "${PIPE_ROOT}/summary/verdict.json")"
