"""Teacher format guard (stages/teacher_format_check.py) replayed through the real Gateway codec.

The replay runs uni_agent's MessageCodec and VERL's Continuous Token builder with a small
character-level ChatML tokenizer. Without the GPU stack (a laptop), those modules are loaded past
the package __init__ files that import ray/torch, with a two-class transformers stub when
transformers is missing; the codec and builder code itself is the real one.
"""

import importlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_STUBBED_ROOTS = ("transformers", "verl", "uni_agent.gateway")


def _stub_package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _import_codec_module():
    """(codec module, whether stubs were installed)."""
    try:
        return importlib.import_module("uni_agent.gateway.session.codec"), False
    except ImportError:
        pass
    _stub_package("verl", ROOT / "verl/verl")
    _stub_package("verl.utils", ROOT / "verl/verl/utils")
    _stub_package("uni_agent.gateway", ROOT / "uni_agent/gateway")
    _stub_package("uni_agent.gateway.session", ROOT / "uni_agent/gateway/session")
    if importlib.util.find_spec("transformers") is None:
        stub = types.ModuleType("transformers")
        stub.PreTrainedTokenizerBase = type("PreTrainedTokenizerBase", (), {})
        stub.ProcessorMixin = type("ProcessorMixin", (), {})
        sys.modules["transformers"] = stub
    return importlib.import_module("uni_agent.gateway.session.codec"), True


@pytest.fixture(scope="module")
def gw():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    saved = dict(sys.modules)
    codec_module, stubbed = _import_codec_module()
    spec = importlib.util.spec_from_file_location(
        "teacher_format_check", ROOT / "examples/harbor_opd_rl/stages/teacher_format_check.py"
    )
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    yield types.SimpleNamespace(check=check, MessageCodec=codec_module.MessageCodec)
    if stubbed:  # leave no stub or stub-loaded module behind for other test modules
        for name in list(sys.modules):
            if any(name == root or name.startswith(root + ".") for root in _STUBBED_ROOTS):
                del sys.modules[name]
        sys.modules.update({k: v for k, v in saved.items() if k not in sys.modules})


class ChatMLTokenizer:
    """Character-level tokenizer with a Qwen3.5-style ChatML template (thinking off: empty think block).

    system_line     rendered as a leading system turn, like a thinking-mode Teacher's Reasoning effort line
    history_think   False renders earlier assistant turns without their empty think block (Qwen3-style)
    remap           characters this tokenizer encodes to other ids
    """

    SPECIAL = ("<|im_start|>", "<|im_end|>", "<think>", "</think>")
    _SPLIT = re.compile("(" + "|".join(map(re.escape, SPECIAL)) + ")")
    _REMAP_OFFSET = 2_000_000
    chat_template = "unit-test ChatML"
    unk_token_id = None

    def __init__(self, *, system_line=None, history_think=True, remap=""):
        self.system_line, self.history_think, self.remap = system_line, history_think, set(remap)
        self.eos_token_id = self.convert_tokens_to_ids("<|im_end|>")

    def convert_tokens_to_ids(self, token):
        return self.SPECIAL.index(token) + 1 if token in self.SPECIAL else None

    def encode(self, text, add_special_tokens=False):
        ids = []
        for piece in self._SPLIT.split(text):
            if piece in self.SPECIAL:
                ids.append(self.convert_tokens_to_ids(piece))
            else:
                ids.extend(1000 + ord(c) + (self._REMAP_OFFSET if c in self.remap else 0) for c in piece)
        return ids

    def decode(self, ids):
        out = []
        for token in ids:
            if token <= len(self.SPECIAL):
                out.append(self.SPECIAL[token - 1])
            else:
                value = token - 1000
                out.append(chr(value - self._REMAP_OFFSET if value >= self._REMAP_OFFSET else value))
        return "".join(out)

    def apply_chat_template(
        self, messages, tokenize=True, add_generation_prompt=False, tools=None, return_dict=False, **kwargs
    ):
        empty_think = "<think>\n\n</think>\n\n"
        last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
        text = f"<|im_start|>system\n{self.system_line}<|im_end|>\n" if self.system_line else ""
        for i, message in enumerate(messages):
            content = message.get("content") or ""
            if message["role"] == "assistant" and (self.history_think or i > last_user):
                content = empty_think + content
            text += f"<|im_start|>{message['role']}\n{content}<|im_end|>\n"
        if add_generation_prompt:
            text += "<|im_start|>assistant\n" + ("<think>\n" if kwargs.get("enable_thinking", True) else empty_think)
        return self.encode(text) if tokenize else text


KWARGS = {"enable_thinking": False}


def codec_for(gw, tokenizer):
    # hf_model_type qwen3_5 selects the Qwen builder the 9B student gets (ChatML newline repair).
    return gw.MessageCodec(tokenizer, hf_model_type="qwen3_5", apply_chat_template_kwargs=KWARGS)


def check(gw, student, teacher):
    return gw.check.run_check(codec_for(gw, student), student, teacher, chat_template_kwargs=KWARGS)


def test_gateway_stream_equals_a_full_native_render(gw):
    student = ChatMLTokenizer()
    messages = gw.check.terminus2_conversation()
    ids = gw.check.gateway_token_ids(
        codec_for(gw, student), messages, end_of_turn_id=student.eos_token_id, encode=student.encode
    )
    assert ids == student.apply_chat_template(messages, add_generation_prompt=True, enable_thinking=False)
    # The Qwen builder restored the newline after each generated <|im_end|> (two assistant turns).
    assert student.decode(ids).count("<|im_end|>\n<|im_start|>user") == 2


def test_same_format_passes(gw):
    result = check(gw, ChatMLTokenizer(), ChatMLTokenizer())
    assert result["passed"]
    assert all(c["match"] for c in result["checks"].values())
    assert "PASS" in gw.check.format_report(result)


def test_teacher_system_line_diverges_at_the_start(gw):
    result = check(gw, ChatMLTokenizer(), ChatMLTokenizer(system_line="Reasoning effort: xhigh"))
    assert not result["passed"]
    gate = result["checks"]["gateway_vs_teacher"]
    assert gate["first_divergence"] == 1  # <|im_start|> then user vs system
    assert gate["windows"]["gateway"][:2] == ["<|im_start|>", "u"]
    assert gate["windows"]["teacher"][:2] == ["<|im_start|>", "s"]
    assert result["checks"]["gateway_vs_student_template"]["match"]  # the Teacher's template is the odd one
    report = gw.check.format_report(result)
    assert "FAIL" in report and "gateway_vs_teacher: first divergence at token 1" in report


def test_teacher_dropping_history_thinking_diverges_at_the_first_assistant_turn(gw):
    student = ChatMLTokenizer()
    result = check(gw, student, ChatMLTokenizer(history_think=False))
    gate = result["checks"]["gateway_vs_teacher"]
    assert not result["passed"]
    first_prompt = student.apply_chat_template(
        gw.check.terminus2_conversation()[:1], add_generation_prompt=True, enable_thinking=False
    )
    # The first prompt ends with the generation prompt's empty think block (6 tokens here); the
    # Teacher renders that first assistant turn without it and goes straight to the JSON action.
    assert gate["first_divergence"] == len(first_prompt) - 6
    offset = gate["first_divergence"] - gate["window_start"]
    assert gate["windows"]["gateway"][offset] == "<think>"
    assert gate["windows"]["teacher"][offset] == "{"


def test_gateway_keeping_generated_think_blocks_fails_even_with_identical_templates(gw):
    # Qwen3-style templates re-render history without the empty think block the model generated;
    # the Gateway never re-renders, so the Teacher would score a format it never produces itself.
    tok = ChatMLTokenizer(history_think=False)
    result = check(gw, tok, ChatMLTokenizer(history_think=False))
    assert not result["passed"]
    assert not result["checks"]["gateway_vs_student_template"]["match"]
    assert result["checks"]["sample_text"]["match"]


def test_tokenizers_encoding_differently_fail_even_when_the_conversation_matches(gw):
    assert "中" not in json.dumps(gw.check.terminus2_conversation(), ensure_ascii=False)
    result = check(gw, ChatMLTokenizer(), ChatMLTokenizer(remap="中"))
    assert result["checks"]["gateway_vs_teacher"]["match"]
    assert not result["checks"]["sample_text"]["match"]
    assert not result["passed"]


def test_first_divergence_handles_prefixes(gw):
    assert gw.check.first_divergence([1, 2, 3], [1, 2, 3]) is None
    assert gw.check.first_divergence([1, 2, 3], [1, 2]) == 2
    assert gw.check.first_divergence([1, 9, 3], [1, 2, 3]) == 1


@pytest.mark.parametrize("teacher,code", [(ChatMLTokenizer(), 0), (ChatMLTokenizer(system_line="x"), 1)])
def test_main_exit_codes_and_evidence(gw, monkeypatch, tmp_path, capsys, teacher, code):
    student = ChatMLTokenizer()
    monkeypatch.setattr(gw.check, "load_student", lambda path, kwargs: (codec_for(gw, student), student))
    monkeypatch.setattr(gw.check, "load_teacher_tokenizer", lambda path: teacher)
    out = tmp_path / "check.json"
    argv = ["--student-model", "/m/student", "--teacher-model", "/m/teacher", "--json", str(out)]
    assert gw.check.main(argv) == code
    saved = json.loads(out.read_text())
    assert saved["passed"] is (code == 0) and saved["teacher_model"] == "/m/teacher"
    assert "teacher format check" in capsys.readouterr().out


def test_main_reports_a_check_that_cannot_run(gw, monkeypatch, capsys):
    def missing(path, kwargs):
        raise OSError("no tokenizer.json")

    monkeypatch.setattr(gw.check, "load_student", missing)
    assert gw.check.main(["--student-model", "/m/s", "--teacher-model", "/m/t"]) == 2
    assert "could not run" in capsys.readouterr().err


def test_default_kwargs_match_the_training_command(gw):
    result = subprocess.run(
        ["bash", str(ROOT / "examples/harbor_opd_rl/train_tb21_lora_smoke.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, "PRINT_COMMAND": "1", "TRAIN_FILE": "/t", "TEST_FILE": "/v", "RUN_ROOT": "/r"},
    )
    assert result.returncode == 0, result.stderr
    prefix = "++data.apply_chat_template_kwargs."
    literal = {"True": True, "False": False}
    trained = {
        key: literal.get(value, value)
        for arg in shlex.split(result.stdout)
        if arg.startswith(prefix)
        for key, value in [arg[len(prefix) :].split("=", 1)]
    }
    assert trained == gw.check.DEFAULT_CHAT_TEMPLATE_KWARGS
