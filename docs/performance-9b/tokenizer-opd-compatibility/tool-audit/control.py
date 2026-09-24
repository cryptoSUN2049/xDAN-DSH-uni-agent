"""CPU control: production ToolAgentLoop handlers, scripted generation only."""

import argparse
import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ["CUDA_VISIBLE_DEVICES"] = ""

from transformers import AutoTokenizer

from verl.experimental.agent_loop.tool_agent_loop import AgentData, AgentState, ToolAgentLoop
from verl.experimental.agent_loop.tool_parser import ToolParser
from verl.tools.function_tool import FunctionTool
from verl.tools.schemas import OpenAIFunctionToolSchema
from verl.utils.tokenizer.continuous_token import QwenContinuousTokenBuilder
from verl.workers.rollout.replica import TokenOutput


class ScriptedServer:
    def __init__(self, tokenizer, texts):
        self.outputs = [tokenizer.encode(t, add_special_tokens=False) for t in texts]

    async def generate(self, **kwargs):
        ids = self.outputs.pop(0)
        return TokenOutput(token_ids=ids, log_probs=[-0.25] * len(ids))


async def case(tokenizer, mode, side="right"):
    def local_add(a, b):
        if mode == "exception":
            raise ValueError("controlled local exception")
        return str(a + b) if mode != "truncate" else "0123456789" * 10

    schema = OpenAIFunctionToolSchema.model_validate(
        {
            "type": "function",
            "function": {
                "name": "local_add",
                "description": "Local sum",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            },
        }
    )
    # Bypass service/resource initialization only. All executed handlers and CT
    # merge/mask implementations below are unmodified production methods.
    obj = object.__new__(ToolAgentLoop)
    obj.loop = asyncio.get_running_loop()
    obj.tokenizer = tokenizer
    obj.processor = None
    obj.continuous_token_builder = QwenContinuousTokenBuilder(
        tokenizer, chat_template_kwargs={"enable_thinking": False}
    )
    obj.tools = {"local_add": FunctionTool("local_add", local_add, schema)}
    obj.tool_schemas = [schema.model_dump(exclude_none=True)]
    obj.tool_parser = ToolParser.get_tool_parser("hermes", tokenizer)
    obj.max_assistant_turns = 3
    obj.max_user_turns = 3
    obj.max_parallel_calls = 1
    obj.response_length = 2048
    obj.max_tool_response_length = 12 if mode == "truncate" else 128
    obj.tool_response_truncate_side = side
    obj.rollout_config = SimpleNamespace(prompt_length=2048)
    obj.server_manager = ScriptedServer(
        tokenizer,
        [
            '<tool_call>\n{"name": "local_add", "arguments": {"a": 2, "b": 3}}\n</tool_call><|im_end|>',
            "The result is 5.<|im_end|>",
        ],
    )
    data = AgentData(
        [{"role": "user", "content": "Use local_add to add 2 and 3."}], None, None, None, None, {}, "cpu-control", {}
    )
    assert await obj._handle_pending_state(data, {}) == AgentState.GENERATING
    initial = len(data.prompt_ids)
    assert await obj._handle_generating_state(data, {}) == AgentState.PROCESSING_TOOLS
    first_n = len(data.response_mask)
    assert first_n > 0 and data.response_mask == [1] * first_n
    assert await obj._handle_processing_tools_state(data) == AgentState.GENERATING
    context_end = len(data.response_mask)
    assert context_end > first_n
    assert data.response_mask[:first_n] == [1] * first_n
    assert data.response_mask[first_n:] == [0] * (context_end - first_n)
    assert data.response_logprobs[first_n:] == [0.0] * (context_end - first_n)
    tool_text = data.messages[-1]["content"]
    if mode == "success":
        assert tool_text == "5"
    elif mode == "exception":
        assert "controlled local exception" in tool_text
    else:
        raw = "0123456789" * 10
        expected = {
            "right": raw[:12] + "...(truncated)",
            "left": "(truncated)..." + raw[-12:],
            "middle": raw[:6] + "...(truncated)..." + raw[-6:],
        }[side]
        assert tool_text == expected
    assert await obj._handle_generating_state(data, {}) == AgentState.TERMINATED
    assert data.response_mask[context_end:] and all(data.response_mask[context_end:])
    assert len(data.prompt_ids) - initial == len(data.response_mask) == len(data.response_logprobs)
    ids = data.prompt_ids[initial:]
    assert tokenizer.decode(ids[first_n:context_end]).find(tool_text) >= 0
    return {
        "case": mode,
        "truncate_side": side,
        "passed": True,
        "tool_text": tool_text,
        "initial_prompt_tokens": initial,
        "boundaries": [0, first_n, context_end, len(ids)],
        "response_ids": ids,
        "response_mask": data.response_mask,
        "response_logprobs": data.response_logprobs,
        "masked_context_text": tokenizer.decode(ids[first_n:context_end]),
    }


async def main(args):
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    results = [await case(tokenizer, "success"), await case(tokenizer, "exception")]
    results.extend([await case(tokenizer, "truncate", side) for side in ["left", "right", "middle"]])
    sources = {}
    for cls in [
        ToolAgentLoop,
        QwenContinuousTokenBuilder,
        ToolAgentLoop.ct_merge_context_msg,
        ToolParser,
        FunctionTool,
    ]:
        path = Path(inspect.getfile(cls))
        sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    output = {
        "passed": True,
        "scope": ("CPU handler/mask control; scripted assistant tokens; no actual model generation or teacher scoring"),
        "source_sha256": sources,
        "cases": results,
    }
    Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(json.dumps({"passed": True, "cases": len(results), "output": args.output}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(main(parser.parse_args()))
