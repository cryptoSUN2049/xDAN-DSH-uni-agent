#!/usr/bin/env bash
set -euo pipefail
R=/workspace/apus-mimo-identity
for attempt in $(seq 1 90); do
  if curl --silent --fail --max-time 3 http://127.0.0.1:8019/health >/dev/null; then
    exec /workspace/ms-swift-jev/venv/bin/python -u "$R/probe.py" --output-dir "$R/results-v1"
  fi
  sleep 10
done
echo 'FAILED: server health not ready within 15 minutes' >&2
exit 1
