# Lessons

- User selected VERL for editable algorithm internals. Do not continue Tinker deployment because its offline implementation already exists.
- MOPD is a training recipe with data/routing/serving/gradient contracts. It is not a model-architecture change or merely a loss coefficient.
- Reuse configurable teacher_key with teacher_domain. Do not overwrite data_source when it also identifies dataset/reward/validation groups.
- Exact native loss matters: k1 current probabilities + detached advantage + PPO/dual clipping differs from Tinker rollout-fixed IS. Never imply numerical equivalence without matching these choices.
