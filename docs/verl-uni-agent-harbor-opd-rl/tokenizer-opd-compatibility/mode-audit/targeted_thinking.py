"""Separate 2048-token diagnostic; never overwrites the original 1024-token gate."""

import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    assert args.out.resolve() != args.source.parent.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = json.loads(args.source.read_text())
    row = next(r for r in rows if r["domain"] == "single_thinking_true")
    prompt = row["ids"][: row["prompt_length"]]
    assert len(prompt) + 2048 <= 4095
    import torch
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    path = "/workspace/models/Qwen3.5-9B"
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(
        path, dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa", local_files_only=True
    ).eval()
    eos = model.generation_config.eos_token_id
    eos_ids = eos if isinstance(eos, list) else [eos]
    torch.manual_seed(20260924)
    inputs = torch.tensor([prompt], device="cuda")
    with torch.inference_mode():
        result = model.generate(
            input_ids=inputs,
            attention_mask=torch.ones_like(inputs),
            do_sample=False,
            max_new_tokens=2048,
            pad_token_id=tokenizer.pad_token_id,
        )[0].tolist()
    assert result[: len(prompt)] == prompt
    continuation = result[len(prompt) :]
    response = tokenizer.decode(continuation, skip_special_tokens=False)
    sample = {
        **row,
        "ids": result,
        "response": response,
        "response_tokens": len(continuation),
        "generation_budget": 2048,
        "thinking_close_observed": "</think>" in response,
        "eos_reached": continuation[-1] in eos_ids,
        "budget_exhausted": len(continuation) == 2048 and continuation[-1] not in eos_ids,
        "generation_eos_ids": eos_ids,
        "tokenizer_eos_id": tokenizer.eos_token_id,
        "last_token_id": continuation[-1],
        "last_token_text": tokenizer.decode([continuation[-1]]),
        "prefix_1024_exactly_reproduced": result[: len(row["ids"])] == row["ids"],
        "scope": "Separate 2048-token diagnostic; original 1024-token acceptance failure remains unchanged",
    }
    (args.out / "samples.json").write_text(json.dumps([sample], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in sample.items() if k not in {"ids", "response"}}, indent=2), flush=True)


if __name__ == "__main__":
    main()
