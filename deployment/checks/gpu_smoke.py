"""Exercise GPU math and import the pinned training stack; never load a model."""

import importlib
import importlib.metadata
import json

import torch


def main():
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")
    modules = ("vllm", "ray", "transformers", "flash_attn", "transfer_queue", "verl", "uni_agent")
    for name in modules:
        importlib.import_module(name)
    torch.manual_seed(0)
    x = torch.randn(128, 128, device="cuda", dtype=torch.float32, requires_grad=True)
    loss = (x @ x.T).square().mean()
    loss.backward()
    torch.cuda.synchronize()
    if not torch.isfinite(loss).item() or not torch.isfinite(x.grad).all().item() or x.grad.abs().sum().item() == 0:
        raise SystemExit("GPU math or backward failed")
    print(
        json.dumps(
            {
                "schema": "dsh.gpu-smoke.v1",
                "passed": True,
                "training_accepted": False,
                "gpu": torch.cuda.get_device_name(),
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "vllm": importlib.metadata.version("vllm"),
                "imports": list(modules),
                "loss": loss.item(),
                "gradient_norm": x.grad.norm().item(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
