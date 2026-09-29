# Native two-GPU NCCL preflight

2026-09-29 10:50:51 UTC: two cases passed, zero skipped/errors/failures. Each case transferred three changing tensor sets between two Ray actors on distinct physical GPUs. Cases cover persistent and rebuilt NCCL groups; tensors include float32, bfloat16, int64 and a tensor larger than the 64 KiB transport bucket. Every received tensor matched exactly.

The operator is `docs/verl-uni-agent-harbor-opd-rl/mimo_nccl_probe.py`, SHA256 `8e08725e2bcf96110c71120334dc606a9644433b530996cee9c2be2d84787322`. It exercised the frozen native `verl/checkpoint_engine/nccl_checkpoint_engine.py`, SHA256 `e32bfa5d650d86016e8e38307c7b26eb81e818bc1e809202dd62a55bd6cb22a6`. Source is unchanged between r9 and proposed r10. The probe exited and a subsequent `nvidia-smi --query-compute-apps` returned no GPU processes.

Artifacts are unmodified cloud copies:

- `status.json`: native test report; SHA256 `1674b5d84b7266ce890b28b04998d5024cd9055ec31d96e3f8cfe7d647e705cf`.
- `nccl-r10.log`: raw operator/Ray output.
- `manifest.json`: isolated CuPy installation, wheel provenance and 2,432 installed file hashes; SHA256 `ef5fb1393db7aa8ee8d80fb2e2d4484650790adb15cd527e8778845aeb281967`.

The fixed base Python environment was not modified. Only `cupy-cuda13x==14.0.1` was installed with `uv pip install --target .../env-overlays/r10-cupy/packages --no-deps --no-index <verified-wheel>`. Base NumPy 2.3.5, cuda-pathfinder 1.8.1 and NCCL 2.28.9 satisfied runtime requirements. No CUDA extras or fastrlock were added. CuPy's [official installation source](https://github.com/cupy/cupy/blob/main/docs/source/install.rst), retrieved through Context7, specifies `cupy-cuda13x` for CUDA 13.

The manifest records the exact `PYTHONPATH` and `LD_LIBRARY_PATH` prefixes. Set `PYTHONDONTWRITEBYTECODE=1`, expose `CUDA_VISIBLE_DEVICES=0,1`, and clear `RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES`. Invoke the fixed Python with the probe, `--source <frozen-source>/verl`, `--overlay <overlay-root>`, a new `--output` directory and a dedicated local `--ray-temp` directory. The observed run had a 900-second external timeout and needed no model weights.

This proves native NCCL transport compatibility and tensor integrity. It does not prove vLLM model loading, merged-LoRA semantics, checkpoint restoration, gateway policy versions or effective RL updates. The values 2/3/4 identify changing test tensors; the NCCL backend does not itself serialize these values as policy-version evidence. Those remain separate r10 training acceptance checks.
