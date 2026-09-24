"""Run a Qwen3.5 chat-template rendering audit over provisional records."""

import argparse
import json
from pathlib import Path

try:
    from examples.performance_9b.qwen_chat_adapter import to_qwen_template_messages
except ModuleNotFoundError:  # detached Runpod audit directory
    from qwen_chat_adapter import to_qwen_template_messages


def audit(model, input_path, output_path):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
    ok = errors = tool_rows = 0
    lengths = []
    examples = []
    for line in Path(input_path).open():
        record = json.loads(line)
        try:
            messages, call_ids = to_qwen_template_messages(record["messages"])
            rendered = tokenizer.apply_chat_template(
                messages,
                tools=json.loads(record["tools_json"]),
                tokenize=True,
                add_generation_prompt=False,
            )
            token_ids = rendered["input_ids"] if isinstance(rendered, dict) else rendered
            if not token_ids:
                raise ValueError("missing input_ids")
            ok += 1
            if hasattr(token_ids, "ids"):
                length = len(token_ids.ids)
            elif token_ids and isinstance(token_ids[0], list):
                length = len(token_ids[0])
            elif token_ids and hasattr(token_ids[0], "ids"):
                length = len(token_ids[0].ids)
            else:
                length = len(token_ids)
            lengths.append(length)
            tool_rows += bool(call_ids)
        except Exception as exc:  # noqa: BLE001 - audit must retain bad-row examples
            errors += 1
            if len(examples) < 10:
                examples.append({"id": record.get("id"), "type": type(exc).__name__, "error": str(exc)[:300]})
    result = {
        "schema_version": "apus-sft-v1",
        "model": model,
        "scope": "all provisional candidates",
        "ok": ok,
        "errors": errors,
        "tool_rows": tool_rows,
        "token_min": min(lengths) if lengths else None,
        "token_p50": sorted(lengths)[len(lengths) // 2] if lengths else None,
        "token_max": max(lengths) if lengths else None,
        "error_examples": examples,
        "training_ready": False,
        "note": "Template rendering only; does not prove loss mask or semantic quality.",
    }
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.model, args.input, args.output)


if __name__ == "__main__":
    main()
