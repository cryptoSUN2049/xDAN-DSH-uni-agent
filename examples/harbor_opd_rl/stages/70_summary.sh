#!/usr/bin/env bash
# Stage summary: fold pipeline-summary.jsonl into verdict.json with two booleans:
#   full_pipeline_mechanically_closed  every stage passed or was legitimately skipped
#   learning_signal_observed           at least one training step had grad_norm > 0
STAGE_NAME=summary
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

"${LANE_PY}" - "${SUMMARY}" "${STAGE_DIR}/verdict.json" <<'PY'
import json,sys
rows=[json.loads(l) for l in open(sys.argv[1])]
last={r["stage"]:r for r in rows}
def steps(stage): d=last.get(stage,{}).get("detail"); return d if isinstance(d,list) else []
train=steps("train")+steps("resume")
nonzero=[s["training/global_step"] for s in train if s.get("actor/grad_norm",0)>0]
mixed=[s["training/global_step"] for s in train if s.get("critic/score/max",0)>s.get("critic/score/min",0)]
required=("env","data","oracle","rollout","train","delta","resume")
verdict={"stages":{k:v["status"] for k,v in last.items() if k!="summary"},
 "steps_with_nonzero_grad":nonzero,"steps_with_reward_variance":mixed,
 "full_pipeline_mechanically_closed":all(last.get(s,{}).get("status") in ("passed","skipped") for s in required),
 "learning_signal_observed":len(nonzero)>0,
 "wandb":{k:open(f"{sys.argv[2].rsplit('/',2)[0]}/{k}/wandb-url.txt").read().strip() for k in ("train","resume") if last.get(k)}}
json.dump(verdict,open(sys.argv[2],"w"),indent=1); print(json.dumps(verdict))
PY
# Retention on this run only (dry-run output kept as evidence, then applied).
bash "${REPO_ROOT}/deployment/bootstrap/retain-checkpoints.sh" --keep "${RETAIN_KEEP:-10}" "${PIPE_ROOT}" > "${STAGE_DIR}/retention-plan.txt" 2>&1 || true
bash "${REPO_ROOT}/deployment/bootstrap/retain-checkpoints.sh" --apply --keep "${RETAIN_KEEP:-10}" "${PIPE_ROOT}" > "${STAGE_DIR}/retention-applied.txt" 2>&1 || true
mark_passed; record passed "$(tr -d '\n' < "${STAGE_DIR}/verdict.json")"
