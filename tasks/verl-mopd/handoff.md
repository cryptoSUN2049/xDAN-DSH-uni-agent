# VERL MOPD handoff

## TL;DR
User switched the real MOPD acceptance task from Tinker to VERL on 2026-09-22, for easier debugging and algorithm changes.
Worktree verl-mopd; branch worktree-verl-mopd; base outer7897cad / VERL a9f29851.
Read docs/verl-mopd/design.md. Current phase: explain and freeze the native algorithm and minimal integration design. No new GPU run submitted.

## Deliverables
- docs/verl-mopd/design.md: architecture, exact native PG semantics, data/API contracts, files, tests, resources.
- This handoff and tasks/verl-mopd/lessons.md: current scope and corrections.
- Tinker reference implementation remains in ../tinker-mopd, initial code643babc; no cloud execution there.

## Constraints
Keep original VERL worktree, existing GPU0 evaluation jobs and source/data unchanged. Use native TeacherManager/loss, preserve data_source and Harbor dispatch. Teacher-domain routing is a separate explicit field. Never print secrets. Real execution requires the current owner/schedule and new MOPD budget contract.

## Findings
Native k1 uses current actor logprob minus teacher, detached before PPO; vanilla includes ratio and dual clipping. Pure OPD task loss is discarded and its distillation coefficient fixed to1. Global token mean is per optimizer minibatch, so freeze ppo_epochs and minibatch boundaries. Hydra sets loss_max_clamp=null unless explicitly overridden. Two real sequential checkpoints prove plumbing only, not expert complementarity.

## Next milestone
- [ ] Finish design explanation and freeze initial PG recipe.
- [ ] Domain preparation and named two-teacher config.
- [ ] Persist route/teacher identity through framework evidence.
- [ ] CPU route/loss/mask/reduction/resume tests.
- [ ] Verify direct teacher weight loading and GPU topology; freeze budget/ownership.
- [ ] Real update, save, reload, resume; evidence report.

## Branch / deployment
New isolated local branch, no deployment. Original VERL HEAD7897cad was clean when inspected. Existing evaluation resource snapshot is in design.md and is not a scheduling grant.

## Cold start
Read this file and design, inspect git/submodule state, read latest original-line handoff and GPU schedule, continue bounded CPU implementation, freeze concrete GPU commands/resources before new calls.
