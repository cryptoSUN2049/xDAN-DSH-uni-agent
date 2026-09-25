"""Pure text-offset helpers for the APUS VERL SFT adapter."""

from __future__ import annotations

import re


def assistant_loss_mask(rendered: str, offsets: list[list[int] | tuple[int, int]]) -> list[int]:
    """Mark tokens whose character spans belong to assistant message bodies.

    The Qwen3.5 chat template emits explicit ``assistant`` and ``im_end``
    markers.  Matching character offsets on one complete render avoids the
    prefix-instability of rendering each message independently.
    """

    mask = [0] * len(offsets)
    for match in re.finditer(r"<\|im_start\|>assistant\n", rendered):
        body_start = match.end()
        body_end = rendered.find("<|im_end|>", body_start)
        if body_end < 0:
            raise ValueError("assistant block has no <|im_end|> marker")
        for token_index, offset in enumerate(offsets):
            if not offset or len(offset) != 2:
                continue
            start, end = offset
            if end > body_start and start < body_end:
                mask[token_index] = 1
    return mask
