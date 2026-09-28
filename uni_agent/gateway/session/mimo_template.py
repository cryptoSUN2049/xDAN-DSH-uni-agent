"""Compatibility for the frozen MiMo Distill Qwen 9B template, not generic Qwen."""

import hashlib
import re

MIMO_TEMPLATE_SHA256 = "59a64ebb4df6d1489d09a91267cf3ceb106162d4a893c4f84833cfb8c897ff63"


def is_mimo_template(processing_class, hf_model_type) -> bool:
    template = getattr(processing_class, "chat_template", None)
    return (
        hf_model_type == "qwen3_5"
        and isinstance(template, str)
        and hashlib.sha256(template.encode()).hexdigest() == MIMO_TEMPLATE_SHA256
    )


def split_mimo_reasoning(message: dict) -> dict:
    """Expose the template's reasoning field without changing generated tokens."""
    match = re.fullmatch(r"<think>(.*?)</think>(.*)", message.get("content", ""), flags=re.DOTALL)
    if match is None:
        return message
    return {**message, "reasoning_content": match.group(1), "content": match.group(2)}
