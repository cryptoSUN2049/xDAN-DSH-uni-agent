#!/usr/bin/env bash
# Native Linux build from a pinned, already authenticated GitHub checkout.
set -euo pipefail
: "${DSH_SOURCE_ROOT:?Absolute DSH checkout required}"
: "${DSH_TOOLS_ROOT:?Absolute build tools directory required}"
[[ "$DSH_SOURCE_ROOT" = /* && "$DSH_TOOLS_ROOT" = /* ]] || exit 2
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || exit 2
[[ "$(git -C "$DSH_SOURCE_ROOT" rev-parse HEAD)" == 7840bced35ee07ebefbdce0106b56dbc00bdc3ef ]] || exit 2
[[ -z "$(git -C "$DSH_SOURCE_ROOT" status --porcelain --untracked-files=no)" ]] || exit 2
mkdir -p "$DSH_TOOLS_ROOT"
cd "$DSH_TOOLS_ROOT"
archive=node-v24.20.0-linux-x64.tar.xz
if [[ ! -f "$archive" ]]; then
  curl -fsSLo "$archive" "https://nodejs.org/dist/v24.20.0/$archive"
fi
printf '2f2c0da162318f0de47665410c7c8c2ed3d36c8f3105de4bbc61176c70a7cbf2  %s\n' "$archive" | sha256sum -c -
# RunPod network volumes do not permit restoring archive UID/GID ownership.
tar --no-same-owner -xJf "$archive"
export PATH="$DSH_TOOLS_ROOT/node-v24.20.0-linux-x64/bin:$PATH"
npm install --global --prefix "$DSH_TOOLS_ROOT/pnpm-11.7.0" pnpm@11.7.0
export PATH="$DSH_TOOLS_ROOT/pnpm-11.7.0/bin:$PATH"
cd "$DSH_SOURCE_ROOT"
pnpm install --frozen-lockfile
pnpm exec tsx scripts/build-exe-for-python-sdk.ts --targets=node24-linux-x64
sha256sum dist-exe/deepseek-harness-sdk-runtime-linux-x64
