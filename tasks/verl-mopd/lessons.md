# Lessons

- User selected VERL for editable algorithm internals. Do not continue Tinker deployment because its offline implementation already exists.
- MOPD is a training recipe with data/routing/serving/gradient contracts. It is not a model-architecture change or merely a loss coefficient.
- Reuse configurable teacher_key with teacher_domain. Do not overwrite data_source when it also identifies dataset/reward/validation groups.
- Exact native loss matters: k1 current probabilities + detached advantage + PPO/dual clipping differs from Tinker rollout-fixed IS. Never imply numerical equivalence without matching these choices.

- One task is not necessarily one trajectory. Enforce one admitted chain for the first two-task/one-minibatch acceptance; never silently drop alternate chains.
- Native V1 overwrites optimizer horizon and forces checkpoint transport naive. Freeze zero-warmup constant LR across smoke resume; report actual runtime settings.
- Repository pre-commit pins Ruff0.12.2, but inherited files contain five UP038 violations there. Installed Ruff0.13.3 passes whole-tree lint and format; borrowed Tinker Ruff0.16.7 additionally formats Markdown. Record the actual tool version, not a misleading mixed gate.

- User explicitly included long-trajectory weighting in MiMo alignment. Carry sequence-mean reduction into every new recipe and compare separately with tokenmean. 91% is an averaging coefficient under comparable token losses, not measured gradient share; equal trajectory weights do not guarantee shorter generations.

- Native sync trainer step1 consumes published weight version0; require one actual policy version per trajectory, not equality to the prompt/training step tag.
- Current engineering recipes inherit LoRA rank16 from base.yaml. Matching public MiMo objective equations is distinct from reproducing its full-parameter production training, data, or capability gains.
- Keep tracked VERL patches complete including new files; git diff alone omits untracked modules. Verify clean apply against pinned upstream plus existing patches, and preserve submodule HEAD.
