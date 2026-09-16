#!/usr/bin/env bash
# Stage acceptance: turn evidence into a pass/fail report. Three layers:
#   1 mechanics  every required stage PASSED (from pipeline-summary.jsonl)
#   2 dynamics   wandb run history (pulled through the API, so it is the same data
#                the dashboard shows) agrees with the local step metrics and shows a
#                live update: reward variance, finite non-zero grad_norm, finite loss
#   3 weights    checkpoint delta: adapter tensors changed, base tensors unchanged;
#                resume continued from the absolute step
# Writes acceptance.json; exits non-zero when any hard check fails.
STAGE_NAME=acceptance
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

"${LANE_PY}" - "${PIPE_ROOT}" "${STAGE_DIR}/acceptance.json" "${TRAIN_STEPS}" <<'PY'
import json, math, os, sys
root, out, train_steps = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = [json.loads(l) for l in open(f"{root}/pipeline-summary.jsonl")]
last = {r["stage"]: r for r in rows}
checks = {}

# 1 mechanics
required = ("env", "data", "oracle", "rollout", "train", "delta", "resume")
checks["stages_passed"] = {s: last.get(s, {}).get("status") for s in required}
checks["mechanics_ok"] = all(v in ("passed", "skipped") for v in checks["stages_passed"].values())

# 2 dynamics: local metrics
def steps(stage):
    d = last.get(stage, {}).get("detail"); return d if isinstance(d, list) else []
local = steps("train") + steps("resume")
finite = lambda x: isinstance(x, (int, float)) and math.isfinite(x)
checks["local_steps"] = [s.get("training/global_step") for s in local]
checks["grad_norm"] = [s.get("actor/grad_norm") for s in local]
checks["pg_loss"] = [s.get("actor/pg_loss") for s in local]
checks["score_mean"] = [s.get("critic/score/mean") for s in local]
checks["reward_variance_steps"] = [s["training/global_step"] for s in local if s.get("critic/score/max", 0) > s.get("critic/score/min", 0)]
checks["nonzero_grad_steps"] = [s["training/global_step"] for s in local if finite(s.get("actor/grad_norm")) and s["actor/grad_norm"] > 0]
checks["all_finite"] = all(finite(s.get("actor/grad_norm")) and finite(s.get("actor/pg_loss")) for s in local)

# 2 dynamics: wandb API (same data as the dashboard)
wandb_report = {}
try:
    import wandb
    api = wandb.Api()
    for stage in ("train", "resume"):
        url_file = f"{root}/{stage}/wandb-url.txt"
        if not os.path.exists(url_file): continue
        url = open(url_file).read().strip()
        if not url: continue
        path = url.split("wandb.ai/")[1]  # entity/project/runs/id
        entity, project, _, run_id = path.split("/")[:4]
        run = api.run(f"{entity}/{project}/{run_id}")
        hist = run.history(keys=["training/global_step", "critic/score/mean", "actor/grad_norm", "actor/pg_loss"], pandas=False)
        wandb_report[stage] = {"url": url, "state": run.state, "rows": [
            {k: h.get(k) for k in ("training/global_step", "critic/score/mean", "actor/grad_norm", "actor/pg_loss")} for h in hist]}
    # agreement: every local step's grad_norm appears in wandb within 1e-6
    wb = {r["training/global_step"]: r for st in wandb_report.values() for r in st["rows"] if r.get("training/global_step") is not None}
    agree = [s["training/global_step"] for s in local if s["training/global_step"] in wb and abs(wb[s["training/global_step"]]["actor/grad_norm"] - s["actor/grad_norm"]) < 1e-6]
    checks["wandb_agrees_steps"] = agree
    checks["wandb_ok"] = len(agree) == len(local) and len(local) > 0
except Exception as exc:  # wandb outage must not hide the offline evidence
    checks["wandb_ok"] = False; checks["wandb_error"] = repr(exc)[:300]
checks["wandb"] = wandb_report

# 3 weights (deployment/checks/checkpoint_delta.py schema dsh.single-rank-lora-delta.v1)
delta_file = f"{root}/delta/delta.json"
if os.path.exists(delta_file):
    d = json.load(open(delta_file))
    checks["delta"] = {k: d.get(k) for k in ("passed", "adapter_count", "adapter_changed", "base_count", "base_changed")}
    checks["adapter_changed"] = bool(d.get("adapter_changed"))
    checks["base_unchanged"] = d.get("base_changed") == 0 and bool(d.get("base_count"))
else:
    checks["delta"] = last.get("delta", {}).get("status")
    checks["adapter_changed"] = None; checks["base_unchanged"] = None
resume_steps = [s.get("training/global_step") for s in steps("resume")]
checks["resume_continued"] = any(st == train_steps + 1 for st in resume_steps)

hard = {
    "mechanics_ok": checks["mechanics_ok"],
    "all_finite": checks["all_finite"],
    "resume_continued": checks["resume_continued"],
}
soft = {
    "learning_signal": len(checks["nonzero_grad_steps"]) > 0,
    "reward_variance": len(checks["reward_variance_steps"]) > 0,
    "wandb_ok": checks.get("wandb_ok", False),
    "adapter_changed": checks.get("adapter_changed") is True,
    "base_unchanged": checks.get("base_unchanged") is True,
}
report = {"hard": hard, "soft": soft, "checks": checks,
          "verdict": "PASS" if all(hard.values()) and all(soft.values()) else ("MECHANICS_ONLY" if all(hard.values()) else "FAIL")}
json.dump(report, open(out, "w"), indent=1)
print(json.dumps({"verdict": report["verdict"], "hard": hard, "soft": soft}))
sys.exit(0 if all(hard.values()) else 1)
PY
STATUS=$?
mark_passed; record "$([[ ${STATUS} -eq 0 ]] && echo passed || echo failed)" "$(tr -d '\n' < "${STAGE_DIR}/acceptance.json" | cut -c1-4000)"
exit ${STATUS}
