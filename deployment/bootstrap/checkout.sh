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
clone_url=https://github.com/cryptoSUN2049/xDAN-DSH-uni-agent.git
askpass=""
cleanup() {
  if [[ -n "$askpass" ]]; then
    rm -f -- "$askpass"
  fi
}
trap cleanup EXIT
# Private GitHub checkout: use the exported token only through Git's askpass
# protocol; the token is never written to this repository or command arguments.
token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [[ -n "$token" ]]; then
  askpass=$(mktemp)
  chmod 700 "$askpass"
  cat >"$askpass" <<'ASKPASS'
#!/usr/bin/env bash
case "${1:-}" in
  *Username*) printf '%s\n' x-access-token ;;
  *Password*) printf '%s\n' "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ;;
  *) printf '\n' ;;
esac
ASKPASS
  GIT_ASKPASS="$askpass" GIT_TERMINAL_PROMPT=0 git clone --no-checkout "$clone_url" "$destination"
else
  git clone --no-checkout "$clone_url" "$destination"
fi
git -C "$destination" checkout --detach "$revision"
test "$(git -C "$destination" rev-parse HEAD)" = "$revision"
git -C "$destination" submodule update --init --recursive
printf 'Pinned checkout ready: %s\n' "$revision"
