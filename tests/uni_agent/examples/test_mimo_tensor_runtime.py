"""Actual nested constructor, DP splitting and minibatch indexing regression.

Run on cloud with PYTHONPATH pointing to the prepared native runtime.
The production unpad initialization is not verified in this CPU environment;
these tests isolate tensor representation and do not claim full padding coverage.
"""

import ast
import inspect
import io
import pickle
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import torch
from tensordict import TensorDict
from transfer_queue.metadata import BatchMeta
from transfer_queue.storage.managers.base import KVStorageManager
from transfer_queue.storage.managers.simple_storage_manager import AsyncSimpleStorageManager
from transfer_queue.utils.serial_utils import MsgpackDecoder, MsgpackEncoder

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


def tq_roundtrip(data):
    """Actual installed wire encoder/decoder, not torch.save as a substitute."""
    return MsgpackDecoder().decode(MsgpackEncoder().encode(data))


def tq_retrieve_assembly(samples, route):
    """Call installed retrieve packing code without allocating network actors.

    Simple get_data uses _pack_field_values for every retrieved field. KV
    get_data uses _merge_tensors_to_tensordict. Supply actual decoded per-row
    values and metadata; only the executor is supplied, not a fake packer.
    This covers their assembly and wire implementation, not remote ZMQ I/O.
    """
    # AgentLoopWorkerTQ uses this actual producer before enqueueing. Decode its
    # serialized output back into per-row fields before storage retrieval.
    produced = tq_roundtrip(tu.list_of_dict_to_tensordict(samples))
    columns = {
        key: list(value.unbind()) if value.is_nested else list(value.unbind(0)) for key, value in produced.items()
    }
    samples = [{key: values[index] for key, values in columns.items()} for index in range(len(samples))]
    if route == "simple":
        return TensorDict(
            {
                key: AsyncSimpleStorageManager._pack_field_values([sample[key] for sample in samples])
                for key in samples[0]
            },
            batch_size=[len(samples)],
        )
    fields = sorted(samples[0])
    meta = BatchMeta(
        global_indexes=list(range(len(samples))),
        partition_ids=["train"] * len(samples),
        field_schema={key: {} for key in fields},
    )
    values = [sample[key] for key in fields for sample in samples]
    with ThreadPoolExecutor(max_workers=2) as executor:
        context = SimpleNamespace(_get_executor=lambda: executor)
        return KVStorageManager._merge_tensors_to_tensordict(context, meta, values)


@pytest.mark.parametrize("route", ["simple", "kv"])
@pytest.mark.parametrize(
    "axes,lengths",
    [
        (4, [8298, 8298, 8298, 8298]),
        (4, [8298, 8217, 7300, 8298]),
        (3, [9, 9, 9, 9]),
        (4, [16, 16, 16, 16]),  # square backing values: shape cannot infer orientation
        (4, [4, 4, 4, 4]),
        (3, [1, 1, 1, 1]),
    ],
)
def test_installed_tq_retrieve_wire_worker_dp_index_preserves_positions(route, axes, lengths):
    samples = [
        {
            "input_ids": torch.arange(length) + index * 10000,
            "position_ids": torch.arange(axes * length).reshape(axes, length) + index * 1000000,
        }
        for index, length in enumerate(lengths)
    ]
    received = tq_roundtrip(tq_retrieve_assembly(samples, route))
    # TQ dispatch splits metadata per rank before each worker receives data;
    # exercise actual TensorDict DP chunk equivalence before its boundary fix.
    for rank, chunk in enumerate(tu.chunk_tensordict(received, 2)):
        chunk = pickle.loads(pickle.dumps(chunk.consolidate()))
        tu.maybe_fix_3d_position_ids(chunk)
        tu.maybe_fix_3d_position_ids(chunk)  # engine train/infer calls it again
        selected = tu.index_select_tensor_dict(chunk, [1, 0])
        restored = tq_roundtrip(selected)
        tu.maybe_fix_3d_position_ids(restored)
        for local, original in enumerate([rank * 2 + 1, rank * 2]):
            for key in samples[original]:
                assert torch.equal(restored[key].unbind()[local], samples[original][key])
                assert restored[key].dtype == samples[original][key].dtype
                assert restored[key].device == samples[original][key].device
        assert restored["position_ids"].offsets().diff().tolist() == [lengths[rank * 2 + 1], lengths[rank * 2]]


@pytest.mark.parametrize("layout", [torch.jagged, torch.strided])
@pytest.mark.parametrize("length", [1, 4])
def test_worker_boundary_single_sample_correct_or_strided_is_idempotent(layout, length):
    position = torch.arange(4 * length).reshape(4, length)
    nested = (
        tu.nested_tensor_from_tensor_list([position], ragged_idx=2)
        if layout == torch.jagged
        else torch.nested.as_nested_tensor([position], layout=layout)
    )
    data = TensorDict(
        {"position_ids": nested, "input_ids": tu.nested_tensor_from_tensor_list([torch.arange(length)])},
        batch_size=[1],
    )
    for _ in range(3):
        tu.maybe_fix_3d_position_ids(data)
        assert torch.equal(data["position_ids"].unbind()[0], position)
        assert data["position_ids"].offsets().diff().tolist() == [length]


def test_worker_boundary_rejects_position_token_length_mismatch():
    data = TensorDict(
        {
            "position_ids": torch.nested.as_nested_tensor([torch.arange(36).reshape(4, 9)], layout=torch.jagged),
            "input_ids": tu.nested_tensor_from_tensor_list([torch.arange(8)]),
        },
        batch_size=[1],
    )
    with pytest.raises(ValueError, match="input token lengths"):
        tu.maybe_fix_3d_position_ids(data)
