"""One real DSH decision per SFT row, with only its target assistant supervised.

Source/provenance acceptance belongs to prepare_sft_dataset. This dataset validates
rendering and loss boundaries; learner token IDs are not behavior-policy tokens.
"""

import copy
import json
from pathlib import Path

import pyarrow.parquet as pq
import torch
from torch.utils.data import Dataset

from verl.utils.tokenizer import normalize_token_ids
from verl.utils.tokenizer.chat_template import apply_chat_template


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(raw):
    _require(isinstance(raw, str), "decision JSON must be a string")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _message(message, *, target=False):
    _require(isinstance(message, dict), "message must be an object")
    role = message.get("role")
    _require(role in {"system", "user", "assistant", "tool"}, "unsupported message role")
    _require(not target or role == "assistant", "target must be assistant")
    content = message.get("content")
    _require(content is None or isinstance(content, str), "only normalized text messages supported")
    calls = message.get("tool_calls") or []
    _require(isinstance(calls, list) and (not calls or role == "assistant"), "invalid tool calls")
    for call in calls:
        _require(isinstance(call, dict) and call.get("type") == "function", "function tool call required")
        function = call.get("function")
        _require(
            isinstance(function, dict) and isinstance(function.get("name"), str) and function["name"],
            "tool function name missing",
        )
        _require(isinstance(function.get("arguments"), dict), "tool arguments must be normalized JSON objects")
    if target:
        _require(bool(content and content.strip()) or bool(calls), "empty assistant target")
        _require(not content or "<tool_call>" not in content, "raw tool-call markup cannot replace structured calls")


class DshDecisionSFTDataset(Dataset):
    def __init__(self, parquet_files, tokenizer, config, processor=None, max_samples=-1):
        config = config or {}
        _require(processor is None, "text-only dataset requires processor=None")
        _require(config.get("pad_mode", "no_padding") == "no_padding", "use native no_padding collator")
        _require(config.get("truncation", "error") == "error", "truncation is forbidden")
        template_kwargs = dict(config.get("apply_chat_template_kwargs") or {})
        _require(
            not template_kwargs or template_kwargs == {"enable_thinking": False},
            "only explicit enable_thinking=False template option is supported",
        )
        self.max_length = config.get("max_length", 32768)
        _require(type(self.max_length) is int and self.max_length > 0, "max_length must be positive integer")
        _require(type(max_samples) is int and (max_samples == -1 or max_samples > 0), "invalid max_samples")
        self.tokenizer = tokenizer
        files = [parquet_files] if isinstance(parquet_files, str | Path) else list(parquet_files)
        self.rows = [row for path in files for row in pq.read_table(path).to_pylist()]
        if max_samples > 0:
            self.rows = self.rows[:max_samples]
        _require(bool(self.rows), "empty decision dataset")
        ids = [row.get("sample_id") for row in self.rows]
        _require(
            all(isinstance(value, str) and value for value in ids) and len(set(ids)) == len(ids),
            "sample IDs must be nonempty and unique",
        )

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        _require(row.get("schema") == "dsh.t2-sft-decision.v1", "wrong decision schema")
        _require(row.get("enable_thinking") is False, "enable_thinking must be false")
        request, target = _json(row.get("request_json")), _json(row.get("target_json"))
        _require(isinstance(request, dict) and set(request) == {"messages", "tools"}, "invalid request fields")
        messages, tools = request["messages"], request["tools"]
        _require(isinstance(messages, list) and bool(messages), "request history must be nonempty")
        _require(tools is None or isinstance(tools, list), "tools must be array or null")
        for message in messages:
            _message(message)
        _message(target, target=True)
        full = [*messages, target]

        def render(history, generation, tokenize):
            return apply_chat_template(
                self.tokenizer,
                messages=copy.deepcopy(history),
                tools=copy.deepcopy(tools),
                add_generation_prompt=generation,
                tokenize=tokenize,
                enable_thinking=False,
            )

        prompt_text, full_text = render(messages, True, False), render(full, False, False)
        _require(
            isinstance(prompt_text, str) and isinstance(full_text, str) and full_text.startswith(prompt_text),
            "chat-template text prefix mismatch; inspect Qwen thinking/template boundary",
        )
        prompt_ids = normalize_token_ids(render(messages, True, True))
        full_ids = normalize_token_ids(render(full, False, True))
        _require(
            prompt_ids and len(full_ids) > len(prompt_ids) and full_ids[: len(prompt_ids)] == prompt_ids,
            "chat-template token prefix mismatch; no boundary repair permitted",
        )
        _require(len(full_ids) <= self.max_length, "decision exceeds max_length; truncation forbidden")
        vocabulary_size = len(self.tokenizer)
        _require(
            all(type(value) is int and 0 <= value < vocabulary_size for value in full_ids),
            "token outside tokenizer vocabulary",
        )
        eos, eos_id = self.tokenizer.eos_token, self.tokenizer.eos_token_id
        suffix = full_text[len(prompt_text) :]
        _require(
            isinstance(eos, str) and eos and type(eos_id) is int and suffix.rstrip().endswith(eos),
            "target lacks template EOS boundary",
        )
        _require(bool(suffix.rstrip()[: -len(eos)].strip()), "target rendered to empty content")
        target_ids = full_ids[len(prompt_ids) :]
        _require(eos_id in target_ids, "target lacks EOS token")
        eos_position = max(i for i, value in enumerate(target_ids) if value == eos_id)
        tail = self.tokenizer.decode(
            target_ids[eos_position + 1 :], skip_special_tokens=False, clean_up_tokenization_spaces=False
        )
        _require(not tail.strip(), "unexpected tokens after target EOS")
        return dict(
            input_ids=torch.tensor(full_ids, dtype=torch.long),
            position_ids=torch.arange(len(full_ids), dtype=torch.long),
            loss_mask=torch.tensor([0] * len(prompt_ids) + [1] * len(target_ids), dtype=torch.long),
        )
