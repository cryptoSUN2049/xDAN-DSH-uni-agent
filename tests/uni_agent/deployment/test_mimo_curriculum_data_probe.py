"""CPU-only native one-row curriculum boundary, including exhausted parent state."""

import copy
import importlib.util
from pathlib import Path

import pytest
from omegaconf import OmegaConf


def module():
    path = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_curriculum_data_probe.py"
    spec = importlib.util.spec_from_file_location("curriculum_probe", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def state():
    return {
        "_index_sampler_state": None,
        "_sampler_iter_state": {"samples_yielded": 1},
        "_sampler_iter_yielded": 1,
        "_num_yielded": 1,
        "_IterableDataset_len_called": None,
        "_shared_seed": None,
        "fetcher_state": None,
        "dataset_state": None,
        "_iterator_finished": False,
    }


def test_native_exhausted_parent_yields_new_task(tmp_path, state):
    import pyarrow as pa
    import pyarrow.parquet as pq

    new = tmp_path / "new.parquet"
    pq.write_table(
        pa.Table.from_pylist([{"prompt": [{"role": "user", "content": "NEW-TASK"}], "data_source": "new-task"}]), new
    )
    config = OmegaConf.create(
        {"shuffle": False, "seed": 42, "filter_overlong_prompts": False, "dataloader_num_workers": 0}
    )
    result = module().probe_next_batch(state, new, config, tokenizer=None)
    assert result["raw_prompt"] == [{"role": "user", "content": "NEW-TASK"}]
    assert result["data_source"] == "new-task"
    assert result["rows"] == 1
    assert result["cuda_initialized"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_state", {"old_task": "OLD"}),
        ("fetcher_state", {}),
        ("_sampler_iter_state", {"samples_yielded": 2}),
        ("_shared_seed", 1),
        ("_num_yielded", 2),
    ],
)
def test_foreign_or_incompatible_state_rejected(state, field, value):
    state[field] = value
    with pytest.raises(ValueError):
        module().validate_state(state)


def test_valid_state_unchanged(state):
    before = copy.deepcopy(state)
    module().validate_state(state)
    assert state == before


@pytest.mark.parametrize("shuffle,workers", [(True, 0), (False, 1)])
def test_changed_sampler_or_worker_topology_rejected(tmp_path, state, shuffle, workers):
    config = OmegaConf.create({"shuffle": shuffle, "dataloader_num_workers": workers})
    with pytest.raises(ValueError, match="sequential single-process"):
        module().probe_next_batch(state, tmp_path / "absent.parquet", config, tokenizer=None)


def test_multirow_new_dataset_rejected(tmp_path, state):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "two.parquet"
    row = {"prompt": [{"role": "user", "content": "NEW"}], "data_source": "new"}
    pq.write_table(pa.Table.from_pylist([row, row]), path)
    config = OmegaConf.create({"shuffle": False, "filter_overlong_prompts": False, "dataloader_num_workers": 0})
    with pytest.raises(ValueError, match="exactly one"):
        module().probe_next_batch(state, path, config, tokenizer=None)


def test_epoch_budget_uses_absolute_target():
    result = module().epoch_plan(4, 5)
    assert result["total_epochs"] == 5
    assert result["initial_epoch"] == 4
    assert result["first_training_step"] == 5


@pytest.mark.parametrize("parent,target", [(4, 4), (4, 3), (0, 1), (True, 5)])
def test_nonadvancing_or_invalid_target_rejected(parent, target):
    with pytest.raises(ValueError):
        module().epoch_plan(parent, target)
