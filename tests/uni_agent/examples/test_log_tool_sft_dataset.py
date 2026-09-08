import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


class Tokenizer:
    eos_token = "§"
    eos_token_id = ord("§")

    def __len__(self):
        return 0x110000

    def decode(self, ids, **kwargs):
        return "".join(chr(value) for value in ids)

    def apply_chat_template(self, messages, *, tokenize, tools=None, add_generation_prompt=False, **kwargs):
        assert kwargs["enable_thinking"] is False
        text = json.dumps(tools, sort_keys=True) + "|"
        for message in messages:
            body = (message.get("content") or "") + json.dumps(message.get("tool_calls", []), sort_keys=True)
            text += message["role"] + ":" + body + "§\n"
        if add_generation_prompt:
            text += "assistant:"
        return [ord(char) for char in text] if tokenize else text


def row(tools=None, target=None):
    return dict(
        schema="dsh.t2-sft-decision.v1",
        sample_id="s1",
        enable_thinking=False,
        request_json=json.dumps(
            dict(
                messages=[
                    dict(role="user", content="hello"),
                    dict(role="assistant", content="history"),
                    dict(role="tool", content="observed", tool_call_id="old"),
                ],
                tools=tools,
            )
        ),
        target_json=json.dumps(target or dict(role="assistant", content="answer")),
    )


def dataset(tmp_path, rows, tokenizer=None, **config):
    from examples.dsh.capability_tasks.log_tool.sft_dataset import DshDecisionSFTDataset

    path = tmp_path / "data.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return DshDecisionSFTDataset(
        str(path),
        tokenizer or Tokenizer(),
        dict(dict(pad_mode="no_padding", truncation="error", max_length=10000), **config),
    )


def test_only_last_decision_supervised_and_native_collator(tmp_path):
    from verl.utils.dataset.dataset_utils import DatasetPadMode, SFTTensorCollator

    ds = dataset(
        tmp_path, [row(), dict(row([dict(type="function", function=dict(name="x", parameters={}))]), sample_id="s2")]
    )
    first = ds[0]
    tokenizer = Tokenizer()
    prompt = json.loads(row()["request_json"])
    prefix = tokenizer.apply_chat_template(**prompt, tokenize=True, add_generation_prompt=True, enable_thinking=False)
    assert set(first) == {"input_ids", "position_ids", "loss_mask"}
    assert all(value.dtype == torch.long and value.ndim == 1 for value in first.values())
    assert first["loss_mask"][: len(prefix)].sum() == 0
    assert first["loss_mask"][len(prefix) :].tolist() == [1] * (len(first["input_ids"]) - len(prefix))
    assert tokenizer.decode(first["input_ids"][len(prefix) :].tolist()).startswith("answer")
    batch = SFTTensorCollator(DatasetPadMode.NO_PADDING)([first, ds[1]])
    assert batch["input_ids"].is_nested
    assert torch.equal(
        torch.roll(batch["loss_mask"].values(), -1)[len(prefix) - 1 : len(prefix)], torch.ones(1, dtype=torch.long)
    )


@pytest.mark.parametrize("bad", ["empty", "thinking", "length", "prefix", "eos"])
def test_fail_closed(tmp_path, bad):
    record = row()
    tok = Tokenizer()
    config = {}
    if bad == "empty":
        record["target_json"] = json.dumps(dict(role="assistant", content=""))
    elif bad == "thinking":
        record["enable_thinking"] = True
    elif bad == "length":
        config["max_length"] = 4
    else:
        original = tok.apply_chat_template

        def render(*args, **kwargs):
            result = original(*args, **kwargs)
            if not kwargs["add_generation_prompt"]:
                if bad == "prefix":
                    return [99] + result if kwargs["tokenize"] else "x" + result
                return [v for v in result if v != tok.eos_token_id] if kwargs["tokenize"] else result.replace("§", "")
            return result

        tok.apply_chat_template = render
    with pytest.raises(ValueError):
        ds = dataset(tmp_path, [record], tok, **config)
        ds[0]


def test_structured_call_and_backslashes_are_target_only(tmp_path):
    args = {"code": {"host": r'return /\w+/.test("x")'}, "service": None}
    tools = [{"type": "function", "function": {"name": "register", "parameters": {"type": "object"}}}]
    target = dict(
        role="assistant",
        content=None,
        tool_calls=[dict(id="c1", type="function", function=dict(name="register", arguments=args))],
    )
    ds = dataset(tmp_path, [row(tools, target)])
    output = ds[0]
    text = Tokenizer().decode(output["input_ids"][output["loss_mask"].bool()].tolist())
    recovered = json.loads(text[:-2])[0]["function"]["arguments"]
    assert recovered == args


def test_token_only_prefix_mismatch_rejected(tmp_path):
    tok = Tokenizer()
    original = tok.apply_chat_template

    def render(*args, **kwargs):
        output = original(*args, **kwargs)
        if kwargs["tokenize"] and not kwargs["add_generation_prompt"]:
            output[0] += 1
        return output

    tok.apply_chat_template = render
    with pytest.raises(ValueError, match="token prefix"):
        dataset(tmp_path, [row()], tok)[0]


@pytest.mark.parametrize("changes", [dict(pad_mode="right"), dict(truncation="right")])
def test_native_no_padding_contract_required(tmp_path, changes):
    with pytest.raises(ValueError):
        dataset(tmp_path, [row()], **changes)
