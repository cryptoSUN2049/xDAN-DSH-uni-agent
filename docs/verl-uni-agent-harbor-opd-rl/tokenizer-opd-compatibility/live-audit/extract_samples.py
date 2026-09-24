"""Extract exact live IDs and historical scoring tensors, without retokenization."""

import argparse
import hashlib
import json
from pathlib import Path

import torch
from replay import dense, flat, nested, response_slice


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--train-jsonl", type=Path)
    parser.add_argument("--tokenizer")
    args = parser.parse_args()
    samples = []
    for file in sorted(args.directory.glob("micro-*.pt")):
        payload = torch.load(file, map_location="cpu", weights_only=False)
        data = payload["data"]
        prompts, responses = data["prompts"], data["responses"]
        masks = dense(data["response_mask"]).bool()
        teacher = response_slice(flat(data["teacher_logprobs"]), data).squeeze(-1)
        teacher_ids = response_slice(flat(data["teacher_ids"]), data).squeeze(-1)
        student = response_slice(flat(payload["model_log_probs"]), data)
        old = dense(data["old_log_probs"])
        count = len(prompts["rows"]) if nested(prompts) else len(prompts)
        for i in range(count):
            if nested(prompts):
                p, r = prompts["rows"][i], responses["rows"][i]
            else:
                attention = data["attention_mask"][i].bool()
                boundary = prompts.shape[1]
                p = prompts[i][attention[:boundary]]
                r = responses[i][attention[boundary:]]
            n = len(r)
            row = {
                "sample_index": len(samples),
                "domain": "unmapped",
                "source_capture": file.name,
                "microbatch_row": i,
                "source_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                "scope": "exact raw IDs captured at actual native distillation_loss boundary; not re-encoded text",
                "prompt_length": len(p),
                "ids": torch.cat([p, r]).tolist(),
                "prompt_ids": p.tolist(),
                "response_ids": r.tolist(),
                "response_mask": masks[i, :n].tolist(),
                "live_teacher_ids": teacher_ids[i, :n].tolist(),
                "live_teacher_logprobs": teacher[i, :n].tolist(),
                "live_student_logprobs": student[i, :n].tolist(),
                "live_old_log_probs": old[i, :n].tolist(),
                "actor_temperature": str(data.get("temperature", "absent")),
                "teacher_temperature": "confirm from actual launch config; do not infer from actor",
            }
            assert all(
                teacher_id == response_id
                for teacher_id, response_id, valid in zip(
                    row["live_teacher_ids"], row["response_ids"], row["response_mask"], strict=True
                )
                if valid
            )
            samples.append(row)
    assert samples, "No actual live captures"
    if args.train_jsonl and args.tokenizer:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
        lookup = {}
        for line in args.train_jsonl.read_text().splitlines():
            source = json.loads(line)
            prompt = tokenizer.apply_chat_template(
                source["prompt"],
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
                return_dict=False,
            )
            lookup.setdefault(tuple(prompt), []).append(source["extra_info"])
        for sample in samples:
            matches = lookup.get(tuple(sample["prompt_ids"]), [])
            sample["source_mapping"] = "exact original prompt IDs" if len(matches) == 1 else "unmapped/ambiguous"
            if len(matches) == 1:
                sample["domain"] = matches[0]["domain"]
                sample["sample_id"] = matches[0]["sample_id"]
                sample["source_metadata"] = matches[0]

    for sample in samples:
        sample["training_domain"] = sample["domain"]
        sample["domain"] = f"live_{sample['sample_index']:02d}_{sample['training_domain']}"
        sample["case_id"] = sample["domain"]
    output = args.directory / "real-capture-samples.json"
    output.write_text(json.dumps(samples, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {"samples": len(samples), "tokens": sum(len(s["response_ids"]) for s in samples), "file": str(output)}
        )
    )


if __name__ == "__main__":
    main()
