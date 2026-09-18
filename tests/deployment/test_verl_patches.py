"""Our fixes for upstream VERL bugs (patches/verl/*.patch) are applied and behave.

These tests import the verl/ tree as it is on this machine, so they fail when the
patches have not been applied: run deployment/bootstrap/apply-verl-patches.sh.
"""

import pytest

torch = pytest.importorskip("torch")
padding_utils = pytest.importorskip("verl.trainer.ppo.padding_utils")


def _real_sample(seq_len: int, prompt_len: int, topk: int = 1) -> dict:
    response_len = seq_len - prompt_len
    return {
        "prompts": torch.arange(prompt_len),
        "responses": torch.arange(response_len),
        "input_ids": torch.arange(seq_len),
        "attention_mask": torch.ones(seq_len, dtype=torch.int64),
        "position_ids": torch.arange(seq_len),
        "response_mask": torch.ones(response_len, dtype=torch.int64),
        "teacher_logprobs": torch.randn(seq_len, topk),
        "teacher_ids": torch.randint(0, 1000, (seq_len, topk), dtype=torch.int32),
    }


def test_padding_sample_teacher_fields_match_its_own_length():
    # pipe-r11 step 5 (2026-09-18): a 31-sample batch was padded to 32 with a copy of a
    # ~20k-token sample; the copy kept that sample's teacher rows and distillation failed
    # `sequence_offsets[-1] == values.shape[0]`.
    assert hasattr(padding_utils, "build_padding_per_token"), "run deployment/bootstrap/apply-verl-patches.sh"
    source = _real_sample(seq_len=300, prompt_len=200, topk=2)
    template, tag = padding_utils.construct_minimal_padding_template(source, {"seq_len": 300}, eos_token_id=2)

    seq_len = template["input_ids"].shape[0]
    assert seq_len == padding_utils.SYNTHETIC_PADDING_SEQ_LEN == tag["seq_len"]
    for key in ("teacher_logprobs", "teacher_ids"):
        assert template[key].shape == (seq_len, 2), key
        assert template[key].dtype == source[key].dtype, key
        assert not template[key].any(), key
    # The rows are inert because the synthetic sample trains on no token.
    assert not template["response_mask"].any()
    # The real sample is untouched.
    assert source["teacher_logprobs"].shape == (300, 2)


def test_padding_without_teacher_fields_is_unchanged():
    source = _real_sample(seq_len=300, prompt_len=200)
    del source["teacher_logprobs"], source["teacher_ids"]
    template, _ = padding_utils.construct_minimal_padding_template(source, {"seq_len": 300}, eos_token_id=2)
    assert "teacher_logprobs" not in template and "teacher_ids" not in template
