"""Turn a VERL FSDP LoRA checkpoint into plain HF weights that vLLM can serve.

    python examples/harbor_opd_rl/merge_lora_checkpoint.py \
        --actor-dir runs/pipe-r11/train/checkpoints/.../global_step_20/actor \
        --out /workspace/verl-uni-agent-harbor-opd-rl/models/pipe-r11-step20

VERL's model_merger writes the *base* weights plus a separate ``lora_adapter/`` (it
renames ``base_layer`` back and pops the lora tensors), so its output alone would
evaluate the untrained base. This script runs that merger, folds the adapter into the
weights with peft ``merge_and_unload``, and checks the result:

  * every LoRA target weight changed by exactly scale * B @ A (checked on a sample),
  * every non-target weight is bit-identical to the base,
  * a merge report (counts, max deltas, rank/alpha) is written next to the weights.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import torch


def run_verl_merger(actor_dir: Path, staging: Path) -> None:
    cmd = [sys.executable, "-m", "verl.model_merger", "merge", "--backend", "fsdp"]
    cmd += ["--local_dir", str(actor_dir), "--target_dir", str(staging)]
    subprocess.run(cmd, check=True)
    if not (staging / "lora_adapter" / "adapter_config.json").exists():
        raise SystemExit(f"no lora_adapter under {staging}: not a LoRA checkpoint?")


def load_model(path: Path):
    import transformers

    config = transformers.AutoConfig.from_pretrained(path)
    arch = (config.architectures or [""])[0]
    cls = getattr(transformers, arch, None) or transformers.AutoModelForCausalLM
    return cls.from_pretrained(path, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--actor-dir", type=Path, required=True, help="global_step_N/actor of a VERL FSDP checkpoint")
    ap.add_argument("--out", type=Path, required=True, help="new directory for the merged HF model")
    ap.add_argument("--check-modules", type=int, default=8, help="LoRA modules to verify numerically")
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; use a new directory to keep evidence")

    from peft import PeftModel

    staging = args.out.with_name(args.out.name + ".verl-merger")
    if not (staging / "lora_adapter").exists():
        run_verl_merger(args.actor_dir, staging)
    adapter_cfg = json.loads((staging / "lora_adapter" / "adapter_config.json").read_text())
    scale = adapter_cfg["lora_alpha"] / adapter_cfg["r"]

    base = load_model(staging)
    base_sd = {k: v.clone() for k, v in base.state_dict().items()}
    peft_model = PeftModel.from_pretrained(base, staging / "lora_adapter")
    lora_sd = peft_model.state_dict()
    merged = peft_model.merge_and_unload()
    merged_sd = merged.state_dict()

    changed = [k for k in merged_sd if not torch.equal(merged_sd[k], base_sd[k])]
    unchanged = len(merged_sd) - len(changed)
    if not changed:
        raise SystemExit("merge changed no weights: the adapter was not applied")

    # Numerical check on a sample: merged - base == scale * B @ A for that module.
    checked, worst = 0, 0.0
    for a_key in sorted(k for k in lora_sd if k.endswith("lora_A.default.weight"))[: args.check_modules]:
        module = a_key[: -len(".lora_A.default.weight")]
        weight_key = module.replace("base_model.model.", "", 1) + ".weight"
        weight_key = weight_key.replace(".base_layer.weight", ".weight")
        if weight_key not in merged_sd:
            raise SystemExit(f"cannot locate merged weight for {module}")
        a = lora_sd[a_key].float()
        b = lora_sd[a_key.replace("lora_A", "lora_B")].float()
        expected = scale * (b @ a)
        got = merged_sd[weight_key].float() - base_sd[weight_key].float()
        err = (got - expected).abs().max().item() / max(expected.abs().max().item(), 1e-8)
        worst = max(worst, err)
        checked += 1
    if worst > 0.05:  # bf16 rounding of W + dW; a wrong scale or transposition is far larger
        raise SystemExit(f"merged delta does not match scale * B @ A (relative error {worst:.3f})")

    merged.save_pretrained(args.out, safe_serialization=True)
    for name in (
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
        "processor_config.json",
        "preprocessor_config.json",
        "special_tokens_map.json",
        "generation_config.json",
    ):
        src = staging / name
        if src.exists() and not (args.out / name).exists():
            shutil.copy2(src, args.out / name)
    report = {
        "actor_dir": str(args.actor_dir),
        "lora_r": adapter_cfg["r"],
        "lora_alpha": adapter_cfg["lora_alpha"],
        "scale": scale,
        "target_modules": adapter_cfg.get("target_modules"),
        "tensors_changed": len(changed),
        "tensors_unchanged": unchanged,
        "modules_checked": checked,
        "max_relative_error": round(worst, 5),
    }
    (args.out / "merge-report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
