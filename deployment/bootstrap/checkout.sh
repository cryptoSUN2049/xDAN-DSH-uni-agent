#!/usr/bin/env bash
# Create a NEW checkout from GitHub at an exact reviewed commit.
set -euo pipefail
if [[ $# -ne 2 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: bash deployment/bootstrap/checkout.sh <40-character commit> <new-directory>" >&2
  exit 2
fi
revision="$1"
destination="$2"
if [[ -e "$destination" ]]; then
  echo "Destination already exists; use a new directory to preserve existing runs." >&2
  exit 2
fi
git clone --no-checkout https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent.git "$destination"
git -C "$destination" checkout --detach "$revision"
test "$(git -C "$destination" rev-parse HEAD)" = "$revision"
git -C "$destination" submodule update --init --recursive
printf 'Pinned checkout ready: %s\n' "$revision"
