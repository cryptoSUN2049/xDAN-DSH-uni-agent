# Short-course r1 evidence archive

The mother training run and both independent reload evaluations are preserved on the persistent cloud volume.

- Archive: `/workspace/reports/ws-short-r1-engineering-evidence-20260909.tar.gz`
- SHA256: `d7764c1422ce5a9f89df862a927059224ca5ede201fd2756a40468ef505d8823`
- Archive size: **18,197,593 bytes**.
- Manifest: `/workspace/reports/ws-short-r1-engineering-evidence-20260909.manifest.json`
- Manifest SHA256: `338c88daeee58b2734e40e8132740f0627acf52a5872e56e9ccced47dcdd9d4f`
- **173,735 source files**, **88,079,882 uncompressed bytes**; every archive member was read back and checked against its source hash and size. Embedded manifest was also verified.

Scope: `ws-short-train-r1`, `ws-short-reload-901-r1`, `ws-short-reload-902-r1`; each run and data directory, prepare/check/launch records, the three execution-checkout metrics JSONL files, and the offline audit overlay verification record. Run directories include the actual audit receipts and trajectories.

Three `training.env` files were excluded without reading. No checkpoint binaries or source checkout were included. Original run artifacts were unchanged. Archive and manifest permissions are 0600.

Execution source: `b47521df1d6cd6b930ab6ac85ef41c670f2405d2`. Independent audit source: `d4401d33c47af623d202a8b52be8266da5ec86f2`.

This is evidence preservation, not a complete standalone model backup: checkpoint files remain separately under `/workspace/uni-agent-g1/checkpoint/ws-short-train-r1/`. Their hashes are preserved in the run records. The archive does not establish capability improvement beyond the results documented in [reload results](work-state-short-reload-final-result.json).

