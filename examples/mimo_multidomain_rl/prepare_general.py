"""Cloud CPU preparation for both published General branches.

Keep original tools, tests, assets and verifier bytes. Only execution images and
the business assets' absolute root are materialized. No training is launched.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SOURCE_HASHES = {
    "config/agent/general/s3k.yaml": "175df84fccccdcfef256e1f57e6cbf33f20b4f097590aa990770842b59035ab6",
    "recipes/general/config/general_agent_loop.yaml": (
        "869e4be44d8ba40b954a322652206e23e8bf4ab15778be60c294ba5925ca1d64"
    ),
    "recipes/general/config/general.yaml": "32d1f61fd61b3dc3558442a47e90a1a3a5f2f3da78de02132e3826f6e9919ee8",
    "recipes/general/env_actor.py": "96096c394c91459f09c25a2866559f39e8c6c34c8cc4f52a123b76d03a4024a2",
    "recipes/general/general_agent/environment.py": "6a76a5c6ee0e1608fbf204139ec87a5052bdb06ffb40e6d397dfd84fdc2a9a04",
    "recipes/general/mcp_proxy.py": "68021d566fd59390f083030a8e3ebdb91f862307ced9ccacb2db94fe079820e4",
}
TOOLS = ["Bash", "Read", "Write", "Edit", "Grep", "Glob"]
MAPPING_SHA256 = "704ad2716d746430a805b9b1ac7c6725aea2117fd8e4823ebe9d339d0313ad58"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def modal_harness(original, *, run_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("Invalid owned General identity")
    if [tool["tool"] for tool in original["agent"]["tools"]] != TOOLS:
        raise ValueError("Original General base tool catalogue changed")
    result = copy.deepcopy(original)
    result["environment"].update(
        environment_class="uni_agent.tasks.mimo_reference.general_environment.GeneralEnvironment",
        app_name="mimo-reference-general",
        run_id=run_id,
        sandbox_timeout=1800,
    )
    # Credentials stay on the controller until trusted sidecar grading.
    env = result["environment"].get("env", {})
    if any("KEY" in name or name.startswith(("GA_JUDGE_", "JUDGE_")) for name in env):
        raise ValueError("Judge authentication cannot enter a task environment config")
    return result


def materialize_rows(rows, *, mapping, assets_root, known_agents, resolver):
    from uni_agent.tasks.mimo_reference.terminal_bench_environment import decode_tests_files

    runtime, receipts = [], []
    assets_root = assets_root.resolve()
    for row in rows:
        item = copy.deepcopy(row)
        instance = json.loads(item["extra_info"]["instance_json"])
        kind = instance.get("dataset_type")
        if kind not in {"terminal_bench", "general_agent"} or item.get("agent_name") not in known_agents:
            raise ValueError("Unknown published General branch or agent route")
        original_image = instance["docker_image"]
        mapped = mapping.get(original_image)
        if not mapped:
            raise ValueError("A General source image has no public mapping")
        instance["docker_image"] = resolver(mapped)
        changed = ["docker_image"]
        assets = {}
        if kind == "terminal_bench":
            files = decode_tests_files(instance)
            assets = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        else:
            relative = Path(instance["env_task_dir"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Business env_task_dir must be relative to the public asset root")
            task = (assets_root / relative).resolve()
            if not task.is_relative_to(assets_root) or not task.is_dir():
                raise ValueError("Original General business assets are not materialized")
            if not (task / "run_verify.py").is_file() or not (task / "verify.py").is_file():
                raise ValueError("Original business verifier programs are missing")
            for path in sorted(task.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Business asset symlinks are not admitted")
                if path.is_file():
                    assets[str(path.relative_to(task))] = sha(path)
            instance["env_task_dir"] = str(task)
            changed.append("env_task_dir")
        item["extra_info"]["instance_json"] = json.dumps(instance, ensure_ascii=False)
        runtime.append(item)
        receipts.append(
            {
                "task_id": instance["instance_id"],
                "dataset_type": kind,
                "source_image": original_image,
                "runtime_image": instance["docker_image"],
                "changed_instance_fields": changed,
                "asset_sha256": assets,
            }
        )
    return runtime, receipts


def preflight(args):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import yaml

    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    hashes = {name: sha(source / name) for name in SOURCE_HASHES}
    if hashes != SOURCE_HASHES:
        raise ValueError("Pinned General source byte identity changed")
    if sha(args.image_mapping) != MAPPING_SHA256:
        raise ValueError("Fixed public image mapping bytes changed")
    repository = Path(__file__).resolve().parents[2]
    extra_paths = [str(repository), str(source / "third_party/mimoagent-osr/src")]
    sys.path[:0] = [str(source), *extra_paths]
    bootstrap = importlib.import_module("uni_agent.tasks.mimo_reference.general_bootstrap")
    if args.judge_auth_file:
        os.environ["MIMO_GENERAL_JUDGE_AUTH_FILE"] = str(args.judge_auth_file.resolve())
    os.environ["MIMO_GENERAL_RUN_ID"] = args.run_id
    judge = bootstrap.configure_trusted_judge()
    bootstrap.install()
    original = yaml.safe_load((source / "config/agent/general/s3k.yaml").read_text())
    harness = modal_harness(original, run_id=args.run_id)
    harness_path = output / "general-modal-harness.yaml"
    harness_path.write_text(yaml.safe_dump(harness, sort_keys=False))
    registry = yaml.safe_load((source / "recipes/general/config/general_agent_loop.yaml").read_text())
    registry[0].update(
        mimoagent_config_path=str(harness_path),
        per_turn_max_tokens=4096,
        fail_on_env_setup_error=True,
        agent_thread_pool_size=2,
    )
    registry_path = output / "general-agent-loop.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False))
    mapping = {}
    for line in args.image_mapping.read_text().splitlines():
        pair = json.loads(line)
        mapping[pair["dataset_image"]] = pair["dockerhub_image"]
    from mimoagent.environments.utils import make_dataset_env

    from examples.mimo_multidomain_rl.prepare_webdev import dockerhub_digest

    paths, receipts, branches = {}, [], set()
    for split in ("train", "heldout"):
        table = pq.read_table(args.data / f"{split}.parquet")
        rows, images = materialize_rows(
            table.to_pylist(),
            mapping=mapping,
            assets_root=args.assets_root,
            known_agents={entry["name"] for entry in registry},
            resolver=dockerhub_digest,
        )
        for row in rows:
            instance = json.loads(row["extra_info"]["instance_json"])
            dataset = make_dataset_env(instance, **harness["environment"])
            # This exercises the original factory and registry, allocating nothing.
            if instance["dataset_type"] == "terminal_bench":
                assert dataset.env.sandbox is None
            else:
                assert not dataset.env._backends
            if split == "train":
                branches.add(instance["dataset_type"])
        target = output / f"{split}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), target)
        paths[split] = str(target)
        receipts.extend(images)
    if branches != {"terminal_bench", "general_agent"}:
        raise ValueError("General training must cover both published task branches")
    environment = {
        "MIMO_GENERAL_AGENT_LOOP_CONFIG": str(registry_path),
        "MIMO_GENERAL_RUN_ID": args.run_id,
        "MIMO_EXTRA_PYTHONPATH": os.pathsep.join(extra_paths),
    }
    os.environ.update(environment)
    cmd = [
        sys.executable,
        "-m",
        "verl.trainer.main_ppo",
        "--config-path",
        str(args.profile.resolve().parent),
        "--config-name",
        args.profile.stem,
        f"actor_rollout_ref.model.path={json.dumps(str(args.model.resolve()))}",
        f"data.train_files={json.dumps([paths['train']])}",
        f"data.val_files={json.dumps([paths['heldout']])}",
        f"trainer.experiment_name={json.dumps(args.run_id)}",
        "--cfg",
        "job",
        "--resolve",
    ]
    child = os.environ.copy()
    child.update(CUDA_VISIBLE_DEVICES="", PYTHONPATH=os.pathsep.join([str(source), *extra_paths]))
    result = subprocess.run(cmd, env=child, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError("General CPU Hydra composition failed")
    from omegaconf import OmegaConf

    config = OmegaConf.create(result.stdout)
    required = {
        "trainer.v1.trainer_mode": "sync",
        "actor_rollout_ref.actor.loss_agg_mode": "prompt-mean",
        "actor_rollout_ref.actor.fsdp_config.model_dtype": "fp32",
        "actor_rollout_ref.rollout.n": 8,
        "actor_rollout_ref.rollout.disable_log_stats": False,
        "algorithm.norm_adv_by_std_in_grpo": False,
        "algorithm.invalid_reward_value": -999,
        "algorithm.filter_groups.enable": True,
        "algorithm.length_penalty.enable": True,
    }
    for key, value in required.items():
        if OmegaConf.select(config, key) != value:
            raise ValueError("Required General semantic changed: " + key)
    env_vars = OmegaConf.select(config, "ray_kwargs.ray_init.runtime_env.env_vars")
    if any("KEY" in name for name in env_vars):
        raise ValueError("Judge keys must not enter composed Hydra config")
    (output / "resolved-general.yaml").write_text(result.stdout)
    return {
        "schema": "mimo.reference-general-cpu-preflight.v1",
        "status": "prepared-not-training-acceptance",
        "source_hashes": hashes,
        "image_mapping_sha256": sha(args.image_mapping),
        "recipe_sha256": sha(args.profile),
        "runtime_parquets": paths,
        "image_asset_receipts": receipts,
        "runtime_environment": environment,
        "judge": judge,
        "mcp_runtime": {
            "version": "1.29.0",
            "scope": "owned-sidecar-isolated-venv",
            "lock_sha256": sha(repository / "examples/mimo_multidomain_rl/general-mcp-runtime-requirements.txt"),
        },
        "required_semantics": required,
        "gpu_used": False,
        "task_pass": False,
        "remaining_gates": [
            "Actual MCP discovery and complete rendered policy prompt must fit context",
            "Real original verifier, non-infra rewards and both-branch valid GRPO updates",
            "Uniform reward groups may be filtered; no successful update is implied",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "data", "assets-root", "image-mapping", "model", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--judge-auth-file", type=Path)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("recipes") / "general.yaml")
    args = parser.parse_args()
    report = preflight(args)
    (args.output / "general-preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
