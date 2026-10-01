"""Actual nested constructor, DP splitting and minibatch indexing regression.

Run on cloud with PYTHONPATH pointing to the prepared native runtime.
The production unpad initialization is not verified in this CPU environment;
these tests isolate tensor representation and do not claim full padding coverage.
"""

import ast
import inspect
import io

import pytest
import torch
from tensordict import TensorDict

from verl.utils import tensordict_utils as tu
from verl.workers.utils.padding import left_right_2_no_padding


def production_position_constructor(items):
    """Execute the actual padding constructor expression, excluding unpad.

    Keep the baseline and runtime on their respective production constructors;
    no test-only replacement of attention helpers or nested tensor APIs.
    """
    source, line = inspect.getsourcelines(left_right_2_no_padding)
    tree = ast.parse("".join(source))
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "position_ids_nested" for target in node.targets)
    ]
    assert len(assignments) == 1, "Production position constructor must be unambiguous"
    expression = ast.Expression(assignments[0].value)
    ast.increment_lineno(expression, line - 1)
    code = compile(expression, inspect.getsourcefile(left_right_2_no_padding), "eval")
    return eval(code, left_right_2_no_padding.__globals__, {"position_ids_list": items})


@pytest.mark.parametrize("axes", [None, 3, 4])
@pytest.mark.parametrize("lengths", [[9, 9, 9, 9], [9, 6, 8, 4]])
def test_nested_ctor_dp_minibatch_and_serialization_preserve_every_position(axes, lengths):
    batch, width = len(lengths), max(lengths)
    tokens = torch.arange(batch * width).reshape(batch, width)
    positions = torch.arange(width).expand(batch, -1).clone()
    if axes:
        positions = positions.unsqueeze(1).expand(-1, axes, -1).clone()
        positions += torch.arange(axes).view(1, -1, 1) * 100
    # Use the production constructor directly, without a fake flash-attention
    # module or test-only unpad replacement masking the initialization gap.
    converted = TensorDict(
        {
            "input_ids": tu.nested_tensor_from_tensor_list(
                [tokens[index, :length] for index, length in enumerate(lengths)]
            ),
            "position_ids": production_position_constructor(
                [positions[index, ..., :length] for index, length in enumerate(lengths)]
            ),
        },
        batch_size=[batch],
    )
    # Exercise exactly the DP and update_actor minibatch paths from the failure.
    chunks = tu.chunk_tensordict(converted, 2)
    for rank, chunk in enumerate(chunks):
        # EngineWorker.train_mini_batch does this before iterator/index_select.
        tu.maybe_fix_3d_position_ids(chunk)
        selected = tu.index_select_tensor_dict(chunk, [1, 0])
        stream = io.BytesIO()
        torch.save(selected, stream)
        stream.seek(0)
        restored = torch.load(stream, weights_only=False)
        tu.maybe_fix_3d_position_ids(restored)
        assert restored["position_ids"].offsets().diff().tolist() == [lengths[rank * 2 + 1], lengths[rank * 2]]
        for local, index in enumerate([rank * 2 + 1, rank * 2]):
            expected = positions[index, ..., : lengths[index]]
            assert torch.equal(restored["position_ids"].unbind()[local], expected)
            assert torch.equal(restored["input_ids"].unbind()[local], tokens[index, : lengths[index]])


def test_model_visible_padding_preserves_four_axes():
    items = [torch.arange(28).reshape(4, 7), torch.arange(20).reshape(4, 5)]
    nested = tu.nested_tensor_from_tensor_list(items)
    padded = torch.nested.to_padded_tensor(nested, padding=0, output_size=(2, 4, 7))
    for index, item in enumerate(items):
        assert torch.equal(padded[index, :, : item.shape[-1]], item)
    assert torch.equal(padded[1, :, 5:], torch.zeros(4, 2, dtype=padded.dtype))
