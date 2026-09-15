"""Model-scoped codec for tokenizer, processor, tool-parser, and decode paths.

This layer stays within the model boundary: it applies chat templates, handles
processor-backed multimodal inputs, parses tools, and decodes backend outputs.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from uni_agent.gateway.utils import normalize_tool_arguments
from verl.utils.tokenizer import normalize_token_ids
from verl.utils.tokenizer.chat_template import apply_chat_template as _apply_chat_template
from verl.utils.tokenizer.chat_template import initialize_turn_separator
from verl.utils.tokenizer.continuous_token_wiring import create_continuous_token_builder

logger = logging.getLogger(__name__)

# Map backend stop_reason values into the gateway's internal finish_reason vocabulary.
_FINISH_REASON_MAP = {
    "completed": "stop",
    "stop": "stop",
    "matched_stop": "stop",
    "eos": "stop",
    "length": "length",
    "max_tokens": "length",
}

_SGLANG_TOOL_PARSER_ALIASES = {
    "qwen3_xml": "qwen3_coder",
}

_VLLM_TOOL_PARSER_ALIASES = {
    "qwen": "qwen3_xml",
    # Qwen2.5 and dense Qwen3-Instruct emit the Hermes-compatible JSON
    # <tool_call> envelope. The qwen3_xml parser expects the different
    # <function=> format used by Qwen3-Coder.
    "qwen25": "hermes",
    "qwen3": "hermes",
}

_HERMES_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_MAX_HERMES_RECOVERY_CLOSERS = 4


def _load_json_with_missing_closers(value: str) -> Any | None:
    """Parse one Hermes payload, allowing only missing terminal JSON closers."""
    text = value.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    expected: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{" or char == "[":
            expected.append("}" if char == "{" else "]")
        elif char == "}" or char == "]":
            if not expected or expected.pop() != char:
                return None
    if in_string or escaped or not expected or len(expected) > _MAX_HERMES_RECOVERY_CLOSERS:
        return None
    try:
        return json.loads(text + "".join(reversed(expected)))
    except json.JSONDecodeError:
        return None


def _recover_hermes_tool_calls(text: str) -> tuple[str, list[Any]] | None:
    """Recover complete Hermes calls when a final call lost JSON closers.

    vLLM's Hermes parser treats one malformed parallel call as an all-or-nothing
    response. The recovery is deliberately narrower: it accepts only complete
    ``<tool_call>`` blocks whose JSON becomes valid by appending terminal
    structural closers, and only ignores a malformed final block. Raw response
    tokens remain unchanged; this affects action decoding only.
    """
    matches = list(_HERMES_TOOL_CALL_PATTERN.finditer(text))
    if not matches:
        return None
    calls: list[Any] = []
    for index, match in enumerate(matches):
        value = _load_json_with_missing_closers(match.group(1))
        if not isinstance(value, dict):
            if index != len(matches) - 1:
                return None
            continue
        name = value.get("name")
        arguments = value.get("arguments")
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            if index != len(matches) - 1:
                return None
            continue
        calls.append(SimpleNamespace(name=name, arguments=json.dumps(arguments, ensure_ascii=False)))
    if not calls:
        return None
    return text[: matches[0].start()], calls


def _canonical_tools_hash(tools: list[dict[str, Any]]) -> str:
    """Return a stable hash for a tool schema independent of dict key order."""
    canonical = json.dumps(tools, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def initialize_generation_prompt(processing_class, **apply_chat_template_kwargs) -> list[int]:
    """Initialize the token suffix inserted by ``add_generation_prompt=True``."""
    without_generation_prompt = normalize_token_ids(
        _apply_chat_template(
            processing_class,
            [{"role": "user", "content": ""}],
            add_generation_prompt=False,
            **apply_chat_template_kwargs,
        )
    )
    with_generation_prompt = normalize_token_ids(
        _apply_chat_template(
            processing_class,
            [{"role": "user", "content": ""}],
            add_generation_prompt=True,
            **apply_chat_template_kwargs,
        )
    )
    if with_generation_prompt[: len(without_generation_prompt)] != without_generation_prompt:
        raise ValueError("Generation prompt is not a stable token suffix")
    return with_generation_prompt[len(without_generation_prompt) :]


class MessageCodec:
    """Model-scoped request codec used by gateway sessions.

    ``_GatewayActor`` owns one codec per actor and injects it into
    ``GatewaySession`` instances. The codec renders chat templates, handles
    multimodal processor inputs, and decodes backend token outputs without
    reading session state.
    """

    def __init__(
        self,
        tokenizer,
        *,
        processor=None,
        vision_info_extractor=None,
        vision_info_extractor_kwargs: dict[str, Any] | None = None,
        tool_parser_name: str | None = None,
        rollout_backend: str | None = None,
        enable_tool_parser_cache: bool = True,
        hf_model_type: str | None = None,
        apply_chat_template_kwargs: dict[str, Any] | None = None,
        mm_processor_kwargs: dict[str, Any] | None = None,
    ):
        self._tokenizer = tokenizer
        self._processor = processor
        self._vision_info_extractor = vision_info_extractor or self._default_vision_info_extractor
        self._vision_info_extractor_kwargs = dict(vision_info_extractor_kwargs or {})
        self._apply_chat_template_kwargs = dict(apply_chat_template_kwargs or {})
        self._mm_processor_kwargs = dict(mm_processor_kwargs or {})
        self._continuous_token_builder = create_continuous_token_builder(
            tokenizer,
            hf_model_type=hf_model_type,
            chat_template_kwargs=self._apply_chat_template_kwargs,
            mm_processor_kwargs=self._mm_processor_kwargs,
            processor=processor,
        )
        processing_class = self._processor if self._processor is not None else tokenizer
        if hasattr(processing_class, "chat_template") and processing_class.chat_template is None:
            self._generation_prompt = []
            self._turn_separator = []
        else:
            self._generation_prompt = initialize_generation_prompt(
                processing_class,
                **self._apply_chat_template_kwargs,
            )
            self._turn_separator = initialize_turn_separator(
                processing_class,
                **self._apply_chat_template_kwargs,
            )
        self._tool_parser_name = tool_parser_name
        self._rollout_backend = rollout_backend
        self._enable_tool_parser_cache = enable_tool_parser_cache
        # Backend parser construction performs expensive setup, so reuse parsers
        # within this actor-scoped codec. SGLang/vLLM bind tool schemas at
        # construction, while verl receives schemas per extraction call; this is
        # why their cache keys differ. Keep the cache codec-scoped because parser
        # instances may retain mutable request state and dynamic schemas can grow
        # the mapping over the codec lifetime. Callers can disable this
        # optimization for parser implementations that require request-scoped
        # instances.
        self._tool_parser_cache: dict[tuple[str, ...], Any] = {}

    @property
    def mm_processor_kwargs(self) -> dict[str, Any]:
        """Return processor kwargs shared by CT rendering and inference."""
        return dict(self._mm_processor_kwargs)

    @property
    def generation_prompt(self) -> list[int]:
        """Return the configured chat template's generation-prompt token suffix."""
        return list(self._generation_prompt)

    @property
    def turn_separator(self) -> list[int]:
        """Return the configured chat template's inter-turn separator tokens."""
        return list(self._turn_separator)

    async def _default_vision_info_extractor(
        self,
        messages: list[dict[str, Any]],
        *,
        image_patch_size: int,
        **_extra: Any,
    ) -> tuple[list[Any] | None, list[Any] | None]:
        # Lazy import so callers without multi-modal needs do not load
        # qwen_vl_utils. ``_extra`` absorbs ``vision_info_extractor_kwargs`` that
        # ``extract_multi_modal_data`` forwards for custom extractors; the
        # default path needs nothing beyond ``messages`` and patch size.
        from qwen_vl_utils import process_vision_info

        return process_vision_info(
            messages,
            image_patch_size=image_patch_size,
            return_video_metadata=True,
        )

    async def extract_multi_modal_data(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[Any] | None, list[Any] | None]:
        """Extract image and video inputs when a processor-backed request needs them."""
        if self._processor is None:
            return None, None

        has_multi_modal_blocks = False
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"image", "image_url", "video", "video_url"}:
                    has_multi_modal_blocks = True
                    break
            if has_multi_modal_blocks:
                break

        if not has_multi_modal_blocks:
            return None, None

        return await self._vision_info_extractor(
            messages,
            image_patch_size=self._processor.image_processor.patch_size,
            **self._vision_info_extractor_kwargs,
        )

    def build_initial_tokens(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        image_data: list[Any] | None = None,
        video_data: list[Any] | None = None,
    ) -> list[int]:
        """Build the initial runtime token stream."""
        return self._continuous_token_builder.build_initial_tokens(
            messages,
            tools=tools,
            images=image_data,
            videos=video_data,
        )

    def merge_assistant_tokens(
        self,
        runtime_token_ids: list[int],
        assistant_token_ids: list[int],
        response_mask: list[int],
        response_logprobs: list[float] | None = None,
        *,
        assistant_logprobs: list[float] | None = None,
    ) -> tuple[list[int], list[int], list[float] | None]:
        """Merge model-generated tokens and align response metadata."""
        merge_result = self._continuous_token_builder.merge_assistant_tokens(
            runtime_token_ids,
            assistant_token_ids,
        )
        response_mask, response_logprobs = self._continuous_token_builder.align_response_metadata(
            merge_result,
            response_mask,
            response_logprobs,
            assistant_logprobs=assistant_logprobs,
        )
        return merge_result.token_ids, response_mask, response_logprobs

    def merge_context_tokens(
        self,
        previous_messages: list[dict[str, Any]],
        updated_messages: list[dict[str, Any]],
        runtime_token_ids: list[int],
        response_mask: list[int],
        response_logprobs: list[float] | None = None,
        *,
        tools: list[dict[str, Any]] | None = None,
        image_data: list[Any] | None = None,
        video_data: list[Any] | None = None,
    ) -> tuple[list[int], list[int], list[float] | None]:
        """Merge appended context and align response metadata."""
        if image_data or video_data:
            raise ValueError(
                "Continuous Token context merging does not currently support incremental image or video data"
            )
        merge_result = self._continuous_token_builder.merge_context_tokens(
            previous_messages,
            updated_messages,
            runtime_token_ids,
            tools=tools,
        )
        response_mask, response_logprobs = self._continuous_token_builder.align_response_metadata(
            merge_result,
            response_mask,
            response_logprobs,
        )
        return merge_result.token_ids, response_mask, response_logprobs

    def _process_tool_calls_sglang(
        self,
        text: str,
        tools: list[dict[str, Any]],
        parser_name: str,
    ) -> tuple[str, list[Any]]:
        cache_key = ("sglang", parser_name, _canonical_tools_hash(tools))
        parser = self._tool_parser_cache.get(cache_key) if self._enable_tool_parser_cache else None
        if parser is None:
            from sglang.srt.entrypoints.openai.protocol import Function as SglFunction
            from sglang.srt.entrypoints.openai.protocol import Tool as SglTool
            from sglang.srt.function_call.function_call_parser import FunctionCallParser

            sglang_tools = [SglTool(type=tool["type"], function=SglFunction(**tool["function"])) for tool in tools]
            parser = FunctionCallParser(sglang_tools, parser_name)
            if self._enable_tool_parser_cache:
                self._tool_parser_cache[cache_key] = parser

        if not parser.has_tool_call(text):
            return text, []
        content, calls = parser.parse_non_stream(text)
        return content, [SimpleNamespace(name=call.name, arguments=call.parameters) for call in calls]

    def _process_tool_calls_vllm(
        self,
        text: str,
        tools: list[dict[str, Any]],
        parser_name: str,
    ) -> tuple[str, list[Any]]:
        from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionToolsParam

        cache_key = ("vllm", parser_name, _canonical_tools_hash(tools))
        parser = self._tool_parser_cache.get(cache_key) if self._enable_tool_parser_cache else None
        vllm_tools = [ChatCompletionToolsParam(**tool) if isinstance(tool, dict) else tool for tool in tools]
        if parser is None:
            from vllm.tool_parsers import ToolParserManager

            parser_cls = ToolParserManager.get_tool_parser(parser_name)
            parser_parameters = inspect.signature(parser_cls).parameters
            if "tools" in parser_parameters:
                parser = parser_cls(self._tokenizer, tools=vllm_tools)
            else:
                parser = parser_cls(self._tokenizer)
            if self._enable_tool_parser_cache:
                self._tool_parser_cache[cache_key] = parser

        request = SimpleNamespace(tools=vllm_tools, tool_choice="auto", skip_special_tokens=True)
        try:
            parsed = parser.extract_tool_calls(text, request)
        except Exception:
            recovered = _recover_hermes_tool_calls(text) if parser_name == "hermes" else None
            if recovered is not None:
                logger.warning(
                    "tool_parser_recovery backend=vllm parser=hermes recovered_calls=%s reason=exception",
                    len(recovered[1]),
                )
                return recovered
            raise
        if not parsed.tools_called:
            recovered = _recover_hermes_tool_calls(text) if parser_name == "hermes" else None
            if recovered is not None:
                logger.warning(
                    "tool_parser_recovery backend=vllm parser=hermes recovered_calls=%s reason=no_calls",
                    len(recovered[1]),
                )
                return recovered
            if parser_name == "hermes" and "<tool_call>" in text:
                logger.warning(
                    "tool_parser_rejection backend=vllm parser=hermes rejected_calls=%s",
                    text.count("<tool_call>"),
                )
            return text, []
        return parsed.content or "", [tool_call.function for tool_call in parsed.tool_calls]

    async def _process_tool_calls_verl(
        self,
        response_ids: list[int],
        tools: list[dict[str, Any]],
        parser_name: str,
    ) -> tuple[str, list[Any]]:
        """Parse tool calls with verl's built-in tool-parser registry."""
        from verl.experimental.agent_loop.tool_parser import ToolParser
        from verl.tools.schemas import OpenAIFunctionToolSchema

        cache_key = ("verl", parser_name)
        parser = self._tool_parser_cache.get(cache_key) if self._enable_tool_parser_cache else None
        if parser is None:
            parser = ToolParser.get_tool_parser(parser_name, self._tokenizer)
            if self._enable_tool_parser_cache:
                self._tool_parser_cache[cache_key] = parser

        tool_schemas = [OpenAIFunctionToolSchema.model_validate(tool) for tool in tools]
        content, calls = await parser.extract_tool_calls(response_ids, tool_schemas)
        return content, [SimpleNamespace(name=call.name, arguments=call.arguments) for call in calls]

    async def _extract_tool_calls(
        self,
        response_ids: list[int],
        tools: list[dict[str, Any]],
        parser_name: str,
    ) -> tuple[str, list[Any]]:
        text = self._tokenizer.decode(response_ids, skip_special_tokens=False)
        parser_backend = self._rollout_backend if self._rollout_backend in {"sglang", "vllm"} else "verl"
        if parser_backend == "sglang":
            effective_parser_name = _SGLANG_TOOL_PARSER_ALIASES.get(parser_name, parser_name)
        elif parser_backend == "vllm":
            effective_parser_name = _VLLM_TOOL_PARSER_ALIASES.get(parser_name, parser_name)
        else:
            effective_parser_name = parser_name
        logger.info(
            "tool_parser_attempt backend=%s parser=%s",
            parser_backend,
            effective_parser_name,
        )

        try:
            if parser_backend == "sglang":
                return self._process_tool_calls_sglang(text, tools, effective_parser_name)
            if parser_backend == "vllm":
                return self._process_tool_calls_vllm(text, tools, effective_parser_name)
            return await self._process_tool_calls_verl(response_ids, tools, effective_parser_name)
        except Exception as exc:
            rejected_calls = max(text.count("<tool_call>"), 1) if effective_parser_name == "hermes" else 1
            logger.warning(
                "tool_parser_rejection backend=%s parser=%s rejected_calls=%s",
                parser_backend,
                effective_parser_name,
                rejected_calls,
            )
            raise RuntimeError(f"{parser_backend} tool parser {parser_name!r} failed") from exc

    async def decode_response(
        self,
        response_ids: list[int],
        *,
        tools: list[dict[str, Any]] | None = None,
        stop_reason: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Decode model output tokens into an assistant message and finish reason."""
        # Terminal backend outcomes take precedence over syntactically complete
        # tool blocks: a truncated/aborted generation must not execute side effects.
        if stop_reason in {"abort", "aborted"}:
            raise HTTPException(status_code=409, detail="Backend generation was aborted; session cannot continue")
        if stop_reason in {"length", "max_tokens"}:
            return {
                "role": "assistant",
                "content": self._tokenizer.decode(response_ids, skip_special_tokens=True),
            }, "length"
        if self._tool_parser_name and tools:
            content, function_calls = await self._extract_tool_calls(
                response_ids,
                tools,
                self._tool_parser_name,
            )
            if function_calls:
                tool_calls = [
                    {
                        "id": f"call_{uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": normalize_tool_arguments(fc.arguments),
                        },
                    }
                    for fc in function_calls
                ]
                message = {
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": tool_calls,
                }
                return message, "tool_calls"
        response_text = self._tokenizer.decode(response_ids, skip_special_tokens=True)
        finish_reason = _FINISH_REASON_MAP.get(stop_reason, stop_reason) if stop_reason else "stop"
        return {"role": "assistant", "content": response_text}, finish_reason

    def canonicalize_message_for_prefix_comparison(self, message: dict[str, Any]) -> dict[str, Any]:
        """Canonicalize one message before session prefix comparison."""
        normalized = dict(message)
        normalized.pop("tool_call_id", None)
        tool_calls = normalized.get("tool_calls")
        if not isinstance(tool_calls, list):
            return normalized

        normalized_tool_calls: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            normalized_tool_call = dict(tool_call)
            normalized_tool_call.pop("id", None)
            normalized_tool_calls.append(normalized_tool_call)
        normalized["tool_calls"] = normalized_tool_calls
        return normalized
