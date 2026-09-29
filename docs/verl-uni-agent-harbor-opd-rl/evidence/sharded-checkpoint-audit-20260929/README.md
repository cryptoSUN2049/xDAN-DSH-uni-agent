# CPU fixture validation, not training acceptance

On 2026-09-29 16:39 UTC, the fixed cloud Python environment passed 14 focused tests in 41.54 seconds. Real Gloo world-size-two processes generated, saved and reloaded native ShardedTensor fixtures. Combined parent/child branch coverage is 88.58% (statements 89.39%, branches 85%).

`status.json` binds source/test/log/report hashes. The checker SHA is `ee49a0f89a5ac651ea59bcd4d5f09ff97c0f40f04a0aac4b3275b3bdbc163715`; the existing optimizer checker remains unchanged. `red.log` preserves the initial missing-module failure, and `green-v2.log` is the final 14-test run. `coverage.json` includes spawned worker coverage.

The four native fixture reports demonstrate: unchanged base with nonzero adapter update passes; base modification, NaN, and all-zero C1 optimizer moments each fail. Other cases reject missing ranks, incomplete/overlapping/out-of-bounds coverage, replicated-value disagreement and changed dtype/shape. A float32 nextafter delta invisible after bfloat16 casting is correctly detected. Existing output files are preserved.

These are deliberately tiny synthetic fixtures. No R14 checkpoint, GPU, model training, checkpoint restoration, or task learning is claimed. The audit used its own CPU process groups and left no owned audit Python process running. No packages were installed and the shared environment was unchanged.
