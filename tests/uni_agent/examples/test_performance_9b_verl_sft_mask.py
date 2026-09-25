import pytest

from examples.performance_9b.verl_sft_mask import assistant_loss_mask


def test_assistant_loss_mask_marks_only_assistant_bodies():
    rendered = (
        "<|im_start|>user\nquestion<|im_end|>\n"
        "<|im_start|>assistant\nanswer one<|im_end|>\n"
        "<|im_start|>tool\nresult<|im_end|>\n"
        "<|im_start|>assistant\nanswer two<|im_end|>"
    )
    offsets = [[i, i + 1] for i in range(len(rendered))]
    mask = assistant_loss_mask(rendered, offsets)

    assert len(mask) == len(offsets)
    assert sum(mask) == len("answer one") + len("answer two")
    assert all(mask[i] == 0 for i in range(rendered.index("question"), rendered.index("question") + 8))
    assert all(mask[i] == 1 for i in range(rendered.index("answer one"), rendered.index("answer one") + 10))
    assert all(mask[i] == 0 for i in range(rendered.index("result"), rendered.index("result") + 6))


def test_assistant_loss_mask_requires_end_marker():
    with pytest.raises(ValueError, match=r"no <\|im_end\|>"):
        assistant_loss_mask("<|im_start|>assistant\nunfinished", [[0, 1]])
