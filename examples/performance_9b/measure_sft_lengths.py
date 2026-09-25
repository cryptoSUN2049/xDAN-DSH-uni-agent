"""Measure token-length tails with the exact tokenizer/chat template used by VERL SFT.

This is intentionally a preflight tool: it does not truncate or sample the data.
It renders every row in a Parquet split and records the untruncated token count so
the single-GPU context ceiling can be chosen from observed tails rather than a
nominal model limit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from transformers import AutoTokenizer


def decode(value, expected):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, expected):
        raise TypeError(f"expected {expected.__name__}, got {type(value).__name__}")
    return value


def token_ids(encoded):
    if isinstance(encoded, dict) or hasattr(encoded, "get"):
        encoded = encoded["input_ids"]
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    while encoded and isinstance(encoded[0], list):
        encoded = encoded[0]
    return list(encoded)


def render_length(tokenizer, row, messages_key, tools_key, thinking_key):
    messages = decode(row[messages_key], list)
    tools = decode(row[tools_key], list) if tools_key and row.get(tools_key) is not None else None
    kwargs = {}
    if thinking_key and thinking_key in row and not pd.isna(row[thinking_key]):
        kwargs["enable_thinking"] = bool(row[thinking_key])
    rendered = tokenizer.apply_chat_template(
        messages,
        tools=tools,
        add_generation_prompt=False,
        tokenize=True,
        **kwargs,
    )
    return len(token_ids(rendered)), len(messages), bool(tools)


def describe(values: list[int], thresholds: list[int]) -> dict:
    array = np.asarray(values, dtype=np.int64)
    quantiles = {f"p{q}": float(np.percentile(array, q)) for q in (50, 75, 90, 95, 99, 99.5, 99.9)}
    counts = {f"over_{limit}": int((array > limit).sum()) for limit in thresholds}
    return {
        "rows": int(array.size),
        "min": int(array.min()),
        "max": int(array.max()),
        "mean": float(array.mean()),
        "quantiles": quantiles,
        "threshold_counts": counts,
    }


def measure_split(tokenizer, path: Path, split: str, messages_key: str, tools_key: str, thinking_key: str):
    frame = pd.read_parquet(path)
    rows = []
    lengths = []
    for index, row in frame.iterrows():
        length, turns, has_tools = render_length(tokenizer, row, messages_key, tools_key, thinking_key)
        lengths.append(length)
        rows.append(
            {
                "split": split,
                "row_index": int(index),
                "token_length": length,
                "turns": turns,
                "has_tools": has_tools,
            }
        )
    return frame, rows, lengths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Tokenizer/model directory")
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--messages-key", default="messages")
    parser.add_argument("--tools-key", default="tools")
    parser.add_argument("--thinking-key", default="enable_thinking")
    parser.add_argument("--thresholds", default="32768,49152,65536")
    args = parser.parse_args()

    thresholds = [int(item) for item in args.thresholds.split(",") if item]
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=False)
    args.output.mkdir(parents=True, exist_ok=True)

    all_rows = []
    split_summary = {}
    for split, path in (("train", args.train), ("validation", args.validation)):
        _, rows, lengths = measure_split(tokenizer, path, split, args.messages_key, args.tools_key, args.thinking_key)
        all_rows.extend(rows)
        split_summary[split] = describe(lengths, thresholds)

    all_lengths = [row["token_length"] for row in all_rows]
    summary = {
        "model": str(args.model),
        "tokenizer_class": tokenizer.__class__.__name__,
        "thresholds": thresholds,
        "splits": split_summary,
        "all": describe(all_lengths, thresholds),
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    pd.DataFrame(all_rows).to_csv(args.output / "row_lengths.csv", index=False)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
