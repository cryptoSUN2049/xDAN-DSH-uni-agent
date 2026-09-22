# Lessons

- User selected VERL for editable algorithm internals. Do not continue Tinker deployment because its offline implementation already exists.
- MOPD is a training recipe with data/routing/serving/gradient contracts. It is not a model-architecture change or merely a loss coefficient.
- Reuse configurable teacher_key with teacher_domain. Do not overwrite data_source when it also identifies dataset/reward/validation groups.
- Exact native loss matters: k1 current probabilities + detached advantage + PPO/dual clipping differs from Tinker rollout-fixed IS. Never imply numerical equivalence without matching these choices.

- One task is not necessarily one trajectory. Enforce one admitted chain for the first two-task/one-minibatch acceptance; never silently drop alternate chains.
- Native V1 overwrites optimizer horizon and forces checkpoint transport naive. Freeze zero-warmup constant LR across smoke resume; report actual runtime settings.
- Repository pre-commit pins Ruff0.12.2, but inherited files contain five UP038 violations there. Installed Ruff0.13.3 passes whole-tree lint and format; borrowed Tinker Ruff0.16.7 additionally formats Markdown. Record the actual tool version, not a misleading mixed gate.
