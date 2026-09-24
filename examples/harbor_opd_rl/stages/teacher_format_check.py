"""Teacher format guard for OPD (docs/performance-9b/opd-then-rl-design.md section 4).

The Teacher scores the student's training sequence as it is: prompt logprobs over the exact
token ids the Gateway built. It judges the student in its own native format only when that
multi-turn token stream equals what the Teacher's chat template renders for the same
conversation. S1 (thinking off) was verified by hand on 2026-09-19; turning thinking on would
silently break it (Qwen3.8's native format adds a Reasoning effort line, and the Gateway never
re-renders history), and nothing else would notice.

The check replays a terminus-2-style conversation (user task, assistant JSON action, terminal
output, action, output; no system message, no tools) through the Gateway's own codec
(uni_agent.gateway.session.codec.MessageCodec, constructed as build_gateway_manager does): the
first prompt rendered once with the generation prompt, each assistant turn appended as the ids
of its content plus the end-of-turn token (what the rollout engine returns), each new user
message merged as a context append. It renders the same messages with the Teacher tokenizer's
chat template (same kwargs, add_generation_prompt=True) and compares the ids, and it checks that
both tokenizers encode a sample text identically. The Gateway stream is also compared with the
student's own template, only to show which side a divergence comes from.

Exit 0 when identical, 1 on a divergence (first index and decoded token windows printed), 2 when
the check cannot run. CPU only: loads tokenizers and configs, never weights.

    python examples/harbor_opd_rl/stages/teacher_format_check.py \\
      --student-model /tmp/models/Qwen3.5-9B --teacher-model /tmp/models/Qwen3.8-27B
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Must equal the ++data.apply_chat_template_kwargs.* overrides in train_tb21_lora_smoke.sh
# (tests/uni_agent/examples/test_harbor_teacher_format_check.py keeps them in step).
DEFAULT_CHAT_TEMPLATE_KWARGS: dict[str, Any] = {"enable_thinking": False}
# The token a Qwen ChatML model emits to end its turn; the rollout engine returns it as the last
# generated token, so the Gateway appends it with the assistant content.
END_OF_TURN_TOKEN = "<|im_end|>"
WINDOW = 8

_TASK = """You are an AI assistant tasked with solving command-line tasks in a Linux environment. \
You will be given a task description and the output from previously executed commands. \
Your goal is to solve the task by providing batches of shell commands.

Format your response as JSON with the following structure:

{
  "analysis": "Analyze the current state based on the terminal output provided.",
  "plan": "Describe your plan for the next steps.",
  "commands": [
    {
      "keystrokes": "ls -la\\n",
      "duration": 0.1
    }
  ],
  "task_complete": true
}

Task Description:
The unit test `tests/test_parser.py::test_empty_input` fails with `IndexError: list index out of range`.
Fix `src/parser.py` so that an empty input returns an empty list, without breaking other tests.

Current terminal state:
Current Terminal Screen:
root@8f2c1d:/app# """

_ACTION_1 = {
    "analysis": "Fresh shell in /app. I have not looked at the repository yet.",
    "plan": "List the files, then run the failing test to see the traceback.",
    "commands": [
        {"keystrokes": "ls -la src tests\n", "duration": 0.1},
        {"keystrokes": "python -m pytest -q tests/test_parser.py::test_empty_input 2>&1 | tail -15\n", "duration": 5.0},
    ],
    "task_complete": False,
}

_OUTPUT_1 = """New Terminal Output:

root@8f2c1d:/app# ls -la src tests
src:
total 16
drwxr-xr-x 2 root root 4096 Sep 19 04:10 .
-rw-r--r-- 1 root root  812 Sep 19 04:10 parser.py

tests:
total 12
-rw-r--r-- 1 root root  655 Sep 19 04:10 test_parser.py
root@8f2c1d:/app# python -m pytest -q tests/test_parser.py::test_empty_input 2>&1 | tail -15
    def parse(text):
        tokens = text.split()
>       head = tokens[0]
E       IndexError: list index out of range

src/parser.py:7: IndexError
1 failed in 0.04s
root@8f2c1d:/app# """

_ACTION_2 = {
    "analysis": "parse() reads tokens[0] before checking that the input has any tokens.",
    "plan": "Return [] early for an empty token list, then rerun the whole test file.",
    "commands": [
        {
            "keystrokes": (
                "sed -i 's/^    head = tokens\\[0\\]/    if not tokens:\\n        return []\\n&/' src/parser.py\n"
            ),
            "duration": 0.1,
        },
        {"keystrokes": "python -m pytest -q tests/test_parser.py\n", "duration": 5.0},
    ],
    "task_complete": False,
}

_OUTPUT_2 = """New Terminal Output:

root@8f2c1d:/app# python -m pytest -q tests/test_parser.py
....                                                                     [100%]
4 passed in 0.05s
root@8f2c1d:/app# """

# Code, JSON, shell output, whitespace runs, CJK and emoji: the pieces BPE merges differ on.
SAMPLE_TEXT = (
    'def main(argv: list[str]) -> int:\n    """Entry point."""\n\tif not argv:\n        return 2\n'
    '{"keystrokes": "grep -rn \\"TODO\\" src/ | wc -l\\n", "duration": 0.5}\n'
    "drwxr-xr-x   2 root root  4096 Sep 19 04:10 .\n\n\n"
    "中文分词、全角标点：测试。日本語テキスト。 emoji 🚀✅ café naïve  trailing spaces   \n"
)


def terminus2_conversation() -> list[dict[str, str]]:
    """User task, assistant action, terminal output, action, output: a terminus-2 episode's shape."""
    return [
        {"role": "user", "content": _TASK},
        {"role": "assistant", "content": json.dumps(_ACTION_1, indent=2)},
        {"role": "user", "content": _OUTPUT_1},
        {"role": "assistant", "content": json.dumps(_ACTION_2, indent=2)},
        {"role": "user", "content": _OUTPUT_2},
    ]


def token_id(tokenizer, token: str) -> int:
    """Id of a special token, refusing tokenizers that do not define it."""
    value = tokenizer.convert_tokens_to_ids(token)
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, int) or value < 0 or value == getattr(tokenizer, "unk_token_id", None):
        raise ValueError(f"tokenizer does not define {token!r} (got {value!r})")
    return value


def gateway_token_ids(codec, messages: list[dict[str, Any]], *, end_of_turn_id: int, encode) -> list[int]:
    """Token ids of ``messages`` as a Gateway session builds them (GatewaySession._prepare_generation_inputs
    and _run_generation): initial render once, generated ids appended, new messages merged as context."""
    if not messages or messages[0]["role"] != "user" or messages[-1]["role"] != "user":
        raise ValueError("the conversation must start and end with a user message")
    history = [messages[0]]
    runtime = list(codec.build_initial_tokens(history, tools=None))
    response_mask: list[int] = []
    for message in messages[1:]:
        if message["role"] == "assistant":
            generated = list(encode(message["content"])) + [end_of_turn_id]
            runtime, response_mask, _ = codec.merge_assistant_tokens(runtime, generated, response_mask)
            history = history + [message]
        else:
            updated = history + [message]
            runtime, response_mask, _ = codec.merge_context_tokens(history, updated, runtime, response_mask, tools=None)
            history = updated
    return list(runtime)


def template_token_ids(processing_class, messages: list[dict[str, Any]], chat_template_kwargs: dict[str, Any]):
    """Native render of ``messages`` with the generation prompt, through VERL's chat-template helper."""
    from verl.utils.tokenizer import normalize_token_ids
    from verl.utils.tokenizer.chat_template import apply_chat_template

    rendered = apply_chat_template(
        processing_class, messages, tokenize=True, add_generation_prompt=True, **chat_template_kwargs
    )
    return normalize_token_ids(rendered)


def first_divergence(left: list[int], right: list[int]) -> int | None:
    """First index where the two id lists differ (the shorter length for a strict prefix), None if equal."""
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def _window(tokenizer, ids: list[int], start: int, stop: int) -> list[str]:
    return [tokenizer.decode([token]) for token in ids[start:stop]]


def compare(left: tuple[str, Any, list[int]], right: tuple[str, Any, list[int]]) -> dict[str, Any]:
    """Compare two (label, tokenizer, ids) sides; on a divergence keep decoded windows around it."""
    (left_label, left_tok, left_ids), (right_label, right_tok, right_ids) = left, right
    index = first_divergence(left_ids, right_ids)
    result: dict[str, Any] = {
        "match": index is None,
        "lengths": {left_label: len(left_ids), right_label: len(right_ids)},
    }
    if index is not None:
        start = max(0, index - WINDOW)
        result.update(
            first_divergence=index,
            window_start=start,
            windows={
                left_label: _window(left_tok, left_ids, start, index + WINDOW),
                right_label: _window(right_tok, right_ids, start, index + WINDOW),
            },
        )
    return result


def run_check(
    codec,
    student_tokenizer,
    teacher_tokenizer,
    *,
    chat_template_kwargs: dict[str, Any],
    end_of_turn_token: str = END_OF_TURN_TOKEN,
    messages: list[dict[str, Any]] | None = None,
    sample_text: str = SAMPLE_TEXT,
) -> dict[str, Any]:
    """Gate: Gateway stream == Teacher-native render, and both tokenizers encode alike."""
    messages = messages or terminus2_conversation()
    gateway = gateway_token_ids(
        codec,
        messages,
        end_of_turn_id=token_id(student_tokenizer, end_of_turn_token),
        encode=lambda text: student_tokenizer.encode(text, add_special_tokens=False),
    )
    teacher = template_token_ids(teacher_tokenizer, messages, chat_template_kwargs)
    student = template_token_ids(student_tokenizer, messages, chat_template_kwargs)
    checks = {
        "gateway_vs_teacher": compare(("gateway", student_tokenizer, gateway), ("teacher", teacher_tokenizer, teacher)),
        "sample_text": compare(
            ("student", student_tokenizer, student_tokenizer.encode(sample_text, add_special_tokens=False)),
            ("teacher", teacher_tokenizer, teacher_tokenizer.encode(sample_text, add_special_tokens=False)),
        ),
        # Diagnostic only: tells a Gateway-concatenation difference from a template difference.
        "gateway_vs_student_template": compare(
            ("gateway", student_tokenizer, gateway), ("student", student_tokenizer, student)
        ),
    }
    return {
        "passed": checks["gateway_vs_teacher"]["match"] and checks["sample_text"]["match"],
        "chat_template_kwargs": dict(chat_template_kwargs),
        "end_of_turn_token": end_of_turn_token,
        "checks": checks,
    }


def format_report(result: dict[str, Any]) -> str:
    lines = [
        f"teacher format check: {'PASS' if result['passed'] else 'FAIL'} "
        f"(chat_template_kwargs={json.dumps(result['chat_template_kwargs'])})"
    ]
    for name, check in result["checks"].items():
        label = f"{name} (diagnostic)" if name == "gateway_vs_student_template" else name
        sizes = ", ".join(f"{side} {n} tokens" for side, n in check["lengths"].items())
        if check["match"]:
            lines.append(f"  {label}: identical ({sizes})")
            continue
        index, start = check["first_divergence"], check["window_start"]
        lines.append(f"  {label}: first divergence at token {index} ({sizes})")
        for side, window in check["windows"].items():
            shown = " ".join(f">>{piece!r}<<" if start + i == index else repr(piece) for i, piece in enumerate(window))
            lines.append(f"    {side:>8} [{start}:]: {shown}")
    return "\n".join(lines)


def load_student(model_dir: str, chat_template_kwargs: dict[str, Any]):
    """Student tokenizer and the Gateway codec, built from the same objects build_gateway_manager
    uses (HFModelConfig: tokenizer, multimodal processor, config.json model_type)."""
    from uni_agent.gateway.session.codec import MessageCodec
    from verl.workers.config import HFModelConfig

    model_config = HFModelConfig(path=model_dir, override_config={"attn_implementation": "sdpa"})
    codec = MessageCodec(
        tokenizer=model_config.tokenizer,
        processor=model_config.processor,
        hf_model_type=getattr(model_config.hf_config, "model_type", None),
        apply_chat_template_kwargs=dict(chat_template_kwargs),
    )
    return codec, model_config.tokenizer


def load_teacher_tokenizer(model_dir: str):
    from verl.utils.tokenizer import hf_tokenizer

    return hf_tokenizer(model_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--student-model", required=True, help="student model dir (the rollout model)")
    parser.add_argument("--teacher-model", required=True, help="Teacher model dir")
    parser.add_argument(
        "--chat-template-kwargs",
        default=json.dumps(DEFAULT_CHAT_TEMPLATE_KWARGS),
        help="JSON; must match the run's data.apply_chat_template_kwargs",
    )
    parser.add_argument("--end-of-turn-token", default=END_OF_TURN_TOKEN)
    parser.add_argument("--json", help="also write the full result here")
    args = parser.parse_args(argv)
    try:
        chat_template_kwargs = json.loads(args.chat_template_kwargs)
        codec, student_tokenizer = load_student(args.student_model, chat_template_kwargs)
        teacher_tokenizer = load_teacher_tokenizer(args.teacher_model)
        result = run_check(
            codec,
            student_tokenizer,
            teacher_tokenizer,
            chat_template_kwargs=chat_template_kwargs,
            end_of_turn_token=args.end_of_turn_token,
        )
    except Exception as exc:  # any failure to build either side means the format is unverified
        print(f"teacher format check could not run: {exc!r}", file=sys.stderr)
        return 2
    result.update(student_model=args.student_model, teacher_model=args.teacher_model)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(format_report(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
