#!/bin/bash
set -eu
mkdir -p /logs/verifier
if printf 'harbor-h0-ok\n' | cmp -s - /app/answer.txt; then
  printf '1\n' > /logs/verifier/reward.txt
else
  printf '0\n' > /logs/verifier/reward.txt
fi
