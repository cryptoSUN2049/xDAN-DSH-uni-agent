"""APUS JSON-column adapter for VERL's MultiTurnSFTDataset.

Parquet stores ``messages`` and ``tools`` as JSON strings because arbitrary
tool argument objects do not have one stable Arrow struct schema.  This class
decodes them before delegating tokenization and loss-mask construction to VERL.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import torch

from examples.performance_9b.verl_sft_mask import assistant_loss_mask
from verl.utils.dataset.dataset_utils import DatasetPadMode
from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset
from verl.utils.fs import copy_local_path_from_hdfs
from verl.utils.tokenizer.chat_template import extract_system_prompt_and_generation


class ApusMultiTurnSFTDataset(MultiTurnSFTDataset):
    """VERL dataset with deterministic decoding of APUS JSON columns."""

    @staticmethod
    def _decode(value, expected):
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, expected):
            raise ValueError(f"expected {expected.__name__}, got {type(value).__name__}")
        return value

    @staticmethod
    def _token_ids(value):
        if isinstance(value, dict) or hasattr(value, "get"):
            value = value["input_ids"]
        if hasattr(value, "ids"):
            return list(value.ids)
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, list):
            result = []
            for item in value:
                result.extend(ApusMultiTurnSFTDataset._token_ids(item))
            return result
        return [value]

    def _build_messages(self, example: dict):
        example = dict(example)
        example[self.messages_key] = self._decode(example[self.messages_key], list)
        if self.tools_key in example and example[self.tools_key] is not None:
            example[self.tools_key] = self._decode(example[self.tools_key], list)
        return super()._build_messages(example)

    def __getitem__(self, item):
        """Render one complete conversation and derive the assistant mask by offsets.

        Qwen3.5's template inspects the last user turn while rendering every
        assistant turn.  Rendering ``messages[:i]`` and ``messages[:i+1]``
        therefore cannot produce a token-prefix-stable stream for a genuine
        multi-turn trajectory.  The full-render path keeps the model's exact
        template output and marks only text between assistant headers and the
        following ``<|im_end|>`` marker.
        """
        row_dict = self.dataframe.iloc[item].to_dict()
        messages = self._build_messages(row_dict)
        tools = self.tools[item] if self.tools is not None else None
        enable_thinking = (
            self.enable_thinking[item] if self.enable_thinking is not None else self.enable_thinking_default
        )
        if enable_thinking is not None:
            enable_thinking = bool(enable_thinking)

        # Qwen3.5 exposes a vision processor even for text-only rows.  Calling
        # that processor positionally treats the rendered string as an image;
        # offsets for this text-only contract must come from the tokenizer.
        processor = self.tokenizer
        template_kwargs = dict(self.apply_chat_template_kwargs)
        if enable_thinking is not None:
            template_kwargs["enable_thinking"] = enable_thinking
        rendered = processor.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=False,
            tokenize=False,
            **template_kwargs,
        )
        if not isinstance(rendered, str):
            raise TypeError(f"chat template must return str, got {type(rendered).__name__}")

        encoded = processor(
            rendered,
            add_special_tokens=False,
            return_attention_mask=False,
            return_offsets_mapping=True,
        )
        token_ids = self._token_ids(encoded)
        offsets = encoded.get("offset_mapping") if hasattr(encoded, "get") else None
        if offsets is None:
            raise ValueError("tokenizer must provide offset_mapping for full-render SFT masking")
        if hasattr(offsets, "tolist"):
            offsets = offsets.tolist()
        if offsets and isinstance(offsets[0], list) and offsets[0] and isinstance(offsets[0][0], list):
            offsets = offsets[0]
        if len(token_ids) != len(offsets):
            raise ValueError(f"token/offset length mismatch: {len(token_ids)} != {len(offsets)}")

        loss_mask = torch.tensor(assistant_loss_mask(rendered, offsets), dtype=torch.long)

        input_ids = torch.tensor(token_ids, dtype=torch.long)
        attention_mask = torch.ones_like(input_ids)
        position_ids = torch.arange(input_ids.shape[0], dtype=torch.long)
        sequence_length = input_ids.shape[0]

        if self.pad_mode == DatasetPadMode.RIGHT:
            if sequence_length < self.max_length:
                pad_token_id = self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else 0
                pad_len = self.max_length - sequence_length
                input_ids = torch.cat((input_ids, torch.full((pad_len,), pad_token_id, dtype=input_ids.dtype)))
                attention_mask = torch.cat((attention_mask, torch.zeros(pad_len, dtype=attention_mask.dtype)))
                loss_mask = torch.cat((loss_mask, torch.zeros(pad_len, dtype=loss_mask.dtype)))
                position_ids = torch.nn.functional.pad(position_ids, (0, pad_len), value=0)
            elif sequence_length > self.max_length:
                if self.truncation == "left":
                    input_ids = input_ids[-self.max_length :]
                    attention_mask = attention_mask[-self.max_length :]
                    loss_mask = loss_mask[-self.max_length :]
                    position_ids = position_ids[-self.max_length :]
                elif self.truncation == "right":
                    input_ids = input_ids[: self.max_length]
                    attention_mask = attention_mask[: self.max_length]
                    loss_mask = loss_mask[: self.max_length]
                    position_ids = position_ids[: self.max_length]
                elif self.truncation == "error":
                    raise ValueError(f"{sequence_length=} larger than {self.max_length=}")
                else:
                    raise ValueError(f"Unknown truncation method {self.truncation}")
            return {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
                "loss_mask": loss_mask,
            }

        if self.pad_mode == DatasetPadMode.NO_PADDING:
            if sequence_length > self.max_length and self.truncation == "error":
                raise ValueError(f"{sequence_length=} larger than {self.max_length=}")
            if sequence_length > self.max_length:
                input_ids = input_ids[: self.max_length]
                loss_mask = loss_mask[: self.max_length]
                position_ids = position_ids[: self.max_length]
            return {"input_ids": input_ids, "position_ids": position_ids, "loss_mask": loss_mask}

        raise ValueError(f"Unknown pad mode {self.pad_mode}")

    def _process_single_message(self, index, message, full_message, tools=None, enable_thinking=None):
        """Tokenize a cumulative prefix so Qwen templates see system+user context."""
        processor = self.processor if self.processor is not None else self.tokenizer
        tools = self._active_tools if tools is None else tools

        def render(prefix, generation):
            if not prefix or all(item.get("role") == "system" for item in prefix):
                return []
            kwargs = dict(self.apply_chat_template_kwargs)
            if enable_thinking is not None:
                kwargs["enable_thinking"] = enable_thinking
            encoded = processor.apply_chat_template(
                prefix,
                tools=tools,
                add_generation_prompt=generation,
                tokenize=True,
                **kwargs,
            )
            if isinstance(encoded, dict) or hasattr(encoded, "get"):
                encoded = encoded["input_ids"]
            return self._token_ids(encoded)

        before = render(full_message[:index], generation=False)
        after = render(full_message[: index + 1], generation=False)
        if len(after) < len(before) or after[: len(before)] != before:
            raise ValueError("chat template prefix is not token-prefix stable")
        token_ids = after[len(before) :]
        input_ids = torch.tensor(token_ids, dtype=torch.long)
        attention_mask = torch.ones_like(input_ids)
        if message.get("role") == "assistant":
            generation_prefix = render(full_message[:index], generation=True)
            header_tokens = max(0, len(generation_prefix) - len(before))
            loss_mask = torch.ones_like(input_ids)
            loss_mask[: min(header_tokens, len(loss_mask))] = 0
        else:
            loss_mask = torch.zeros_like(input_ids)
        return input_ids, loss_mask, attention_mask, {}

    def sanity_check(self, input_ids, messages, tools, enable_thinking):
        """Validate cumulative tokenization against one full Qwen render."""
        processor = self.processor if self.processor is not None else self.tokenizer
        kwargs = dict(self.apply_chat_template_kwargs)
        if enable_thinking is not None:
            kwargs["enable_thinking"] = enable_thinking
        expected = processor.apply_chat_template(
            messages, tools=tools, add_generation_prompt=False, tokenize=True, **kwargs
        )
        expected_ids = torch.tensor(self._token_ids(expected), dtype=torch.long)
        if not torch.equal(input_ids.cpu(), expected_ids.cpu()):
            limit = min(input_ids.numel(), expected_ids.numel())
            mismatch = next((i for i in range(limit) if input_ids[i] != expected_ids[i]), limit)
            raise AssertionError(
                "APUS cumulative tokenization differs from full chat-template render: "
                f"actual={input_ids.numel()} expected={expected_ids.numel()} first_diff={mismatch} "
                f"actual_head={input_ids[:8].tolist()} expected_head={expected_ids[:8].tolist()}"
            )

    def _read_files_and_process(self):
        # VERL's default dtype_backend=pyarrow path can overflow on long JSON
        # strings when it samples an ArrowExtensionArray.  Read scalar columns
        # through ordinary pandas objects, then keep the upstream processing
        # contract used by __getitem__.
        dataframes = []
        for parquet_file in self.parquet_files:
            parquet_file = copy_local_path_from_hdfs(parquet_file, verbose=True)
            dataframes.append(pd.read_parquet(parquet_file))
        self.dataframe = pd.concat(dataframes, ignore_index=True)
        total = len(self.dataframe)
        if self.max_samples > 0 and self.max_samples < total:
            if self.shuffle:
                rng = np.random.default_rng(self.seed)
                indices = rng.choice(total, size=self.max_samples, replace=False)
            else:
                indices = np.arange(self.max_samples)
            self.dataframe = self.dataframe.iloc[indices.tolist()].reset_index(drop=True)
        self.messages = [self._decode(value, list) for value in self.dataframe[self.messages_key].tolist()]
        self.tools = (
            [self._decode(value, list) for value in self.dataframe[self.tools_key].tolist()]
            if self.tools_key in self.dataframe.columns
            else None
        )
        self.enable_thinking = (
            self.dataframe[self.enable_thinking_key].tolist()
            if self.enable_thinking_key in self.dataframe.columns
            else None
        )
        self.system_prompt, self.generation_prompt = extract_system_prompt_and_generation(
            self.tokenizer, **self.apply_chat_template_kwargs
        )
