"""CPU-only exact LoRA A/B module audit of exported safetensors."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import torch
from safetensors.torch import load_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("weights", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    weights = load_file(str(args.weights), device="cpu")
    rows = []
    for key, value in sorted(weights.items()):
        if ".lora_B." not in key:
            continue
        module = key.split(".lora_B.")[0]
        a_key = key.replace(".lora_B.", ".lora_A.")
        assert a_key in weights, f"Missing A pair: {key}"
        zero = bool(torch.count_nonzero(value) == 0)
        visual = ".visual." in module or ".vision_tower." in module or ".vision_model." in module
        language = ".language_model." in module or ".text_model." in module
        category = "vision" if visual else "text" if language else "unknown"
        rows.append(
            {
                "module": module,
                "category": category,
                "zero_B": zero,
                "shape_A": list(weights[a_key].shape),
                "shape_B": list(value.shape),
                "finite": bool(torch.isfinite(value).all() and torch.isfinite(weights[a_key]).all()),
                "nonzero_elements_B": int(torch.count_nonzero(value)),
            }
        )
    counts = Counter(f"{r['category']}_{'zero' if r['zero_B'] else 'nonzero'}" for r in rows)
    result = {
        "weights": str(args.weights),
        "weights_sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "total_tensors": len(weights),
        "paired_modules": len(rows),
        "counts": dict(counts),
        "all_zero_B_are_vision": all(r["category"] == "vision" for r in rows if r["zero_B"]),
        "all_text_B_updated": all(not r["zero_B"] for r in rows if r["category"] == "text"),
        "passed": len(weights) == 716
        and len(rows) == 358
        and counts == {"vision_zero": 110, "text_nonzero": 248}
        and all(r["finite"] for r in rows),
        "modules": rows,
    }
    args.out.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "modules"}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
