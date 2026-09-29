import json
from pathlib import Path

import pytest
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.distributed._shard.sharded_tensor import Shard, init_from_local_shards
from torch.distributed._shard.sharding_spec import ShardMetadata

from deployment.checks.sharded_checkpoint_delta import _aggregate, _compare, _describe, audit, validate_coverage

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def fixture_rank(rank, root):
    torch.set_num_threads(2)
    root = Path(root)
    dist.init_process_group("gloo", init_method="file://" + str(root / "fixture-rendezvous"), rank=rank, world_size=2)
    try:
        metadata = ShardMetadata([rank * 2, 0], [2, 2], f"rank:{rank}/cpu")
        for step in (1, 2):
            for case in ("ok", "base", "nan", "zero_optimizer"):
                dest = root / case / str(step)
                dest.mkdir(parents=True, exist_ok=True)
                base = torch.ones(2, 2)
                adapter = torch.ones(2, 2) * step
                if case == "base" and step == 2 and rank == 1:
                    base[0, 0] = 2
                if case == "nan" and step == 2 and rank == 1:
                    adapter[0, 0] = float("nan")
                model = {
                    "base.weight": init_from_local_shards([Shard(base, metadata)], 4, 2),
                    "lora_A.weight": init_from_local_shards([Shard(adapter, metadata)], 4, 2),
                    "replicated_buffer": torch.tensor(2),
                }
                torch.save(model, dest / f"model_world_size_2_rank_{rank}.pt")
                moment = 0.0 if case == "zero_optimizer" and step == 1 else float(step)
                optimizer = {
                    "state": {
                        0: {
                            "step": torch.tensor(float(step)),
                            "exp_avg": torch.ones(2) * moment,
                            "exp_avg_sq": torch.ones(2) * moment,
                        }
                    },
                    "param_groups": [{"params": [0]}],
                }
                torch.save(optimizer, dest / f"optim_world_size_2_rank_{rank}.pt")
                torch.save(
                    {"lr_scheduler": {"last_epoch": step}, "rng": {"torch": torch.get_rng_state()}},
                    dest / f"extra_state_world_size_2_rank_{rank}.pt",
                )
                if rank == 0:
                    (dest / "fsdp_config.json").write_text('{"world_size":2}')
    finally:
        dist.destroy_process_group()


@pytest.fixture(scope="module")
def checkpoints(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-shards")
    mp.spawn(fixture_rank, args=(str(root),), nprocs=2, join=True)
    return root


@pytest.mark.parametrize("case,passed", [("ok", True), ("base", False), ("nan", False), ("zero_optimizer", False)])
def test_native_two_rank_checkpoint_audit(checkpoints, tmp_path, case, passed):
    report = audit(checkpoints / case / "1", checkpoints / case / "2", tmp_path / "report.json")
    assert report["passed"] is passed
    assert report["world_size"] == 2
    assert not torch.cuda.is_initialized()
    if passed:
        assert report["model"]["base_changed"] == 0
        assert report["model"]["adapter_changed"] == 1
        assert all(r["optimizer"]["optimizer_step_advanced"] for r in report["ranks"])
        assert len(report["ranks"][0]["files"]["before_model"]["sha256"]) == 64
    assert json.loads((tmp_path / "report.json").read_text())["passed"] is passed


def test_missing_rank_rejected_before_loading(checkpoints, tmp_path):
    import shutil

    root = tmp_path / "missing"
    shutil.copytree(checkpoints / "ok" / "2", root)
    (root / "model_world_size_2_rank_1.pt").unlink()
    with pytest.raises(ValueError, match="rank"):
        audit(checkpoints / "ok" / "1", root, tmp_path / "report.json")


@pytest.mark.parametrize(
    "boxes",
    [
        [{"offsets": [0], "sizes": [2], "rank": 0}],
        [{"offsets": [0], "sizes": [3], "rank": 0}, {"offsets": [2], "sizes": [1], "rank": 1}],
        [{"offsets": [0], "sizes": [2], "rank": 0}, {"offsets": [2], "sizes": [3], "rank": 1}],
    ],
)
def test_incomplete_overlapping_or_out_of_bounds_coverage_fails(boxes):
    with pytest.raises(ValueError):
        validate_coverage([4], boxes)


def test_replicated_disagreement_rejected():
    rows = []
    for rank in range(2):
        rows.append(
            {
                "rank": rank,
                "model": {
                    "base": _describe(torch.ones(2), torch.ones(2) + rank, rank),
                    "lora_A": _describe(torch.zeros(2), torch.ones(2), rank),
                },
            }
        )
    with pytest.raises(ValueError, match="Replicated"):
        _aggregate(rows)


def test_unchanged_adapter_is_not_an_update():
    model = {name: _describe(torch.ones(2), torch.ones(2), 0) for name in ("base", "lora_A")}
    report = _aggregate([{"rank": rank, "model": model} for rank in range(2)])
    assert not report["passed"]
    assert report["adapter_changed"] == 0


@pytest.mark.parametrize("other", [torch.ones(3), torch.ones(2, dtype=torch.float64)])
def test_shape_and_dtype_change_rejected(other):
    with pytest.raises(ValueError, match="shape/dtype"):
        _compare(torch.ones(2), other)


def test_exact_original_dtype_comparison():
    before = torch.tensor([1.0], dtype=torch.float32)
    after = torch.nextafter(before, torch.tensor([2.0]))
    assert torch.equal(before.bfloat16(), after.bfloat16())
    assert _compare(before, after)["changed"]


def test_output_not_overwritten(checkpoints, tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("preserve")
    with pytest.raises(FileExistsError):
        audit(checkpoints / "ok" / "1", checkpoints / "ok" / "2", output)
    assert output.read_text() == "preserve"
