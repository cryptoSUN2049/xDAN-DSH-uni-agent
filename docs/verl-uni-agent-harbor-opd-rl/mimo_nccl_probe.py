"""Cloud-only native NCCL wire test; no model/training acceptance is implied."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ray-temp", required=True)
    args = parser.parse_args()
    import ray
    import torch

    from verl.checkpoint_engine.nccl_checkpoint_engine import NCCLCheckpointEngine

    assert torch.cuda.device_count() == 2, "Probe requires exactly two visible GPUs"
    args.output.mkdir(exist_ok=False, parents=True)
    manifest = args.overlay / "manifest.json"
    native = args.source / "verl/checkpoint_engine/nccl_checkpoint_engine.py"
    status = {
        "status": "running",
        "mode": "separate_async",
        "backend": "nccl",
        "tests": 0,
        "skipped": 0,
        "errors": 0,
        "failures": 0,
        "versions_per_test": 3,
        "started_at": time.time(),
        "overlay_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "native_source_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "results": [],
    }

    def save():
        (args.output / "status.json").write_text(json.dumps(status, indent=2) + "\n")

    @ray.remote(num_gpus=1)
    class WireWorker:
        def __init__(self, master, rebuild):
            torch.cuda.set_device(0)
            self.master = master
            self.engine = NCCLCheckpointEngine(
                bucket_size=65536,
                group_name="mimo-probe-" + str(rebuild),
                rebuild_group=rebuild,
                is_master=master,
                multi_sender=False,
            )

        def identity(self):
            props = torch.cuda.get_device_properties(0)
            return {"ray_gpu_ids": ray.get_gpu_ids(), "uuid": str(props.uuid), "pid": os.getpid()}

        def prepare(self):
            return self.engine.prepare()

        def initialize(self, kwargs):
            self.engine.init_process_group(**kwargs)

        def finalize(self):
            self.engine.finalize()

        @staticmethod
        def weights(version):
            return {
                "small_fp32": torch.arange(257, device="cuda", dtype=torch.float32) + version,
                "large_bf16": (torch.arange(40000, device="cuda") % 29 + version).to(torch.bfloat16),
                "integer": torch.arange(53, device="cuda", dtype=torch.int64).reshape(1, 53) + version,
            }

        async def transfer(self, version):
            expected = self.weights(version)
            if self.master:
                await self.engine.send_weights(iter(expected.items()), global_steps=version)
                return {"version": version, "sent": len(expected)}
            received = {}
            async for name, tensor in self.engine.receive_weights(global_steps=version):
                assert name not in received
                received[name] = tensor.clone()
            assert set(received) == set(expected)
            for name, tensor in expected.items():
                assert received[name].dtype == tensor.dtype
                assert received[name].shape == tensor.shape
                assert torch.equal(received[name], tensor), f"Mismatch in {name} version {version}"
            return {"version": version, "exact_equal": True, "tensors": len(received)}

    save()
    ray.init(address="local", num_gpus=2, _temp_dir=args.ray_temp, include_dashboard=False)
    try:
        for rebuild in (False, True):
            workers = [WireWorker.remote(master, rebuild) for master in (True, False)]
            try:
                identities = ray.get([worker.identity.remote() for worker in workers])
                assert identities[0]["uuid"] != identities[1]["uuid"]
                rounds = []
                for version in (2, 3, 4):
                    metadata = ray.get([worker.prepare.remote() for worker in workers])
                    topology = NCCLCheckpointEngine.build_topology(1, 1, metadata)
                    ray.get(
                        [
                            worker.initialize.remote({key: values[0] for key, values in kwargs.items()})
                            for worker, kwargs in zip(workers, topology, strict=True)
                        ]
                    )
                    rounds.append(ray.get([worker.transfer.remote(version) for worker in workers]))
                    ray.get([worker.finalize.remote() for worker in workers])
                status["results"].append({"rebuild_group": rebuild, "identities": identities, "rounds": rounds})
                status["tests"] += 1
                save()
            finally:
                for worker in workers:
                    ray.kill(worker, no_restart=True)
        status["status"] = "passed"
    except Exception as error:
        status.update(status="failed", errors=1, error_type=type(error).__name__)
        raise
    finally:
        ray.shutdown()
        status["finished_at"] = time.time()
        save()


if __name__ == "__main__":
    main()
