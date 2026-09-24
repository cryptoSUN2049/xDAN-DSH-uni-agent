# Live verification checkpoint

- Published HEAD a7f8344 (remote branch SHA verified).
- Single-GPU export probe r1 started through dedicated SSH master socket `/private/tmp/uni-agent-opd-validation-ssh.sock`.
- Remote PID 32559, parent timeout PID 32558, bound 900 seconds. Never restart until authoritative process/result check.
- Model `/workspace/models/Qwen3-4B-1cfa9a7`; script `deployment/checks/fsdp_lora_merged_export.py`.
- Evidence `/workspace/verl-uni-agent-harbor-opd-rl/runs/fsdp-lora-export-r1.{json,log}`.
- r1 terminated with AssertionError during FSDP forward; failed JSON retained. Probe had use_orig_params=True unlike recipe default False. Script aligned to False; trainable names inspected inside summon_full_params.
- r2 launched after r1 exited; same 900-second bound, output fsdp-lora-export-r2.{json,log}. No success claim until result inspection.
- SSH direct handshakes often timeout. Dedicated master restored connectivity; use `ssh -S`/`scp -o ControlPath` while alive.
- Pending user text: dual-GPU SSH/model capacity and project-specific public Gateway hostname/tunnel.

## Terminal update
- r2 PID33362 exited 0. Evidence copied into docs/worktree/fsdp-lora-export-r2.json.
- 144 changed adapters, zero changed base, 399 exported tensors; selected merged layer and trainer restoration exact.
- r1 retained; no running export probe remains. Next operation is two-GPU publication/reload, pending user SSH details.

## PR3 / reload terminal checkpoint
- PR3 merged2b3eff3;49 focused tests passed.
- save-r3 and resume-r4 both passed; no GPU process left. r4 exact trainer and optimizer restoration + two additional updates.
- SSH interrupted save observation; direct process/result checks proved it continued and completed, no duplicate job started.
- Native checkpoint path retained in evidence, no model weights added to repository.
