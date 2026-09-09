# Validation score consumption audit correction

Goal: audit the actual pinned VERL validation dump without changing rewards or admitting invalid stage evidence.

Pinned VERL `fefb080262e1c015a0ea05f958822a6a512dc795`, `trainer_base.py` validation dump maps each trajectory key to its session's final sample score. `_log_rollout_data` retains each original stage score for training. The old auditor applied training semantics to validation, incorrectly rejecting a valid A=0/B=1 chain dumped as 1/1.

Flow: original stage receipt + trace → existing strict crosswalk/lineage verification → validation: same verified chain's terminal B reward; training: original stage reward → compare consumed row score. All original stage checks, group/sibling identity, unique keys, missing/duplicate checks remain mandatory. No cross-group terminal lookup and no artifact mutation.

Files: `examples/dsh/capabilities/audit_memory_training.py`; `tests/uni_agent/examples/test_audit_memory_training.py`.

Tests: real framework chain with unequal A/B rewards; validation broadcast accepted, original-stage validation dump rejected; training retains original scores and rejects broadcast; tampered chain/receipt/trace rejected; multi-context coverage retained. Execute pinned validation dump AST to guard the semantics against source changes.

Deployment: this is an independent offline auditor change. Run it from a new fixed checkout against immutable original run artifacts. Do not rewrite the original launch manifest or its source SHA. Report both execution source and audit source. No SDK/runtime/VERL update is needed.

## Verification

- RED: `test_validation_broadcasts_verified_terminal_reward` failed before the fix: original A=1/B=0 receipts, actual validation semantics 0/0, old audit rejected.
- GREEN: entire `test_audit_memory_training.py`: **33 passed** (18.83 s). Includes original trace/hash/sibling/submission/missing/duplicate checks, multiple contexts, unequal original rewards, training broadcast rejection, and executing pinned `_validate` dump AST across two sessions with different terminal scores.
- Scoped Ruff check and format check passed. Parent must run repository-wide mandatory gates before push.
- GPU is not required to re-score the immutable existing validation dumps. Independent audit of the actual 901/902 artifacts remains the parent's next verification step.
