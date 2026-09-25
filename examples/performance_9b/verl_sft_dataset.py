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

    def _build_messages(self, example: dict):
        example = dict(example)
        example[self.messages_key] = self._decode(example[self.messages_key], list)
        if self.tools_key in example and example[self.tools_key] is not None:
            example[self.tools_key] = self._decode(example[self.tools_key], list)
        return super()._build_messages(example)

    def _process_single_message(self, index, message, full_message, tools=None, enable_thinking=None):
        """Tokenize a cumulative prefix so Qwen templates see system+user context."""
        processor = self.processor if self.processor is not None else self.tokenizer

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
            if isinstance(encoded, dict):
                encoded = encoded["input_ids"]
            if hasattr(encoded, "tolist"):
                encoded = encoded.tolist()
            if encoded and isinstance(encoded[0], list):
                encoded = encoded[0]
            return encoded

        before = render(full_message[:index], generation=True)
        after = render(full_message[: index + 1], generation=False)
        if len(after) < len(before) or after[: len(before)] != before:
            raise ValueError("chat template prefix is not token-prefix stable")
        token_ids = after[len(before) :]
        input_ids = torch.tensor(token_ids, dtype=torch.long)
        attention_mask = torch.ones_like(input_ids)
        loss_mask = torch.ones_like(input_ids) if message.get("role") == "assistant" else torch.zeros_like(input_ids)
        return input_ids, loss_mask, attention_mask, {}

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
