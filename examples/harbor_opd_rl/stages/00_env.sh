#!/usr/bin/env bash
# Stage env: prove the uv lane can drive the GPU and import the whole stack,
# and that Harbor CLI, Modal and wandb credentials are usable. No model load.
STAGE_NAME=env
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"; stage_dir

"${LANE_PY}" - > "${STAGE_DIR}/env-proof.json" <<'PY'
import importlib, importlib.metadata as im, json, sys, torch
mods=("vllm","ray","transformers","transfer_queue","verl","uni_agent","peft","harbor","modal","litellm","wandb")
for m in mods: importlib.import_module(m)
x=torch.randn(64,64,device="cuda",requires_grad=True); (x@x.T).square().mean().backward(); torch.cuda.synchronize()
assert x.grad.abs().sum().item()>0
print(json.dumps({"python":sys.version.split()[0],"prefix":sys.prefix,"gpu":torch.cuda.get_device_name(),
  "versions":{k:im.version(k) for k in ("torch","vllm","ray","harbor","modal","wandb")},"imports":list(mods),"passed":True},indent=1))
PY
command -v harbor >/dev/null || { log "harbor CLI missing"; exit 2; }
modal profile current > "${STAGE_DIR}/modal-profile.txt"
"${LANE_PY}" -c 'import wandb; print(wandb.Api().default_entity)' > "${STAGE_DIR}/wandb-entity.txt"
mark_passed; record passed "$(tr -d '\n' < "${STAGE_DIR}/env-proof.json")"
log "passed: modal=$(cat "${STAGE_DIR}/modal-profile.txt") wandb=$(cat "${STAGE_DIR}/wandb-entity.txt")"
