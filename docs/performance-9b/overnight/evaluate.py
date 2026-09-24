"""Same-template, same-budget standalone evaluation of base or LoRA models."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path

from reward import grade


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--model-id", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--adapter")
    p.add_argument("--tokenizer", default="/workspace/models/Qwen3.5-9B")
    p.add_argument("--max-tokens", type=int, default=2048)
    args = p.parse_args()
    import pyarrow.parquet as pq
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    data = pq.read_table(args.data).to_pylist()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    prompts = [
        tokenizer.apply_chat_template(
            row["prompt"], tokenize=True, return_dict=False, add_generation_prompt=True, enable_thinking=False
        )
        for row in data
    ]
    options = dict(
        model=args.model,
        tokenizer=args.tokenizer,
        dtype="bfloat16",
        tensor_parallel_size=1,
        gpu_memory_utilization=0.75,
        max_model_len=max(4096, args.max_tokens + 2048),
        max_num_seqs=4,
        max_num_batched_tokens=4096,
        enforce_eager=True,
        enable_prefix_caching=False,
    )
    if args.adapter:
        options.update(enable_lora=True, max_lora_rank=16)
    llm = LLM(**options)
    adapter = LoRARequest(args.model_id, 1, args.adapter) if args.adapter else None
    outputs = llm.generate(
        [{"prompt_token_ids": x} for x in prompts],
        SamplingParams(temperature=0, max_tokens=args.max_tokens, seed=20260924),
        lora_request=adapter,
    )
    records = []
    for row, result in zip(data, outputs, strict=True):
        response = result.outputs[0]
        score = grade(row["data_source"], response.text, row["reward_model"]["ground_truth"], row["extra_info"])
        records.append(
            {
                "domain": row["data_source"],
                "extra_info": row["extra_info"],
                "prompt": row["prompt"],
                "output": response.text,
                "output_tokens": len(response.token_ids),
                "finish_reason": response.finish_reason,
                "truncated": response.finish_reason == "length",
                **score,
            }
        )
    (dest / "outputs.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    domains = []
    for domain in sorted({r["domain"] for r in records}):
        rows = [r for r in records if r["domain"] == domain]
        scored = [r for r in rows if r["score"] is not None]
        domains.append(
            {
                "domain": domain,
                "count": len(rows),
                "scored": len(scored),
                "skipped": len(rows) - len(scored),
                "infra": 0,
                "score": statistics.mean(r["score"] for r in scored) if scored else None,
                "output_tokens_mean": statistics.mean(r["output_tokens"] for r in rows),
                "truncated_count": sum(r["truncated"] for r in rows),
                "truncated_rate": statistics.mean(r["truncated"] for r in rows),
                "verifiers": sorted({r["verifier"] for r in rows}),
                "python_syntax_valid": sum(r.get("python_syntax_valid", False) for r in rows)
                if domain == "code"
                else None,
            }
        )
    report = {
        "model": args.model_id,
        "model_path": args.model,
        "adapter_path": args.adapter,
        "adapter_reload_verified": bool(args.adapter),
        "adapter_weights_sha256": hashlib.sha256(
            (Path(args.adapter) / "adapter_model.safetensors").read_bytes()
        ).hexdigest()
        if args.adapter
        else None,
        "status": "complete",
        "dataset_revision": hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),
        "budget": {
            "max_tokens": args.max_tokens,
            "temperature": 0,
            "seed": 20260924,
            "template": "student tokenizer; enable_thinking=False; no tools",
        },
        "domains": domains,
        "overall": {
            "count": len(records),
            "scored": sum(d["scored"] for d in domains),
            "skipped": sum(d["skipped"] for d in domains),
            "infra": 0,
            "score": None,
            "reason": "No aggregate accuracy across heterogeneous graders / unscored domains",
        },
        "limitations": [
            "Small internal validation, not official benchmark.",
            "Code syntax is not execution correctness; chat is unscored.",
            "Teacher uses student template for controlled comparison; not native-template upper bound.",
        ],
    }
    (dest / "eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        json.dumps({"model": args.model_id, "count": len(records), "domains": domains}, ensure_ascii=False), flush=True
    )


if __name__ == "__main__":
    main()
