import pytest

from examples.mem_agent.prepare_native_smoke import select_rows


def test_subsets_exclude_teacher_outputs_and_do_not_overlap():
    rows = [
        dict(
            data_source="hotpotqa",
            prompt=[{"role": "user", "content": str(i)}],
            context="facts",
            reward_model={"ground_truth": ["answer"]},
            extra_info={"index": i},
            responses_instruct=["leak"],
        )
        for i in range(6)
    ]
    train, val = select_rows(rows, 3, 2)
    assert {r["extra_info"]["index"] for r in train}.isdisjoint(r["extra_info"]["index"] for r in val)
    assert all("responses_instruct" not in row for row in train + val)
    assert [r["extra_info"]["index"] for r in train + val] == [0, 1, 2, 3, 4]


def test_duplicate_questions_cannot_cross_partition():
    row = dict(
        data_source="hotpotqa",
        prompt=[{"role": "user", "content": "same"}],
        context="facts",
        reward_model={"ground_truth": ["answer"]},
        extra_info={},
    )
    with pytest.raises(ValueError, match="duplicate"):
        select_rows([row, row], 1, 1)
