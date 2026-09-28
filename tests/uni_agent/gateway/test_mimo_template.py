import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment

from uni_agent.gateway.session.codec import MessageCodec

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
TEMPLATE = Path(__file__).parent / "fixtures/mimo-distill-qwen-9b.jinja"
TEMPLATE_SHA256 = "59a64ebb4df6d1489d09a91267cf3ceb106162d4a893c4f84833cfb8c897ff63"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
]


class TemplateTokenizer:
    chat_template = TEMPLATE.read_text()
    special = {"<|im_start|>": 1000000, "<|im_end|>": 1000001}
    eos_token_id = special["<|im_end|>"]

    def encode(self, text, add_special_tokens=False):
        for token, identity in self.special.items():
            text = text.replace(token, chr(identity))
        return [ord(char) for char in text]

    def decode(self, ids, skip_special_tokens=False):
        text = "".join(chr(identity) for identity in ids)
        for token, identity in self.special.items():
            text = text.replace(chr(identity), "" if skip_special_tokens else token)
        return text

    def convert_tokens_to_ids(self, token):
        return self.special.get(token)

    def apply_chat_template(self, messages, *, tokenize=True, add_generation_prompt=True, tools=None, **kwargs):
        environment = Environment()
        environment.filters["tojson"] = lambda value, **options: json.dumps(value, **options)
        source = self.chat_template.replace("{%- generation -%}", "").replace("{%- endgeneration -%}", "")
        text = environment.from_string(source).render(
            messages=messages,
            tools=tools,
            add_generation_prompt=add_generation_prompt,
            **kwargs,
        )
        return self.encode(text) if tokenize else text


@pytest.fixture(params=["fixture", "real", "real_processor"])
def tokenizer(request):
    if request.param == "fixture":
        return TemplateTokenizer(), None
    directory = os.environ.get("MIMO_TOKENIZER_DIR")
    if not directory:
        pytest.skip("Set MIMO_TOKENIZER_DIR for the real frozen-tokenizer CPU contract")
    from transformers import AutoProcessor, AutoTokenizer

    processor = (
        AutoProcessor.from_pretrained(directory, local_files_only=True) if request.param == "real_processor" else None
    )
    return AutoTokenizer.from_pretrained(directory, local_files_only=True), processor


@pytest.mark.asyncio
async def test_mimo_two_tool_turns_preserve_template_tokens_reasoning_and_masks(tokenizer, monkeypatch):
    tokenizer, processor = tokenizer
    assert hashlib.sha256(tokenizer.chat_template.encode()).hexdigest() == TEMPLATE_SHA256
    codec = MessageCodec(
        tokenizer, processor=processor, hf_model_type="qwen3_5", tool_parser_name="qwen3_coder", rollout_backend="vllm"
    )
    history = [{"role": "system", "content": "You are a coding agent."}, {"role": "user", "content": "Fix it."}]
    initial = codec.build_initial_tokens(history, tools=TOOLS)
    tokens, masks, probabilities = initial, [], []
    expected_masks, expected_probabilities = [], []
    for command, observation in [("pwd", "/testbed"), ("git status", "clean")]:
        if isinstance(tokenizer, TemplateTokenizer):

            async def extract(*args, command=command, **kwargs):
                return "<think>Inspect.</think>", [SimpleNamespace(name="bash", arguments={"command": command})]

            monkeypatch.setattr(codec, "_extract_tool_calls", extract)
        response = tokenizer.encode(
            "<think>Inspect.</think><tool_call><function=bash><parameter=command>"
            + command
            + "</parameter></function></tool_call><|im_end|>",
            add_special_tokens=False,
        )
        assistant, reason = await codec.decode_response(response, tools=TOOLS, stop_reason="stop")
        assert reason == "tool_calls"
        assert assistant["reasoning_content"] == "Inspect."
        assert assistant["content"] == ""
        assert assistant["tool_calls"][0]["function"]["arguments"] == {"command": command}
        response_logprobs = [-(index + 1) / 1000 for index in range(len(response))]
        tokens, masks, probabilities = codec.merge_assistant_tokens(
            tokens,
            response,
            masks,
            probabilities,
            assistant_logprobs=response_logprobs,
        )
        expected_masks += [1] * len(response)
        expected_probabilities += response_logprobs
        previous = history + [assistant]
        history = previous + [
            {"role": "tool", "tool_call_id": assistant["tool_calls"][0]["id"], "content": observation}
        ]
        tokens, masks, probabilities = codec.merge_context_tokens(
            previous,
            history,
            tokens,
            masks,
            probabilities,
            tools=TOOLS,
        )
        context_length = len(tokens) - len(initial) - len(expected_masks)
        expected_masks += [0] * context_length
        expected_probabilities += [0.0] * context_length
        assert tokens == codec.build_initial_tokens(history, tools=TOOLS)
        assert masks == expected_masks
        assert probabilities == expected_probabilities
    final, reason = await codec.decode_response(
        tokenizer.encode("<think>Done.</think>Fixed.<|im_end|>"), stop_reason="stop"
    )
    assert final == {"role": "assistant", "content": "Fixed.", "reasoning_content": "Done."}
    assert reason == "stop"


@pytest.mark.asyncio
async def test_mimo_length_does_not_admit_a_complete_tool_block(tokenizer):
    tokenizer, processor = tokenizer
    codec = MessageCodec(
        tokenizer, processor=processor, hf_model_type="qwen3_5", tool_parser_name="qwen3_coder", rollout_backend="vllm"
    )
    text = "<think>Inspect.</think><tool_call><function=bash><parameter=command>pwd</parameter></function></tool_call>"
    message, reason = await codec.decode_response(tokenizer.encode(text), tools=TOOLS, stop_reason="length")
    assert reason == "length" and "tool_calls" not in message


@pytest.mark.asyncio
async def test_other_qwen35_template_keeps_existing_builder_and_decode():
    tokenizer = TemplateTokenizer()
    tokenizer.chat_template += "{# different reviewed template #}"
    codec = MessageCodec(tokenizer, hf_model_type="qwen3_5")
    assert type(codec._continuous_token_builder).__name__ == "QwenContinuousTokenBuilder"
    message, _ = await codec.decode_response(tokenizer.encode("<think>Original.</think>Text"))
    assert message["content"] == "<think>Original.</think>Text" and "reasoning_content" not in message
