"""CPU-only one-row curriculum boundary probe; never restores model or touches a checkpoint."""

import argparse
import copy
import hashlib
import inspect
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_state(state):
    """Only admit the observed stateless, exhausted one-row sequential loader."""
    expected = {
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
    if state != expected:
        raise ValueError("Parent state is not the audited one-row sequential loader state")


def epoch_plan(parent_step, target_step):
    from omegaconf import OmegaConf

    from examples.harbor_opd_rl.launch import finalize_training_plan

    if type(parent_step) is not int or type(target_step) is not int or not 0 < parent_step < target_step:
        raise ValueError("Explicit positive parent and advancing absolute target required")
    config = OmegaConf.create(
        {"data": {"train_batch_size": 1}, "trainer": {"total_training_steps": target_step, "save_freq": 1}}
    )
    result = finalize_training_plan(config, train_rows=1, validation_rows=1)
    result.update(initial_epoch=parent_step, first_training_step=parent_step + 1)
    if not result["initial_epoch"] < result["total_epochs"]:
        raise ValueError("Parent epoch cannot reach target")
    return result


def probe_next_batch(state, parquet, config, tokenizer):
    import torch
    from torchdata.stateful_dataloader import StatefulDataLoader

    from verl.trainer.ppo.utils import create_rl_dataset, create_rl_sampler
    from verl.trainer.ppo.v1.trainer_base import PPOTrainer
    from verl.utils import tensordict_utils as tu
    from verl.utils.dataset.rl_dataset import collate_fn

    validate_state(state)
    if config.shuffle is not False or config.dataloader_num_workers != 0:
        raise ValueError("This proof only admits sequential single-process loading")
    dataset = create_rl_dataset([str(parquet)], config, tokenizer, None, max_samples=-1)
    if len(dataset) != 1:
        raise ValueError("This proof requires exactly one effective row")
    loader = StatefulDataLoader(
        dataset=dataset,
        batch_size=1,
        num_workers=0,
        drop_last=True,
        collate_fn=collate_fn,
        sampler=create_rl_sampler(config, dataset),
    )
    loader.load_state_dict(copy.deepcopy(state))
    holder = SimpleNamespace(train_dataloader=loader, train_dataloader_it=None)
    batch = PPOTrainer._fetch_one_gen_batch(holder)
    prompt = tu.unwrap_non_tensor_data(batch["raw_prompt"][0])
    if hasattr(prompt, "tolist"):
        prompt = prompt.tolist()
    return {
        "raw_prompt": prompt,
        "data_source": tu.unwrap_non_tensor_data(batch["data_source"][0]),
        "rows": len(batch),
        "cuda_initialized": torch.cuda.is_initialized(),
        "native_source_sha256": {
            str(Path(inspect.getfile(obj)).resolve()): sha(inspect.getfile(obj))
            for obj in (PPOTrainer, StatefulDataLoader, create_rl_dataset, type(dataset))
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--data-sha256", required=True)
    parser.add_argument("--old-parquet", type=Path, required=True)
    parser.add_argument("--model-tokenizer", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--parent-step", type=int, required=True)
    parser.add_argument("--target-step", type=int, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "mimo.curriculum-data-resume-probe.v1",
        "passed": False,
        "scope": (
            "Synthetic distinct-task mechanism probe using real parent data.pt; "
            "not training consumption or full model resume"
        ),
        "started_at_unix": time.time(),
    }
    try:
        if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
            raise ValueError("Explicit CUDA_VISIBLE_DEVICES='' required")
        import pyarrow as pa
        import pyarrow.parquet as pq
        import torch
        from omegaconf import OmegaConf
        from transformers import AutoTokenizer

        data = args.checkpoint / "data.pt"
        if (
            args.checkpoint.name != f"global_step_{args.parent_step}"
            or data.is_symlink()
            or data.stat().st_size > 65536
        ):
            raise ValueError("Unexpected parent data path/size")
        if sha(data) != args.data_sha256:
            raise ValueError("Parent data hash differs")
        if (args.checkpoint / "transfer_queue").exists():
            raise ValueError("Parent TransferQueue replay crosses task boundary")
        fsdp = json.loads((args.checkpoint / "actor/fsdp_config.json").read_text())
        if fsdp != {"FSDP_version": 1, "world_size": 2}:
            raise ValueError("Parent FSDP/world size differs")
        state = torch.load(data, map_location="cpu", weights_only=False)
        validate_state(state)
        old = pq.read_table(args.old_parquet).to_pylist()
        if len(old) != 1:
            raise ValueError("Old prepared dataset must have exactly one row")
        new = copy.deepcopy(old)
        new[0]["prompt"] = [
            {"role": "user", "content": "R20 distinct task CPU mechanism probe: write a new result file."}
        ]
        new[0]["data_source"] = "harbor/r20-distinct-mechanism-probe/train"
        new[0]["extra_info"]["sample_id"] = "r20-distinct-mechanism-probe"
        if new[0]["prompt"] == old[0]["prompt"]:
            raise ValueError("Probe task must differ")
        new_path = args.output_dir / "new-task.parquet"
        pq.write_table(pa.Table.from_pylist(new), new_path)
        tokenizer = AutoTokenizer.from_pretrained(str(args.model_tokenizer), local_files_only=True)
        config = OmegaConf.create(
            {
                "shuffle": False,
                "seed": 42,
                "dataloader_num_workers": 0,
                "max_prompt_length": 8192,
                "filter_overlong_prompts": True,
                "filter_overlong_prompts_workers": 1,
            }
        )
        result = probe_next_batch(state, new_path, config, tokenizer)
        if (
            result["raw_prompt"] != new[0]["prompt"]
            or result["data_source"] != new[0]["data_source"]
            or result["cuda_initialized"]
        ):
            raise ValueError("Native next batch did not yield the new task on CPU")
        if sha(data) != args.data_sha256:
            raise ValueError("Parent data changed during probe")
        report.update(
            passed=True,
            parent_step=args.parent_step,
            checkpoint=str(args.checkpoint),
            data_sha256=args.data_sha256,
            old_parquet_sha256=sha(args.old_parquet),
            new_parquet_sha256=sha(new_path),
            loader_state=state,
            transfer_queue_exists=False,
            fsdp=fsdp,
            native=result,
            plan=epoch_plan(args.parent_step, args.target_step),
            original_parent_unchanged=True,
            full_bitwise_data_replay_claimed=False,
            model_loaded=False,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["finished_at_unix"] = time.time()
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
