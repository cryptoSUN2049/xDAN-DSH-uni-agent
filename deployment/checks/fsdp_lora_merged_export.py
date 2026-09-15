"""Single-GPU native VERL FSDP LoRA merged-export component probe.

Uses a real local model and real gradient update. Does not start Ray, rollout
servers, Harbor jobs, or prove asynchronous publication. Optional fresh-process checkpoint recovery
is verified independently from serving-policy publication.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True, help="Fixed local HF snapshot; no downloads")
    parser.add_argument("--output", type=Path, required=True, help="New JSON evidence file (must not exist)")
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--checkpoint-dir", type=Path, help="New native checkpoint directory to save")
    parser.add_argument("--resume-evidence", type=Path, help="Successful prior probe JSON binding checkpoint files")
    args = parser.parse_args()
    if not 1 <= args.steps <= 10 or not 0 < args.learning_rate <= 0.1:
        parser.error("steps must be 1..10 and learning-rate in (0, 0.1]")
    if not args.model_path.is_dir() or not (args.model_path / "config.json").is_file():
        parser.error("model-path must be a local fixed HF snapshot with config.json")
    if args.output.exists():
        parser.error("output already exists; evidence must not be overwritten")
    if args.checkpoint_dir is not None and args.checkpoint_dir.exists():
        parser.error("checkpoint-dir must be new")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "uni-agent.fsdp-lora-merged-export.v1",
        "scope": "single_gpu_native_export_component",
        "passed": False,
        "rollout_publication_verified": False,
        "checkpoint_reload_verified": False,
        "model_path": str(args.model_path.resolve()),
    }
    group_started = False
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        import torch.distributed as dist
        from peft.tuners.lora.layer import LoraLayer
        from torch.distributed.fsdp import FullyShardedDataParallel as FSDP

        from verl.trainer.config import CheckpointConfig
        from verl.utils.fsdp_utils import normalize_peft_param_name
        from verl.utils.model import convert_weight_keys
        from verl.workers.config import FSDPEngineConfig, FSDPOptimizerConfig, HFModelConfig
        from verl.workers.engine.fsdp.transformer_impl import FSDPEngineWithLMHead

        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise RuntimeError("Expose exactly one operator-assigned CUDA GPU via CUDA_VISIBLE_DEVICES")
        if dist.is_initialized():
            raise RuntimeError("Probe requires its own fresh single-process distributed group")
        torch.cuda.set_device(0)
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)
        root = Path(__file__).resolve().parents[2]
        report["versions"] = {
            name: importlib.metadata.version(name) for name in ("torch", "transformers", "peft", "ray")
        }
        report["verl_commit"] = subprocess.check_output(
            ["git", "-C", str(root / "verl"), "rev-parse", "HEAD"], text=True
        ).strip()
        report["native_source_sha256"] = {
            relative: digest_file(root / "verl" / relative)
            for relative in (
                "verl/workers/engine/fsdp/transformer_impl.py",
                "verl/utils/fsdp_utils.py",
            )
        }
        report["gpu"] = torch.cuda.get_device_name(0)
        weights = sorted(args.model_path.glob("*.safetensors"))
        if not weights:
            raise RuntimeError("Require safetensors model files for explicit artifact hashing")
        report["model_files"] = {path.name: digest_file(path) for path in [args.model_path / "config.json", *weights]}
        with tempfile.TemporaryDirectory(prefix="uni-agent-fsdp-export-") as temporary:
            dist.init_process_group(
                "nccl",
                init_method=Path(temporary, "rendezvous").as_uri(),
                rank=0,
                world_size=1,
                timeout=timedelta(minutes=5),
            )
            group_started = True
            model_config = HFModelConfig(
                path=str(args.model_path.resolve()),
                use_remove_padding=False,
                use_fused_kernels=False,
                enable_gradient_checkpointing=True,
                override_config={"attn_implementation": "sdpa"},
                lora_rank=8,
                lora_alpha=16,
                target_modules=["q_proj", "v_proj"],
                lora={"type": "lora", "rank": 8, "alpha": 16, "merge": True, "target_modules": ["q_proj", "v_proj"]},
            )
            engine = FSDPEngineWithLMHead(
                model_config=model_config,
                engine_config=FSDPEngineConfig(
                    strategy="fsdp",
                    model_dtype="bf16",
                    use_orig_params=False,
                    use_torch_compile=False,
                    param_offload=False,
                    optimizer_offload=False,
                ),
                optimizer_config=FSDPOptimizerConfig(lr=args.learning_rate, total_training_steps=args.steps),
                checkpoint_config=CheckpointConfig(),
            )
            engine.initialize()

            def tensor_hash(tensor):
                value = tensor.detach().cpu().contiguous()
                return hashlib.sha256(value.reshape(-1).view(torch.uint8).numpy().tobytes()).hexdigest()

            def snapshot():
                with FSDP.summon_full_params(engine.module, writeback=False):
                    return {name: tensor_hash(value) for name, value in engine.module.named_parameters()}

            def optimizer_hash():
                digest = hashlib.sha256()

                def visit(value):
                    if isinstance(value, torch.Tensor):
                        digest.update(str((value.dtype, tuple(value.shape))).encode())
                        digest.update(tensor_hash(value).encode())
                    elif isinstance(value, dict):
                        for key in sorted(value, key=str):
                            digest.update(repr(key).encode())
                            visit(value[key])
                    elif isinstance(value, (tuple, list)):
                        for item in value:
                            visit(item)
                    else:
                        digest.update(repr(value).encode())

                visit(engine.optimizer.state_dict())
                return digest.hexdigest()

            if args.resume_evidence is not None:
                prior = json.loads(args.resume_evidence.read_text())
                if not prior.get("passed") or prior.get("model_files") != report["model_files"]:
                    raise RuntimeError("Resume evidence must be successful and bind the same model")
                checkpoint = Path(prior["checkpoint_path"])
                observed = {
                    path.relative_to(checkpoint).as_posix(): digest_file(path)
                    for path in checkpoint.rglob("*")
                    if path.is_file()
                }
                if not observed or observed != prior["checkpoint_files"]:
                    raise RuntimeError("Checkpoint files differ from the source evidence")
                engine.load_checkpoint(str(checkpoint), del_local_after_load=False)
                if snapshot() != prior["trainer_parameter_hashes"]:
                    raise RuntimeError("Independent checkpoint load changed trainer parameters")
                if optimizer_hash() != prior["optimizer_state_sha256"]:
                    raise RuntimeError("Independent checkpoint load changed optimizer state")
                report["checkpoint_reload_verified"] = True
                report["resume_evidence_sha256"] = digest_file(args.resume_evidence)
                report["restored_optimizer_state_sha256"] = optimizer_hash()

            before = snapshot()
            # Match the recipe's native FSDP1 default. Inspect original names
            # only while summoned; outside this context FSDP exposes flat params.
            with FSDP.summon_full_params(engine.module, writeback=False):
                trainable = [name for name, parameter in engine.module.named_parameters() if parameter.requires_grad]
            if not trainable or any("lora_" not in name for name in trainable):
                raise RuntimeError("Expected only real LoRA parameters to be trainable")
            tokens = model_config.tokenizer("The command prints a line. Explain: echo hello", return_tensors="pt").to(
                "cuda"
            )
            engine.module.train()
            losses, grad_norms = [], []
            for _ in range(args.steps):
                engine.optimizer.zero_grad(set_to_none=True)
                output = engine.module(**tokens, labels=tokens["input_ids"], use_cache=False)
                loss = output.loss
                if loss is None or not torch.isfinite(loss):
                    raise RuntimeError("Diagnostic language-model loss is not finite")
                loss.backward()
                norm = engine.module.clip_grad_norm_(1.0)
                if not torch.isfinite(norm) or norm <= 0:
                    raise RuntimeError("Expected finite nonzero real adapter gradient")
                losses.append(float(loss.detach()))
                grad_norms.append(float(norm))
                engine.optimizer.step()
            updated = snapshot()
            adapter_changed = [name for name in before if "lora_" in name and before[name] != updated[name]]
            base_changed = [name for name in before if "lora_" not in name and before[name] != updated[name]]
            if not adapter_changed or base_changed:
                raise RuntimeError("Expected adapter update with unchanged frozen trainer base")
            with FSDP.summon_full_params(engine.module, writeback=False):
                peft_model = getattr(engine.module, "_fsdp_wrapped_module", engine.module)
                layer_name, layer = next(
                    (name, item)
                    for name, item in peft_model.named_modules()
                    if isinstance(item, LoraLayer) and hasattr(item, "get_delta_weight")
                )
                base = layer.get_base_layer().weight.detach().clone()
                delta = layer.get_delta_weight("default").detach().to(base.dtype)
                if not torch.isfinite(delta).all() or delta.abs().max() == 0:
                    raise RuntimeError("Selected real LoRA layer has no finite update")
                expected = (base + delta).cpu()
                # state_dict omits FSDP wrapper names, including nested auto-wraps.
                layer_name = layer_name.replace("_fsdp_wrapped_module.", "")
                names = normalize_peft_param_name({layer_name + ".base_layer.weight": expected})
                names = convert_weight_keys(names, getattr(engine.module, "_fsdp_wrapped_module", engine.module))
                expected_name, expected = next(iter(names.items()))
                base_cpu = base.cpu()
            exported, peft_config = engine.get_per_tensor_param()
            if peft_config is not None:
                raise RuntimeError("Merged native export unexpectedly returned PEFT metadata")
            rows = []
            selected = None
            # Exhaust the native generator so the merge context exits and restores base.
            for name, tensor in exported:
                if "lora_" in name:
                    raise RuntimeError("Merged export unexpectedly contains adapter keys")
                rows.append({"name": name, "shape": list(tensor.shape), "sha256": tensor_hash(tensor)})
                if name == expected_name:
                    selected = tensor.detach().cpu().clone()
            if selected is None:
                raise RuntimeError(f"Selected native export key not found: {expected_name}")
            torch.testing.assert_close(selected, expected, rtol=0, atol=0)
            if torch.equal(selected, base_cpu):
                raise RuntimeError("Merged export equals base: adapter update absent or rounded away")
            restored = snapshot()
            if updated != restored:
                raise RuntimeError("Native export permanently changed trainer base or adapter tensors")
            report["trainer_parameter_hashes"] = restored
            report["optimizer_state_sha256"] = optimizer_hash()
            if args.checkpoint_dir is not None:
                engine.save_checkpoint(str(args.checkpoint_dir.resolve()), global_step=args.steps)
                report["checkpoint_path"] = str(args.checkpoint_dir.resolve())
                report["checkpoint_files"] = {
                    path.relative_to(args.checkpoint_dir).as_posix(): digest_file(path)
                    for path in args.checkpoint_dir.rglob("*")
                    if path.is_file()
                }
                if not report["checkpoint_files"]:
                    raise RuntimeError("Native checkpoint produced no files")
            report.update(
                passed=True,
                losses=losses,
                gradient_norms=grad_norms,
                trainable_count=len(trainable),
                adapter_changed_count=len(adapter_changed),
                adapter_updates={name: {"before": before[name], "after": updated[name]} for name in adapter_changed},
                base_changed_count=0,
                export_count=len(rows),
                export_tensors=rows,
                selected_layer=expected_name,
                merged_max_abs_delta=float((selected.float() - base_cpu.float()).abs().max()),
                trainer_state_restored_exactly=True,
                expected_base_plus_delta_exact=True,
            )
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        try:
            if group_started:
                import torch.distributed as dist

                dist.destroy_process_group()
        except Exception as error:
            report["passed"] = False
            report["cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
            print(json.dumps({"passed": report["passed"], "output": str(args.output), "scope": report["scope"]}))


if __name__ == "__main__":
    main()
