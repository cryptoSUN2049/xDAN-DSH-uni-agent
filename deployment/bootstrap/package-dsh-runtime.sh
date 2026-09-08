#!/usr/bin/env bash
# Package the completed Session v2 Linux build using the official release tool.
set -euo pipefail
umask 077
: "${DSH_SOURCE_ROOT:?Absolute DSH checkout required}"
: "${DSH_RELEASE_ROOT:?New absolute release output directory required}"
[[ "$DSH_SOURCE_ROOT" = /* && "$DSH_RELEASE_ROOT" = /* ]] || exit 2
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || exit 2
dsh_revision="$(git -C "$DSH_SOURCE_ROOT" rev-parse HEAD)"
[[ "$dsh_revision" == b2369692ea530007075ebcd18d39fdba0bbd3982 ]] || exit 2
dsh_status="$(git -C "$DSH_SOURCE_ROOT" status --porcelain --untracked-files=no)"
[[ -z "$dsh_status" ]] || exit 2
[[ ! -e "$DSH_RELEASE_ROOT" && ! -L "$DSH_RELEASE_ROOT" ]] || exit 2
cd "$DSH_SOURCE_ROOT"
dsh_binary="$PWD/dist-exe/deepseek-harness-sdk-runtime-linux-x64"
for dsh_payload in "$dsh_binary" "$dsh_binary-rg"; do
  [[ -f "$dsh_payload" && -x "$dsh_payload" && ! -L "$dsh_payload" ]] || exit 2
done
[[ -f scripts/build-python-release.py ]] || exit 2
command -v python3 >/dev/null
command -v sha256sum >/dev/null
# Operator PATH selects uv; preserve the actual version rather than invent a pin.
dsh_uv_version="$(uv --version)"
[[ "$dsh_uv_version" == uv\ * ]] || exit 2
# mkdir without -p is also the exclusive claim against another packaging run.
mkdir -- "$DSH_RELEASE_ROOT"
python3 scripts/build-python-release.py --package runtime --platform linux-x64 \
  --runtime-exe "$dsh_binary" --tag python-v0.1.3-alpha.2 --output-dir "$DSH_RELEASE_ROOT"
python3 scripts/build-python-release.py --package sdk \
  --tag python-v0.1.3-alpha.2 --output-dir "$DSH_RELEASE_ROOT"
cd "$DSH_RELEASE_ROOT"
dsh_runtime_wheel=deepseek_harness_runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64.whl
dsh_sdk_wheel=deepseek_harness_sdk-0.1.3a2-py3-none-any.whl
[[ -f "$dsh_runtime_wheel" && -f "$dsh_sdk_wheel" ]] || exit 2
python3 - "$dsh_revision" "$dsh_uv_version" <<'PY'
import json
import sys
from pathlib import Path

Path("build-info.json").write_text(json.dumps({
    "source_revision": sys.argv[1],
    "package_version": "0.1.3-alpha.2",
    "python_distribution_version": "0.1.3a2",
    "platform": "linux-x64",
    "uv_version": sys.argv[2],
    "status": "packaged-not-installed",
}, indent=2) + "\n")
PY
sha256sum "$dsh_binary" "$dsh_binary-rg" \
  "$dsh_runtime_wheel" "$dsh_sdk_wheel" build-info.json > SHA256SUMS
