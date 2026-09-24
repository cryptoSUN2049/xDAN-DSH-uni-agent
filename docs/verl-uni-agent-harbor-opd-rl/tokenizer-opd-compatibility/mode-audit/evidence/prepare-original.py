"""CPU mode renders controls; generate mode records genuine student continuations.

Neither mode executes a tool or proves tool-rollout response masks.
"""

import argparse
import hashlib
import json
from pathlib import Path


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def cases():
    simple = [{"role": "user", "content": "What is 17 times 23? Check your calculation and answer briefly."}]
    history = [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4", "reasoning_content": "Adding two and two gives four."},
        {"role": "user", "content": "Multiply that result by 3. Answer briefly."},
    ]
    inline = [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "<think>Adding two and two gives four.</think>4"},
        {"role": "user", "content": "Multiply that result by 3. Answer briefly."},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "add",
                "description": "Add two integers",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            },
        }
    ]
    tool_history = [
        {"role": "user", "content": "Use add to calculate 19+23, then report its result."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_control",
                    "type": "function",
                    "function": {
                        "name": "add",
                        "arguments": {"a": 19, "b": 23},
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_control", "name": "add", "content": "42"},
    ]
    result = []
    for name, messages in [
        ("single", simple),
        ("history_reasoning_field", history),
        ("history_inline_thinking", inline),
        ("tool_history_control", tool_history),
    ]:
        for thinking in [False, True]:
            result.append(
                {
                    "domain": f"{name}_thinking_{str(thinking).lower()}",
                    "messages": messages,
                    "thinking": thinking,
                    "tools": tools if name.startswith("tool") else None,
                    "tool_execution_verified": False,
                }
            )
    result.append(
        {
            "domain": "long_prompt_thinking_false",
            "messages": [{"role": "user", "content": ""}],
            "thinking": False,
            "tools": None,
            "long_prompt": True,
            "tool_execution_verified": False,
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "generate"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--student", default="/workspace/models/Qwen3.5-9B")
    parser.add_argument("--teacher", default="/workspace/models/Qwen3.8-27B")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--max-context", type=int, default=4096)
    args = parser.parse_args()
    if not 1 <= args.max_new_tokens <= 1024 or args.max_context != 4096:
        raise ValueError("Bounded audit: 1..1024 response tokens; context exactly 4096")
    from transformers import AutoTokenizer

    student = AutoTokenizer.from_pretrained(args.student, local_files_only=True)
    teacher = AutoTokenizer.from_pretrained(args.teacher, local_files_only=True)
    args.out.mkdir(parents=True, exist_ok=True)
    prepared, evidence = [], []
    for case in cases():
        if case.get("long_prompt"):
            # Build semantically whole repeated context, no arbitrary token slicing.
            text = "Reference record: alpha = 17; beta = 23.\n"
            count = 1
            target = min(3000, args.max_context - args.max_new_tokens - 128)
            while len(student.encode(text * (count + 1), add_special_tokens=False)) < target:
                count += 1
            case["messages"][0]["content"] = text * count + "What is alpha times beta? Answer briefly."
        options = {"enable_thinking": case["thinking"], "add_generation_prompt": True, "tokenize": False}
        if case["tools"]:
            options["tools"] = case["tools"]
        rendered = [t.apply_chat_template(case["messages"], **options) for t in [student, teacher]]
        ids = student.encode(rendered[0], add_special_tokens=False)
        cross_equal = ids == teacher.encode(rendered[0], add_special_tokens=False)
        if not cross_equal:
            raise ValueError(f"Cross-tokenizer coordinate mismatch: {case['domain']}")
        if len(ids) + args.max_new_tokens + 1 > args.max_context:
            raise ValueError("Context budget exceeded")
        evidence.append(
            {
                **case,
                "student_template": rendered[0],
                "teacher_template": rendered[1],
                "native_templates_equal": rendered[0] == rendered[1],
                "student_render_cross_tokenizer_equal": cross_equal,
                "prompt_length": len(ids),
            }
        )
        prepared.append(
            {
                "domain": case["domain"],
                "prompt_length": len(ids),
                "ids": ids,
                "thinking": case["thinking"],
                "cross_tokenizer_equal": cross_equal,
                "tool_execution_verified": False,
                "tool_rollout_mask_verified": False,
                "prompt_sha256": hashlib.sha256(rendered[0].encode()).hexdigest(),
            }
        )
    write(args.out / "templates.json", evidence)
    if args.mode == "prepare":
        for row in prepared:
            response = "Check: 17*20 + 17*3 = 391. Final answer: 391."
            if row["thinking"]:
                response += "</think>\n\n391"
            row["ids"] += student.encode(response, add_special_tokens=False) + [student.eos_token_id]
            row["scope"] = "synthetic coordinate/EOS control only; not genuine student trajectory"
        write(args.out / "samples.json", prepared)
        return
    import torch
    from transformers import AutoModelForImageTextToText

    torch.manual_seed(20260924)
    model = AutoModelForImageTextToText.from_pretrained(
        args.student, dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa", local_files_only=True
    ).eval()
    samples = []
    for row in prepared:
        inputs = torch.tensor([row["ids"]], device="cuda")
        with torch.inference_mode():
            generated = model.generate(
                input_ids=inputs,
                attention_mask=torch.ones_like(inputs),
                do_sample=False,
                max_new_tokens=args.max_new_tokens,
                pad_token_id=student.pad_token_id,
            )
        raw_ids = generated[0].tolist()
        assert raw_ids[: row["prompt_length"]] == row["ids"]
        continuation = raw_ids[row["prompt_length"] :]
        response = student.decode(continuation, skip_special_tokens=False)
        samples.append(
            {
                **row,
                "ids": raw_ids,
                "response": response,
                "response_tokens": len(continuation),
                "scope": "HF student actual generation raw token IDs, student template; constructed history",
                "generation_budget": args.max_new_tokens,
                "eos_reached": continuation[-1] == student.eos_token_id,
                "thinking_close_observed": "</think>" in response if row["thinking"] else None,
                "budget_exhausted": len(continuation) == args.max_new_tokens
                and continuation[-1] != student.eos_token_id,
            }
        )
        write(args.out / "samples.json", samples)
        print(row["domain"], len(continuation), samples[-1]["eos_reached"], flush=True)
    write(
        args.out / "generation-complete.json",
        {
            "samples": len(samples),
            "expected": len(prepared),
            "passed": len(samples) == len(prepared),
            "mode": "HF actual generation",
        },
    )


if __name__ == "__main__":
    main()
