#!/usr/bin/env bash
# Rebuild one uv lane on the persistent volume from its single frozen snapshot.
# Inherited from xDAN-DSH-MetaRSI docs/main/uv-runbook.md: every asset lives on
# /workspace, the venv is never placed on pod-local disk, the lock is the only
# source of package versions, and activation is proven by sys.prefix + CUDA math
# + key imports before the lane may be used.
set -euo pipefail

LANE="${LANE:-ua-verl-py312-vllm023}"
ROOT="${WORKSPACE_ROOT:-/workspace/verl-uni-agent-harbor-opd-rl}"
VENV="${UV_VENV:-$ROOT/envs/$LANE}"
PYTHON="${UV_PYTHON:-/usr/bin/python3.12}"
LOCK="${LANE_LOCK:-$ROOT/src/uni-agent/deployment/versions/uv-lanes/$LANE.freeze.txt}"
RUNS="${RUNS_DIR:-$ROOT/runs}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/cache/uv}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

fail() { printf 'uv-lane-bootstrap: %s\n' "$*" >&2; exit 2; }

[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail "Linux x86_64 only"
command -v uv >/dev/null || fail "uv not on PATH"
[[ "$VENV" = /workspace/* ]] || fail "venv must live under /workspace, got $VENV"
[[ "$UV_CACHE_DIR" = /workspace/* ]] || fail "uv cache must live under /workspace"
[[ -f "$LOCK" ]] || fail "lock not found: $LOCK"
[[ -x "$PYTHON" ]] || fail "python not found: $PYTHON"
if [[ -d "$VENV/lib" ]] && [[ "$(find "$VENV/lib" -maxdepth 3 -name 'site-packages' -exec sh -c 'ls "$1" | wc -l' _ {} \; | head -1)" -gt 10 ]]; then
  fail "$VENV already populated; choose a new UV_VENV instead of overwriting"
fi
mkdir -p "$RUNS" "$UV_CACHE_DIR" "$(dirname "$VENV")"

LOG="$RUNS/uv-lane-$LANE-$STAMP.log"
exec > >(tee -a "$LOG") 2>&1
echo "lane=$LANE venv=$VENV python=$PYTHON lock=$LOCK cache=$UV_CACHE_DIR"
sha256sum "$LOCK"

uv venv "$VENV" --python "$PYTHON"
uv pip sync --python "$VENV/bin/python" "$LOCK"
uv pip check --python "$VENV/bin/python" || echo "uv pip check reported conflicts; review above before use"

# Activation proof. Any failure below leaves the lane unverified.
"$VENV/bin/python" - <<'PY'
import sys, importlib
print("sys.prefix", sys.prefix)
print("python", sys.version.split()[0])
import torch
a = torch.arange(32, device="cuda", dtype=torch.float32)
assert (a * a).sum().item() == 10416, "CUDA arithmetic mismatch"
print("torch", torch.__version__, torch.cuda.get_device_name())
for m in ("vllm", "ray", "transformers", "peft", "transfer_queue", "verl", "uni_agent"):
    importlib.import_module(m)
print("imports passed")
PY

FREEZE="$RUNS/uv-lane-$LANE-$STAMP.freeze.txt"
uv pip freeze --python "$VENV/bin/python" > "$FREEZE"
if diff -q <(grep -v '^-e ' "$LOCK" | sort) <(grep -v '^-e ' "$FREEZE" | sort) >/dev/null; then
  echo "freeze matches lock"
else
  echo "freeze differs from lock:"
  diff <(grep -v '^-e ' "$LOCK" | sort) <(grep -v '^-e ' "$FREEZE" | sort) || true
fi
cat > "$RUNS/uv-lane-$LANE-$STAMP.manifest.json" <<JSON
{"lane":"$LANE","venv":"$VENV","python":"$("$VENV/bin/python" -c 'import sys;print(sys.version.split()[0])')","lock":"$LOCK","lock_sha256":"$(sha256sum "$LOCK" | cut -d' ' -f1)","driver":"$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)","gpu":"$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)","freeze":"$FREEZE","log":"$LOG","utc":"$STAMP"}
JSON
echo "manifest $RUNS/uv-lane-$LANE-$STAMP.manifest.json"
