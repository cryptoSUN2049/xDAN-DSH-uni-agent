"""APUS JSON-column adapter for VERL's MultiTurnSFTDataset.

Parquet stores ``messages`` and ``tools`` as JSON strings because arbitrary
tool argument objects do not have one stable Arrow struct schema.  This class
decodes them before delegating tokenization and loss-mask construction to VERL.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

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
