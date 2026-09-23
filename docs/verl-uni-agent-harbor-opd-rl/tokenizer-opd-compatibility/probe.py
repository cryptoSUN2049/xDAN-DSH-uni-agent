"""Bounded, read-only model compatibility experiment; writes only evidence."""

import argparse
import gc
import hashlib
import json
from pathlib import Path


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["cpu", "hf", "vllm"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = ["Qwen3.5-9B", "Qwen3.8-27B"]
    paths = [Path("/workspace/models") / n for n in names]
    if args.mode == "cpu":
        from transformers import AutoTokenizer

        ts = [AutoTokenizer.from_pretrained(p, local_files_only=True) for p in paths]
        cases = {
            "english": "Explain why 17 is prime.",
            "chinese": "计算三十七乘以二十三，并检查结果。",
            "code": "def f(x):\n    return x ** 2\nprint(f(7))",
            "thinking": "<think>先检查条件。\n17 has no divisors.</think>\n\n17 is prime.",
            "tool": "<tool_call>\n<function=exec>\n<parameter=cmd>\npwd\n</parameter>\n</function>\n</tool_call>",
            "unicode": "𝑥² ≥ 0; café; 👩‍💻; \t\n汉字",
            "audio": "<|audio_start|><|audio_pad|><|audio_end|>",
        }
        records = []
        for name, text in cases.items():
            ids = [t.encode(text, add_special_tokens=False) for t in ts]
            records.append(
                {
                    "name": name,
                    "ids_equal": ids[0] == ids[1],
                    "ids": ids,
                    "roundtrip": [t.decode(x) == text for t, x in zip(ts, ids, strict=True)],
                }
            )
        conversations = {
            "single": [{"role": "user", "content": "What is 17 times 23?"}],
            "history": [
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4", "reasoning_content": "Add two and two."},
                {"role": "user", "content": "Now multiply it by 3."},
            ],
            "inline_think": [
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "<think>Add two and two.</think>4"},
                {"role": "user", "content": "Why?"},
            ],
        }
        templates = []
        for name, messages in conversations.items():
            for thinking in [False, True]:
                rendered = [
                    t.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=True, enable_thinking=thinking
                    )
                    for t in ts
                ]
                templates.append(
                    {
                        "case": name,
                        "thinking": thinking,
                        "equal": rendered[0] == rendered[1],
                        "rendered": rendered,
                        "student_render_cross_encoding_equal": ts[0].encode(rendered[0]) == ts[1].encode(rendered[0]),
                    }
                )
        vocab = [t.get_vocab() for t in ts]
        mismatches = [(k, v, vocab[1][k]) for k, v in vocab[0].items() if k in vocab[1] and vocab[1][k] != v]
        manifest = {
            n: {
                f: hashlib.sha256((p / f).read_bytes()).hexdigest()
                for f in ["config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja"]
            }
            for n, p in zip(names, paths, strict=True)
        }
        save(
            out / "cpu.json",
            {
                "files": manifest,
                "tokenizer_classes": [type(t).__name__ for t in ts],
                "vocab_lengths": [len(v) for v in vocab],
                "shared_vocab_id_mismatches": mismatches,
                "only_teacher_tokens": sorted(set(vocab[1]) - set(vocab[0])),
                "encoding": records,
                "templates": templates,
            },
        )
        print("CPU_DONE", flush=True)
        return
    if args.mode == "hf":
        import torch
        from transformers import AutoModelForImageTextToText, AutoTokenizer

        torch.manual_seed(42)
        tokenizer = AutoTokenizer.from_pretrained(paths[0], local_files_only=True)
        print("LOAD_STUDENT", flush=True)
        model = AutoModelForImageTextToText.from_pretrained(
            paths[0], torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="eager", local_files_only=True
        ).eval()
        samples = []
        for prompt in [
            "What is 17 times 23? Answer briefly.",
            "请用一句话解释为什么天空是蓝色的。",
            "Write a Python function that returns the square of an integer.",
        ]:
            ids = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                enable_thinking=False,
                add_generation_prompt=True,
                return_tensors="pt",
            ).to("cuda")
            if not isinstance(ids, torch.Tensor):
                ids = ids["input_ids"]
            with torch.inference_mode():
                generated = model.generate(
                    input_ids=ids,
                    attention_mask=torch.ones_like(ids),
                    do_sample=False,
                    max_new_tokens=64,
                    pad_token_id=tokenizer.pad_token_id,
                )
            seq = generated[0].tolist()
            samples.append(
                {
                    "prompt": prompt,
                    "prompt_length": ids.shape[1],
                    "ids": seq,
                    "response": tokenizer.decode(seq[ids.shape[1] :]),
                    "ended": seq[-1] == tokenizer.eos_token_id,
                }
            )
        save(out / "student.json", samples)
        del model, ids, generated
        gc.collect()
        torch.cuda.empty_cache()
        print("LOAD_TEACHER", flush=True)
        model = AutoModelForImageTextToText.from_pretrained(
            paths[1], torch_dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="eager", local_files_only=True
        ).eval()
        scores = []
        for row in samples:
            ids = torch.tensor([row["ids"]], device="cuda")
            with torch.inference_mode():
                logits = (
                    model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False).logits[0, :-1].float()
                )
                lp = logits.log_softmax(-1).gather(-1, ids[0, 1:, None]).squeeze(-1)
                top = logits.topk(32, dim=-1).indices
                scores.append(
                    {
                        "logprobs": lp.cpu().tolist(),
                        "finite": bool(torch.isfinite(lp).all()),
                        "teacher_extra_top32_positions": int(((top >= 248070) & (top <= 248076)).any(-1).sum()),
                    }
                )
        save(out / "hf.json", scores)
        print("HF_DONE", flush=True)
        return
    from vllm import LLM, SamplingParams

    samples = json.loads((out / "student.json").read_text())
    llm = LLM(
        model=str(paths[1]),
        dtype="bfloat16",
        tensor_parallel_size=1,
        gpu_memory_utilization=0.75,
        max_model_len=1024,
        max_num_seqs=1,
        enforce_eager=True,
        enable_prefix_caching=False,
        max_num_batched_tokens=1024,
    )
    results = llm.generate(
        [{"prompt_token_ids": r["ids"]} for r in samples],
        SamplingParams(max_tokens=1, temperature=1.0, prompt_logprobs=0),
    )
    scores = []
    for row, result in zip(samples, results, strict=True):
        assert result.prompt_token_ids == row["ids"]
        values = [result.prompt_logprobs[i][token].logprob for i, token in enumerate(row["ids"]) if i > 0]
        scores.append({"logprobs": values, "token_ids_verified": True})
    save(out / "vllm.json", scores)
    print("VLLM_DONE", flush=True)


if __name__ == "__main__":
    main()
