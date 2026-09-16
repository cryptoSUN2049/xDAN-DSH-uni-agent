#!/usr/bin/env bash
# One-command driver for the Terminal-Bench 2.1 + Harbor (terminus-2, Modal) +
# VERL LoRA GRPO pipeline on a single GPU host. Every stage writes evidence under
# $PIPE_ROOT/<stage>/ and a line in $PIPE_ROOT/pipeline-summary.jsonl. Stages that
# already have a passing evidence file are skipped, so the driver can be re-run
# after a failure; FROM_STAGE=<name> forces a restart at that stage.
#
# Stages: env -> data -> oracle -> rollout -> train -> delta -> resume -> summary
#
# Required env: PIPE_ROOT (new or existing absolute run root)
# Optional env: LANE_ROOT, MODEL_PATH, TRAIN_STEPS, ROLLOUT_N, TASK_FILTER (easy|all),
#               MAX_INSTANCES, DAPO, WANDB_ENABLED, FROM_STAGE, SKIP_STAGES ("oracle rollout")
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LANE_ROOT="${LANE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
LANE_PY="${LANE_PY:-${LANE_ROOT}/envs/ua-verl-py312-vllm023-ws1/bin/python}"
export PATH="$(dirname "${LANE_PY}"):${PATH}"
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/verl${PYTHONPATH:+:${PYTHONPATH}}"
PIPE_ROOT="${PIPE_ROOT:?absolute pipeline run root}"
MODEL_PATH="${MODEL_PATH:-/workspace/models/Qwen3-4B-1cfa9a7}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-hosted_vllm/$(basename "${MODEL_PATH}")}"
TASK_CONFIG="${TASK_CONFIG:-${REPO_ROOT}/examples/harbor_opd_rl/tb21_terminus2_smoke.yaml}"
ORACLE_CONFIG="${ORACLE_CONFIG:-${REPO_ROOT}/examples/quickstart/harbor/task_config_oracle.yaml}"
TASK_FILTER="${TASK_FILTER:-easy}"          # easy = the four TB 2.1 tasks labelled easy; all = first MAX_INSTANCES
MAX_INSTANCES="${MAX_INSTANCES:-5}"
TRAIN_STEPS="${TRAIN_STEPS:-3}"
RESUME_EXTRA_STEPS="${RESUME_EXTRA_STEPS:-1}"
ROLLOUT_N="${ROLLOUT_N:-4}"
CONCURRENCY="${CONCURRENCY:-4}"
TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE:-2}"
FROM_STAGE="${FROM_STAGE:-}"
SKIP_STAGES="${SKIP_STAGES:-}"
DATA_DIR="${DATA_DIR:-${LANE_ROOT}/data}"
TB_DATASET_REF="${TB_DATASET_REF:-terminal-bench/terminal-bench-2-1}"
EASY_TASKS="${EASY_TASKS:-fix-git cobol-modernization prove-plus-comm overfull-hbox}"

mkdir -p "${PIPE_ROOT}"
SUMMARY="${PIPE_ROOT}/pipeline-summary.jsonl"
STAGES=(env data oracle rollout train delta resume summary)

log() { printf '[pipeline %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
record() { # stage status detail
  printf '{"stage":"%s","status":"%s","utc":"%s","detail":%s}\n' "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${3:-null}" >> "${SUMMARY}"
}
stage_done() { [[ -f "${PIPE_ROOT}/$1/PASSED" ]]; }
mark_passed() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${PIPE_ROOT}/$1/PASSED"; }
should_run() { # stage
  local s="$1"
  [[ " ${SKIP_STAGES} " == *" ${s} "* ]] && { log "skip ${s} (SKIP_STAGES)"; return 1; }
  if [[ -n "${FROM_STAGE}" ]]; then
    local i j; for i in "${!STAGES[@]}"; do [[ "${STAGES[$i]}" == "${FROM_STAGE}" ]] && j=$i; done
    local k; for k in "${!STAGES[@]}"; do [[ "${STAGES[$k]}" == "${s}" ]] && break; done
    [[ $k -lt ${j:-0} ]] && { log "skip ${s} (before FROM_STAGE=${FROM_STAGE})"; return 1; }
    [[ $k -eq ${j:-0} ]] && rm -f "${PIPE_ROOT}/${s}/PASSED"
  fi
  stage_done "${s}" && { log "skip ${s} (already PASSED)"; return 1; }
  mkdir -p "${PIPE_ROOT}/${s}"; return 0
}
gpu_free() {
  local used; used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  [[ "${used}" -lt 2000 ]] || { log "GPU busy (${used} MiB); refusing to start a GPU stage"; return 1; }
}
trainer_running() { ps -eo cmd | grep -qE "^[^ ]*python -m verl\.trainer\.main_ppo"; }

# ---------------------------------------------------------------- env
if should_run env; then
  D="${PIPE_ROOT}/env"
  "${LANE_PY}" - > "${D}/env-proof.json" <<'PY'
import importlib, importlib.metadata as im, json, sys, torch
mods=("vllm","ray","transformers","transfer_queue","verl","uni_agent","peft","harbor","modal","litellm","wandb")
for m in mods: importlib.import_module(m)
x=torch.randn(64,64,device="cuda",requires_grad=True); (x@x.T).square().mean().backward(); torch.cuda.synchronize()
assert x.grad.abs().sum().item()>0
print(json.dumps({"python":sys.version.split()[0],"prefix":sys.prefix,"gpu":torch.cuda.get_device_name(),
  "versions":{k:im.version(k) for k in ("torch","vllm","ray","harbor","modal","wandb")},"passed":True},indent=1))
PY
  command -v harbor >/dev/null
  modal profile current > "${D}/modal-profile.txt"
  "${LANE_PY}" -c 'import wandb; print(wandb.Api().default_entity)' > "${D}/wandb-entity.txt"
  mark_passed env; record env passed "$(cat "${D}/env-proof.json" | tr -d '\n')"
  log "env passed"
fi

# ---------------------------------------------------------------- data
if should_run data; then
  D="${PIPE_ROOT}/data"
  FULL_PARQUET="${DATA_DIR}/harbor_terminal-bench_terminal-bench-2-1.parquet"
  if [[ ! -f "${FULL_PARQUET}" ]]; then
    (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --dataset-ref "${TB_DATASET_REF}" \
       --local-save-dir "${DATA_DIR}" --max-instances "${MAX_INSTANCES}") > "${D}/preprocess-full.log" 2>&1
  fi
  TASK_ROOT="${DATA_DIR}/harbor/terminal-bench_terminal-bench-2-1/terminal-bench-2-1"
  if [[ "${TASK_FILTER}" == easy ]]; then
    E="${DATA_DIR}/tb21-easy-tasks"; rm -rf "${E}"; mkdir -p "${E}"
    for t in ${EASY_TASKS}; do cp -r "${TASK_ROOT}/${t}" "${E}/${t}"; done
    (cd "${REPO_ROOT}" && "${LANE_PY}" -m uni_agent.tasks.harbor.preprocess --task-root "${E}" \
       --local-save-dir "${DATA_DIR}/easy") > "${D}/preprocess-easy.log" 2>&1
    TRAIN_PARQUET="${DATA_DIR}/easy/harbor_tb21-easy-tasks.parquet"
  else
    TRAIN_PARQUET="${FULL_PARQUET}"
  fi
  echo "${TRAIN_PARQUET}" > "${D}/train-parquet.txt"
  echo "${FULL_PARQUET}" > "${D}/full-parquet.txt"
  "${LANE_PY}" -c "import pandas as pd,sys; d=pd.read_parquet(sys.argv[1]); print(len(d))" "${TRAIN_PARQUET}" > "${D}/train-rows.txt"
  mark_passed data; record data passed "{\"train_parquet\":\"${TRAIN_PARQUET}\",\"rows\":$(cat "${D}/train-rows.txt")}"
  log "data passed: ${TRAIN_PARQUET} ($(cat "${D}/train-rows.txt") rows)"
fi
TRAIN_PARQUET="$(cat "${PIPE_ROOT}/data/train-parquet.txt")"
FULL_PARQUET="$(cat "${PIPE_ROOT}/data/full-parquet.txt")"

# ---------------------------------------------------------------- oracle (Modal + verifier, no GPU)
if should_run oracle; then
  D="${PIPE_ROOT}/oracle"
  (cd "${REPO_ROOT}" && NUM_WORKERS=2 GLOBAL_CONCURRENCY=2 "${LANE_PY}" examples/inference/parallel_infer_api.py \
     --data-path "${TRAIN_PARQUET}" --task-config "${ORACLE_CONFIG}" --base-url http://unused.invalid/v1 \
     --limit 2 --concurrency 2 --log-dir "${D}/logs" --result-path "${D}/result.json") > "${D}/run.log" 2>&1
  "${LANE_PY}" - "${D}/result.json" <<'PY'
import json,sys; d=json.load(open(sys.argv[1])); s=d["summary"]
assert s["resolved"]==s["total_rollouts"]>0, s
print(json.dumps({"resolved":s["resolved"],"total":s["total_rollouts"],"mean_reward":s["mean_reward"]}))
PY
  mark_passed oracle; record oracle passed "$("${LANE_PY}" -c "import json;d=json.load(open('${D}/result.json'))['summary'];print(json.dumps({'resolved':d['resolved'],'total':d['total_rollouts']}))")"
  log "oracle passed"
fi

# ---------------------------------------------------------------- rollout (Gateway + vLLM, GPU)
if should_run rollout; then
  D="${PIPE_ROOT}/rollout"; gpu_free
  (cd "${REPO_ROOT}" && UNI_AGENT_LOG_DIR="${D}/logs" "${LANE_PY}" examples/inference/parallel_infer_verl.py \
     --data-path "${TRAIN_PARQUET}" --model-path "${MODEL_PATH}" --served-model-name "${SERVED_MODEL_NAME}" \
     --task-config "${TASK_CONFIG}" --engine vllm --tool-parser hermes --nnodes 1 --n-gpus-per-node 1 \
     --tensor-parallel-size 1 --gpu-memory-utilization 0.6 --max-model-len 36864 --limit 2 --concurrency 2 \
     --log-dir "${D}/logs" --result-path "${D}/result.json") > "${D}/run.log" 2>&1
  "${LANE_PY}" - "${D}/result.json" "${D}/logs" <<'PY'
import json,sys,glob,os
d=json.load(open(sys.argv[1])); assert d["num_scored_sessions"]==d["num_prompts"]*d["n"]>0, d
traj=glob.glob(os.path.join(sys.argv[2],"session-*","trajectory.npz")); assert len(traj)==d["num_scored_sessions"], traj
print(json.dumps({"scored_sessions":d["num_scored_sessions"],"mean_rm_score":d["mean_rm_score"],"trajectories":len(traj)}))
PY
  mark_passed rollout; record rollout passed "$("${LANE_PY}" -c "import json;d=json.load(open('${D}/result.json'));print(json.dumps({'scored_sessions':d['num_scored_sessions'],'mean_rm_score':d['mean_rm_score']}))")"
  log "rollout passed"
fi

# ---------------------------------------------------------------- train (GPU)
train_once() { # run_root exp_name total_steps [extra env...]
  local run_root="$1" exp="$2" steps="$3"; shift 3
  mkdir -p "${run_root}"
  (cd "${REPO_ROOT}" && env MODEL_PATH="${MODEL_PATH}" MODEL_ID="${SERVED_MODEL_NAME}" TRAIN_FILE="${TRAIN_PARQUET}" \
     TEST_FILE="${FULL_PARQUET}" TASK_CONFIG="${TASK_CONFIG}" RUN_ROOT="${run_root}" PYTHON_BIN="${LANE_PY}" \
     EXP_NAME="${exp}" TOTAL_TRAINING_STEPS="${steps}" TRAIN_MAX_SAMPLES=4 VAL_MAX_SAMPLES=1 \
     TRAIN_BATCH_SIZE="${TRAIN_BATCH_SIZE}" PPO_MINI_BATCH_SIZE="${TRAIN_BATCH_SIZE}" ROLLOUT_N="${ROLLOUT_N}" \
     CONCURRENCY="${CONCURRENCY}" ROLLOUT_MAX_NUM_SEQS="${CONCURRENCY}" SAVE_FREQ=1 "$@" \
     bash examples/harbor_opd_rl/train_tb21_lora_smoke.sh) > "${run_root}/train.log" 2>&1 || true
  # Completion is judged by the checkpoint + step metrics, not the exit code:
  # the trainer can hang in wandb teardown after everything is written.
  local ck; ck=$(find "${run_root}/checkpoints" -maxdepth 4 -type d -name "global_step_${steps}" | head -1)
  [[ -n "${ck}" && -f "${ck}/model_world_size_1_rank_0.pt" ]] || { log "train ${exp}: global_step_${steps} missing"; return 1; }
  grep -qE "step:${steps} - " "${run_root}/train.log" || { log "train ${exp}: step ${steps} metrics missing"; return 1; }
  if trainer_running; then
    log "train ${exp}: trainer lingering after completion; terminating"
    ps -eo pid,cmd | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo" | awk '{print $1}' | xargs -r kill -TERM; sleep 8
    ps -eo pid,cmd | grep -E "^ *[0-9]+ [^ ]*python -m verl\.trainer\.main_ppo" | awk '{print $1}' | xargs -r kill -KILL; sleep 3
  fi
  ray stop --force >/dev/null 2>&1 || true; sleep 3
  echo "${ck}" > "${run_root}/final-checkpoint.txt"
  grep -oE "step:[0-9]+ - .*" "${run_root}/train.log" > "${run_root}/step-metrics.txt"
}
metrics_json() { # step-metrics file -> json of key metrics per step
  "${LANE_PY}" - "$1" <<'PY'
import sys,json,re
keys=("training/global_step","critic/score/mean","critic/score/max","critic/score/min","actor/grad_norm","actor/pg_loss","response_length/mean","timing_s/gen","timing_s/update_actor")
out=[]
for line in open(sys.argv[1]):
    m=dict(re.findall(r"([\w/\-]+):(-?[0-9.]+(?:e-?\d+)?)",line))
    out.append({k:float(m[k]) for k in keys if k in m})
print(json.dumps(out))
PY
}
if should_run train; then
  D="${PIPE_ROOT}/train"; gpu_free
  train_once "${D}" "pipe-train" "${TRAIN_STEPS}"
  metrics_json "${D}/step-metrics.txt" > "${D}/metrics.json"
  mark_passed train; record train passed "$(cat "${D}/metrics.json")"
  log "train passed: $(cat "${D}/metrics.json")"
fi

# ---------------------------------------------------------------- delta (CPU): adapter changed, base unchanged
if should_run delta; then
  D="${PIPE_ROOT}/delta"
  CK_LAST="$(cat "${PIPE_ROOT}/train/final-checkpoint.txt")"
  CK_FIRST="$(dirname "${CK_LAST}")/global_step_1"
  BEFORE="${CK_FIRST}/model_world_size_1_rank_0.pt"; AFTER="${CK_LAST}/model_world_size_1_rank_0.pt"
  if [[ "${CK_FIRST}" == "${CK_LAST}" ]]; then
    record delta skipped '"single step: nothing to diff"'; mark_passed delta
  else
    (cd "${REPO_ROOT}" && "${LANE_PY}" deployment/checks/checkpoint_delta.py "${BEFORE}" "${AFTER}" --output "${D}/delta.json") > "${D}/run.log" 2>&1
    mark_passed delta; record delta passed "$(tr -d '\n' < "${D}/delta.json" | cut -c1-2000)"
  fi
  log "delta done"
fi

# ---------------------------------------------------------------- resume (GPU): reload last checkpoint, train +N
if should_run resume; then
  D="${PIPE_ROOT}/resume"; gpu_free
  CK_LAST="$(cat "${PIPE_ROOT}/train/final-checkpoint.txt")"
  TOTAL=$(( TRAIN_STEPS + RESUME_EXTRA_STEPS ))
  train_once "${D}" "pipe-resume" "${TOTAL}" RESUME_MODE=resume_path RESUME_FROM_PATH="${CK_LAST}"
  grep -qE "step:$(( TRAIN_STEPS + 1 )) - " "${D}/train.log"
  metrics_json "${D}/step-metrics.txt" > "${D}/metrics.json"
  mark_passed resume; record resume passed "$(cat "${D}/metrics.json")"
  log "resume passed"
fi

# ---------------------------------------------------------------- summary
if should_run summary; then
  D="${PIPE_ROOT}/summary"
  "${LANE_PY}" - "${SUMMARY}" "${PIPE_ROOT}" <<'PY'
import json,sys
rows=[json.loads(l) for l in open(sys.argv[1])]
last={r["stage"]:r for r in rows}
train=last.get("train",{}).get("detail") or []
nonzero=[s for s in train if isinstance(s,dict) and s.get("actor/grad_norm",0)>0]
mixed=[s for s in train if isinstance(s,dict) and s.get("critic/score/max",0)>s.get("critic/score/min",0)]
verdict={"stages":{k:v["status"] for k,v in last.items()},
 "steps_with_nonzero_grad":len(nonzero),"steps_with_reward_variance":len(mixed),
 "full_pipeline_mechanically_closed":all(last.get(s,{}).get("status") in ("passed","skipped") for s in ("env","data","oracle","rollout","train","delta","resume")),
 "learning_signal_observed":len(nonzero)>0}
json.dump(verdict,open(sys.argv[2]+"/summary/verdict.json","w"),indent=1); print(json.dumps(verdict))
PY
  mark_passed summary; record summary passed "$(cat "${D}/verdict.json" | tr -d '\n')"
fi
log "pipeline finished; summary at ${SUMMARY}"
