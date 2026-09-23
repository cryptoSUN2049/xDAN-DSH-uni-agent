"""CPU-only adapter export using VERL's shard merger and LoRA serialization.

Never calls model.save_pretrained or instantiates/merges a full base model.
Only use with trusted checkpoints produced by this training job (torch pickle).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def validate_adapter(adapter: Path, metadata: dict) -> dict:
    import torch
    from safetensors.torch import load_file

    config = json.loads((adapter / "adapter_config.json").read_text())
    rank = int(config["r"])
    alpha = float(config["lora_alpha"])
    if rank != int(metadata["r"]) or alpha != float(metadata["lora_alpha"]) or rank <= 0 or alpha <= 0:
        raise ValueError("Adapter rank/alpha missing, invalid, or inconsistent with training metadata")
    if config.get("peft_type") != "LORA" or not config.get("target_modules"):
        raise ValueError("Missing PEFT LORA type/target_modules")
    weights = adapter / "adapter_model.safetensors"
    tensors = load_file(str(weights), device="cpu")
    a_names = [key for key in tensors if key.endswith(".lora_A.weight")]
    if not a_names or len(tensors) != len(a_names) * 2:
        raise ValueError("Expected complete paired LoRA A/B tensors only")
    updated_modules = 0
    for name in a_names:
        a = tensors[name]
        b = tensors[name.replace(".lora_A.weight", ".lora_B.weight")]
        if a.ndim != 2 or b.ndim != 2 or a.shape[0] != rank or b.shape[1] != rank:
            raise ValueError(f"Invalid rank/shape in {name}")
        if not torch.isfinite(a).all() or not torch.isfinite(b).all():
            raise ValueError(f"Nonfinite adapter weights: {name}")
        if torch.count_nonzero(a).item() == 0:
            raise ValueError(f"All-zero A tensor: {name}")
        # B is zero at initialization: nonzero B is essential, nonzero A alone proves nothing.
        if torch.count_nonzero(b).item():
            updated_modules += 1
    if not updated_modules:
        raise ValueError("Every B tensor is zero: no trained adapter update")
    return {
        "adapter": str(adapter.resolve()),
        "rank": rank,
        "alpha": alpha,
        "tensor_count": len(tensors),
        "modules": len(a_names),
        "modules_with_nonzero_B": updated_modules,
        "weights_sha256": digest(weights),
        "config_sha256": digest(adapter / "adapter_config.json"),
        "validation": "finite paired tensors; nonzero B; metadata matched",
        "generation_reload_verified": False,
    }


def export_one(actor: Path, target: Path, base_model: str) -> dict:
    from verl.model_merger.base_model_merger import ModelMergerConfig
    from verl.model_merger.fsdp_model_merger import FSDPModelMerger

    class AdapterOnlyMerger(FSDPModelMerger):
        def save_hf_model_and_tokenizer(self, state_dict):
            # Deliberately bypass upstream implementation which also saves base weights.
            if not state_dict or any("lora_" not in name for name in state_dict):
                raise ValueError("Expected LoRA-only checkpoint; refuse full-model export")
            if not self.save_lora_adapter(state_dict):
                raise ValueError("VERL merger produced no adapter")

    metadata_path = actor / "lora_train_meta.json"
    metadata = json.loads(metadata_path.read_text())
    shards = sorted(actor.glob("model_world_size_*_rank_*.pt"))
    if not shards:
        raise ValueError("No model shards; checkpoint may be incomplete")
    adapter = target / "lora_adapter"
    if not adapter.exists():
        config = ModelMergerConfig(
            operation="merge",
            backend="fsdp",
            local_dir=str(actor),
            target_dir=str(target),
            hf_model_config_path=str(actor / "huggingface"),
        )
        merger = AdapterOnlyMerger(config)
        merger.merge_and_save()
        merger.cleanup()
        config_path = adapter / "adapter_config.json"
        adapter_config = json.loads(config_path.read_text())
        adapter_config["base_model_name_or_path"] = base_model
        config_path.write_text(json.dumps(adapter_config, indent=2) + "\n")
    record = validate_adapter(adapter, metadata)
    record["source_actor"] = str(actor.resolve())
    record["source_metadata_sha256"] = digest(metadata_path)
    record["source_shards"] = [{"name": path.name, "sha256": digest(path)} for path in shards]
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-model", required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    actors = sorted(args.checkpoints.glob("global_step_*/actor"), key=lambda p: int(p.parent.name.split("_")[-1]))
    records = []
    for actor in actors:
        step = int(actor.parent.name.split("_")[-1])
        try:
            result = export_one(actor, args.out / actor.parent.name, args.base_model)
            records.append({"step": step, "status": "exported", **result})
        except Exception as exc:
            records.append({"step": step, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    manifest = {"format": "peft_adapter_only", "base_model": args.base_model, "checkpoints": records}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    if not records or any(row["status"] != "exported" for row in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
