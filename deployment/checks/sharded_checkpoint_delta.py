"""Exact CPU audit of trusted world-size-two native FSDP checkpoints.

Only use artifacts produced by this project's own training. ShardedTensor and
RNG loading needs weights_only=False; file hashes bind evidence, not trust.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path

import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.distributed._shard.sharded_tensor import ShardedTensor

from deployment.checks.optimizer_delta import compare_optimizers, load_trusted, require


def validate_coverage(shape, boxes):
    require(shape and all(type(n) is int and n > 0 for n in shape), "Invalid global shape")
    volume = 0
    for i, box in enumerate(boxes):
        offsets, sizes = box["offsets"], box["sizes"]
        require(box["rank"] in (0, 1), "Invalid shard rank")
        require(len(offsets) == len(sizes) == len(shape), "Shard dimensionality mismatch")
        require(
            all(
                type(o) is int and type(s) is int and o >= 0 and s > 0 and o + s <= n
                for o, s, n in zip(offsets, sizes, shape, strict=True)
            ),
            "Invalid shard bounds",
        )
        volume += math.prod(sizes)
        for prior in boxes[:i]:
            overlap = all(
                max(a, b) < min(a + x, b + y)
                for a, b, x, y in zip(offsets, prior["offsets"], sizes, prior["sizes"], strict=True)
            )
            require(not overlap, "Overlapping shards")
    require(volume == math.prod(shape), "Incomplete shard coverage")


def _box(metadata):
    return {
        "offsets": list(metadata.shard_offsets),
        "sizes": list(metadata.shard_sizes),
        "rank": metadata.placement.rank(),
    }


def _digest_tensor(value):
    return hashlib.sha256(value.contiguous().reshape(-1).view(torch.uint8).numpy().tobytes()).hexdigest()


def _compare(a, b):
    require(type(a) is torch.Tensor and type(b) is torch.Tensor, "Unsupported tensor subclass")
    require(
        a.device.type == b.device.type == "cpu" and a.layout == b.layout == torch.strided, "CPU dense tensors required"
    )
    require(a.shape == b.shape and a.dtype == b.dtype, "Tensor shape/dtype changed")
    require(not a.is_complex(), "Complex tensor unsupported")
    changed, finite, maximum = False, True, 0.0
    av, bv = a.reshape(-1), b.reshape(-1)
    for start in range(0, av.numel(), 262144):
        x, y = av[start : start + 262144], bv[start : start + 262144]
        ok = bool(torch.isfinite(x).all() and torch.isfinite(y).all())
        finite = finite and ok
        changed = changed or not torch.equal(x, y)
        if ok and x.numel():
            maximum = max(maximum, float((x.double() - y.double()).abs().max()))
    return {"finite": finite, "changed": changed, "max_abs_delta": maximum if finite else None}


def _describe(a, b, rank):
    if isinstance(a, ShardedTensor):
        require(isinstance(b, ShardedTensor), "Tensor representation changed")
        ma, mb = a.metadata(), b.metadata()
        descriptor = {
            "shape": list(ma.size),
            "dtype": str(ma.tensor_properties.dtype),
            "boxes": [_box(s) for s in ma.shards_metadata],
        }
        require(
            descriptor
            == {
                "shape": list(mb.size),
                "dtype": str(mb.tensor_properties.dtype),
                "boxes": [_box(s) for s in mb.shards_metadata],
            },
            "Shard metadata changed",
        )
        old, new = a.local_shards(), b.local_shards()
        require(len(old) == len(new), "Local shard count changed")
        rows = []
        for x, y in zip(old, new, strict=True):
            box = _box(x.metadata)
            require(box == _box(y.metadata) and box["rank"] == rank, "Local shard placement mismatch")
            require(list(x.tensor.shape) == box["sizes"], "Local tensor shape disagrees with metadata")
            require(str(x.tensor.dtype) == descriptor["dtype"], "Local tensor dtype disagrees with metadata")
            rows.append({"box": box, **_compare(x.tensor, y.tensor)})
        return {"kind": "sharded", "descriptor": descriptor, "local": rows}
    require(not isinstance(b, ShardedTensor), "Tensor representation changed")
    return {
        "kind": "replicated",
        "descriptor": {"shape": list(a.shape), "dtype": str(a.dtype)},
        **_compare(a, b),
        "before_sha256": _digest_tensor(a),
        "after_sha256": _digest_tensor(b),
    }


def _load_native(path):
    require(path.is_file() and not path.is_symlink(), "Regular non-symlink checkpoint required")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        result = torch.load(source, map_location="cpu", weights_only=False)
        source.seek(0)
        require(hashlib.file_digest(source, "sha256").hexdigest() == digest, "Checkpoint changed during load")
    return result, {"path": str(path.resolve()), "sha256": digest, "bytes": path.stat().st_size}


def _rank_worker(rank, before, after, temporary):
    torch.set_num_threads(2)
    report = {"rank": rank, "passed": False, "files": {}, "errors": []}
    try:
        dist.init_process_group(
            "gloo",
            init_method="file://" + str(Path(temporary) / "rendezvous"),
            rank=rank,
            world_size=2,
            timeout=timedelta(minutes=10),
        )
        models = []
        for label, folder in (("before", before), ("after", after)):
            value, info = _load_native(Path(folder) / f"model_world_size_2_rank_{rank}.pt")
            report["files"][label + "_model"] = info
            require(isinstance(value, dict) and value and all(isinstance(k, str) for k in value), "Invalid model state")
            models.append(value)
        require(models[0].keys() == models[1].keys(), "Model keys changed")
        report["model"] = {name: _describe(value, models[1][name], rank) for name, value in models[0].items()}
        del models
        optimizers = []
        for label, folder in (("before", before), ("after", after)):
            value, info = load_trusted(Path(folder) / f"optim_world_size_2_rank_{rank}.pt")
            optimizers.append(value)
            report["files"][label + "_optimizer"] = info
            extra, info = _load_native(Path(folder) / f"extra_state_world_size_2_rank_{rank}.pt")
            report["files"][label + "_extra"] = info
            require(isinstance(extra, dict) and extra.get("lr_scheduler") and extra.get("rng"), "Missing scheduler/RNG")
        report["optimizer"] = compare_optimizers(*optimizers)
        report["passed"] = report["optimizer"]["passed"]
    except Exception as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        if dist.is_initialized():
            dist.destroy_process_group()
        (Path(temporary) / f"rank{rank}.json").write_text(json.dumps(report, allow_nan=False))


def _aggregate(ranks):
    require(len(ranks) == 2 and [r["rank"] for r in ranks] == [0, 1], "Missing rank reports")
    require(all("model" in r for r in ranks), "Rank model audit failed")
    left, right = [r["model"] for r in ranks]
    require(left.keys() == right.keys(), "Cross-rank model keys mismatch")
    counts = {"base_count": 0, "base_changed": 0, "adapter_count": 0, "adapter_changed": 0, "all_finite": True}
    for name, a in left.items():
        b = right[name]
        require(a["kind"] == b["kind"] and a["descriptor"] == b["descriptor"], "Cross-rank metadata mismatch")
        if a["kind"] == "sharded":
            boxes = a["descriptor"]["boxes"]
            validate_coverage(a["descriptor"]["shape"], boxes)
            rows = a["local"] + b["local"]
            require(
                sorted(json.dumps(x["box"], sort_keys=True) for x in rows)
                == sorted(json.dumps(x, sort_keys=True) for x in boxes),
                "Local shards do not match global metadata",
            )
        else:
            require(
                all(a[k] == b[k] for k in ("before_sha256", "after_sha256")), "Replicated values disagree across ranks"
            )
            rows = [a, b]
        kind = "adapter" if "lora_" in name.lower() else "base"
        counts[kind + "_count"] += 1
        counts[kind + "_changed"] += int(any(x["changed"] for x in rows))
        counts["all_finite"] &= all(x["finite"] for x in rows)
    counts["passed"] = bool(
        counts["base_count"] and counts["adapter_changed"] and not counts["base_changed"] and counts["all_finite"]
    )
    return counts


def audit(before, after, output):
    before, after, output = Path(before), Path(after), Path(output)
    require(before.resolve() != after.resolve(), "Distinct checkpoints required")
    configs = {}
    for label, folder in (("before", before), ("after", after)):
        path = folder / "fsdp_config.json"
        require(path.is_file() and not path.is_symlink(), "Missing FSDP config")
        raw = path.read_bytes()
        require(json.loads(raw).get("world_size") == 2, "Expected world_size 2")
        configs[label] = {"sha256": hashlib.sha256(raw).hexdigest(), "path": str(path.resolve())}
        for rank in range(2):
            for prefix in ("model", "optim", "extra_state"):
                path = folder / f"{prefix}_world_size_2_rank_{rank}.pt"
                require(path.is_file() and not path.is_symlink(), f"Missing/invalid rank {rank} {prefix}")
    report = {
        "schema": "dsh.native-sharded-checkpoint-delta.v1",
        "world_size": 2,
        "passed": False,
        "errors": [],
        "configs": configs,
        "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "optimizer_checker_sha256": hashlib.sha256(
            Path(__file__).with_name("optimizer_delta.py").read_bytes()
        ).hexdigest(),
        "torch_version": torch.__version__,
        "scope": "Trusted native CPU shards; exact comparison and strict per-rank optimizer; not restore proof",
    }
    with output.open("x") as destination:
        old_cuda = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        try:
            with tempfile.TemporaryDirectory(prefix="fsdp-audit-") as temporary:
                context = mp.spawn(_rank_worker, args=(str(before), str(after), temporary), nprocs=2, join=False)
                deadline = time.monotonic() + 1200
                try:
                    while not context.join(timeout=1):
                        require(time.monotonic() < deadline, "CPU audit exceeded 1200 seconds")
                finally:
                    for child in context.processes:
                        if child.is_alive():
                            child.terminate()
                            child.join(timeout=10)
                            if child.is_alive():
                                child.kill()
                                child.join(timeout=10)
                report["ranks"] = [json.loads((Path(temporary) / f"rank{i}.json").read_text()) for i in range(2)]
                report["model"] = _aggregate(report["ranks"])
                report["passed"] = report["model"]["passed"] and all(r["passed"] for r in report["ranks"])
        except Exception as error:
            report["errors"].append(f"{type(error).__name__}: {error}")
        finally:
            if old_cuda is None:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            else:
                os.environ["CUDA_VISIBLE_DEVICES"] = old_cuda
            json.dump(report, destination, indent=2, allow_nan=False)
            destination.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.before, args.after, args.output)
    print(json.dumps({"passed": report["passed"], "output": str(args.output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
