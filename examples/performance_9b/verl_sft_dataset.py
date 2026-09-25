"""APUS JSON-column adapter for VERL's MultiTurnSFTDataset.

Parquet stores ``messages`` and ``tools`` as JSON strings because arbitrary
tool argument objects do not have one stable Arrow struct schema.  This class
decodes them before delegating tokenization and loss-mask construction to VERL.
"""

from __future__ import annotations

import json

from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset


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
        # Let the upstream loader read scalar columns, then decode only the
        # columns used by __getitem__.  This avoids Arrow's nested conversion.
        super()._read_files_and_process()
        self.messages = [self._decode(value, list) for value in self.dataframe[self.messages_key].tolist()]
        if self.tools_key in self.dataframe.columns:
            self.tools = [self._decode(value, list) for value in self.dataframe[self.tools_key].tolist()]
