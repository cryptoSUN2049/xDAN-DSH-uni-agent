#!/usr/bin/env bash
export PATH=/workspace/verl-uni-agent-harbor-opd-rl/envs/ua-verl-py312-vllm023-ws1/bin:$PATH
cd /workspace/verl-uni-agent-harbor-opd-rl/runs/swe-ctrf-diag
for t in swe-rebench-v2-fv__aio-libs__aiohttp-8538 swe-rebench-v2-fv__aristanetworks__anta-969 swe-rebench-v2-fv__pallets__click-2788; do
  ( timeout 2400 harbor trial start --path /workspace/verl-uni-agent-harbor-opd-rl/runs/swe-ctrf-diag/data/stage1/tasks-train/$t --trial-name oracle-${t##*__} --trials-dir /workspace/verl-uni-agent-harbor-opd-rl/runs/swe-ctrf-diag/trials --agent oracle --env modal --timeout-multiplier 1 > /workspace/verl-uni-agent-harbor-opd-rl/runs/swe-ctrf-diag/oracle-${t##*__}.log 2>&1; echo "[oracle] $t exit=$?" ) &
done
wait
for f in /workspace/verl-uni-agent-harbor-opd-rl/runs/swe-ctrf-diag/trials/*/verifier/reward.txt; do echo "[oracle] reward $f = $(cat $f)"; done
echo "[oracle] done"
