# Teacher bridge review — d94305b

Date: 2026-09-15. Scope: `entry.py`, `framework.py`, new CPU Teacher tests, resident memory/work-state subclasses, pinned VERL distillation consumers. Product code was not modified by this review.

## Confirmed findings

1. **Resident Framework initialization rejects OPD.** `NativeMemoryFramework.from_config` does not accept `teacher_client`; `NativeWorkStateFramework` inherits the same method. The newly enabled adapter passes that keyword through `build_agent_framework`, yielding `TypeError` before construction. Added eight red tests in `test_teacher_memory_on_cpu.py`: two forwarding cases plus preservation of sync, n4, and verifier admission constraints. Red evidence: `/private/tmp/uni-agent-opd-memory-red.log`.
2. **Registered Harbor postprocessor rejects the upstream task-result contract.** Identified by the main implementation agent and reproduced here: `validate_registered_trajectories` still rejects `task_result`. The existing wrapper test now supplies a real `TaskResult` and requires identity-preserving delegation to `validate_trajectories`. Red evidence: `/private/tmp/uni-agent-opd-registration-red.log`.
3. **Teacher RPC waiting is unbounded by the runner timeout.** `session_timeout_seconds` only encloses the Ray runner await. Teacher scoring follows later, without a timeout. A deterministic suspended Teacher manager keeps the prompt at `running`; cancelling the outer generation task also leaves that status. This does not establish a real server outage, but directly demonstrates the missing framework failure boundary. Probe: `/private/tmp/uni-agent-opd-review-probe.py` and `.log`. A separate Teacher deadline and cancellation/status contract should be implemented before unattended campaigns; this review did not change that contract.

## Verified behavior

- Adapter rejects enabled distillation without clients and rejects supplied clients when distillation is disabled before spawning the gateway.
- Real Worker construction, `build_agent_framework`, and default `GatewayAgentFramework.from_config` preserve Teacher client identity. Existing RL-only custom factories are not forced to accept the new keyword.
- Every returned/admitted trajectory is scored. Original token sequences, action masks, verifier reward and receipt are retained; no second next-token shift is introduced.
- Validation does not call Teacher. Exceptions propagate through the existing strict group mechanism: no successful sibling is written and the UID transitions from running to failure.
- Teacher tensors move from trajectory extension fields to top-level TQ fields. Partial Teacher columns fail closed. Different sequence lengths with the same top-k use sequence-axis ragged nesting (`ragged_idx=1`).
- Actual pinned VERL `no_padding_2_padding` consumes Teacher rows beginning at `prompt_length - 1`. The actual reverse-KL estimator was exercised on a five-token sequence with response mask `[1, 0, 1]`: response loss shape `[1, 3]`; full-sequence Student gradients `[0, 1, 0, 1, 0]`, including zero gradient at the inserted tool token.
- Resident stage assembly concatenates the existing writer/reader trajectory objects. Inspection found no additional Teacher-field deletion in that assembly. Subclass initialization was the blocking issue above.

## Evidence limits and remaining tests

CPU execution uses Torch 2.14.0, whereas the production VERL environment pins Torch 2.11. CPU contracts do not establish GPU backend/model support, top-k GPU gather behavior, actual Teacher RPC availability, LoRA parameter updates or checkpoint reload.

The current tests demonstrate Teacher-to-TQ and native sampled-loss alignment. A real GPU test must still demonstrate the configured PPO plus distillation objective consuming these fields and updating parameters. Teacher scoring timeout/cancellation deserves a dedicated regression once its intended timeout value and ownership contract are selected.

## Remediation verified after review

All three findings are fixed: resident factories forward Teacher clients while retaining their synchronous constraints; the registered postprocessor accepts and forwards TaskResult; Teacher requests have a finite configurable 300-second default deadline. The timeout test observes strict UID running→failure with zero trajectory publication. Final Teacher/Memory/recipe contracts: 66 passed; related registration/Memory/Work-state regression: 131 passed. External whole-rollout cancellation status remains a separate pre-existing issue and is not claimed fixed.
