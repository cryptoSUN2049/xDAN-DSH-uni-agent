"""Prepare/check/launch one fixed diagnostic memory family with the existing sync trainer."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[3]
AF = "actor_rollout_ref.rollout.custom.agent_framework."


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def revision(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def deployment_lock():
    return json.loads((ROOT / "deployment/versions/g1-deployment-lock.json").read_text())


def runtime_probe(python, runtime):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "RAY_ADDRESS")}
    env["CUDA_VISIBLE_DEVICES"] = ""
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import json;from importlib.metadata import version;"
            "from deepseek_harness_runtime import bundled_runtime_path;"
            "print(json.dumps(dict(path=str(bundled_runtime_path()),"
            "sdk=version('deepseek-harness-sdk'),runtime=version('deepseek-harness-runtime-bin'))))",
        ],
        cwd="/tmp",
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    installed = json.loads(probe.stdout)
    if Path(installed["path"]).resolve() != runtime or any(installed[k] != "0.1.3a2" for k in ("sdk", "runtime")):
        raise ValueError("Requires selected SDK/runtime 0.1.3a2")
    return installed


def prepare(
    *,
    output_dir,
    run_root,
    run_id,
    runtime_executable,
    runner_python,
    model_path,
    model_revision,
    family="constraints",
    mode="val",
):
    if mode not in ("val", "train") or family not in ("constraints", "updates"):
        raise ValueError("Only val/train and fixed diagnostic families are supported")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}", run_id):
        raise ValueError("Invalid run identity")
    if not re.fullmatch(r"[0-9a-f]{40}", model_revision):
        raise ValueError("Model revision must be an explicit commit identity")
    output, run = Path(output_dir).absolute(), Path(run_root).absolute()
    runtime, python, model = (
        Path(runtime_executable).resolve(),
        Path(runner_python).absolute(),
        Path(model_path).resolve(),
    )
    checkpoint = Path("/workspace/uni-agent-g1/checkpoint") / run_id
    ray = Path("/tmp") / ("dsh-m-" + hashlib.sha256(run_id.encode()).hexdigest()[:12])
    for path in (output, run, checkpoint, ray):
        if path.exists() or path.is_symlink():
            raise ValueError("Requires new private paths")
    if run.resolve().is_relative_to(output.resolve()) or output.resolve().is_relative_to(run.resolve()):
        raise ValueError("Output and run must be independent")
    lock = deployment_lock()
    if model_revision != lock["student"]["revision"]:
        raise ValueError("Student revision must match deployment lock")
    if not os.access(runtime, os.X_OK) or digest(runtime) != lock["dsh"]["runtime_binary_sha256"]:
        raise ValueError("Runtime pin mismatch")
    head, verl_head = revision(ROOT), revision(ROOT / "verl")
    if verl_head != lock["integration"]["verl_revision"]:
        raise ValueError("VERL pin mismatch")
    installed = runtime_probe(python, runtime)
    model_hashes = {str(model / name): digest(model / name) for name in ("config.json", "tokenizer_config.json")}
    output.mkdir(parents=True, mode=0o700)
    # These are scheduling records. Private A/B task prompts/fixtures are created by StageSpec.
    for split in ("train", "validation"):
        row = dict(
            data_source="dsh/memory-fixed-diagnostic/" + family,
            uid=run_id + "-" + split,
            agent_name="task",
            prompt=[dict(role="user", content="Execute the trusted memory chain.")],
            extra_info=dict(
                tools_kwargs=dict(
                    task=dict(name="dsh_architecture", metadata=dict(family=family, split=split, diagnostic_only=True))
                )
            ),
        )
        pq.write_table(pa.Table.from_pylist([row]), output / (split + ".parquet"))
    # Ops requires a task file; actual execution always substitutes a private StageSpec file.
    template = ROOT / "examples/dsh/evolution_task_config_v3_live.yaml"
    (output / "task.yaml").write_text(yaml.safe_dump(yaml.safe_load(template.read_text()), sort_keys=False))
    env = dict(
        HOME="/root",
        LANG="C.UTF-8",
        PATH=f"{python.parent}:/usr/local/bin:/usr/bin:/bin",
        PYTHONPATH=f"{ROOT}:{ROOT / 'verl'}",
        PYTHON_BIN=str(python),
        DSH_VENV=str(python.parent.parent),
        CUDA_VISIBLE_DEVICES="0",
        DSH_RUNTIME_MODE="exe",
        HF_HUB_OFFLINE="1",
        WANDB_MODE="disabled",
        PYTHONUNBUFFERED="1",
        OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2",
        RAY_TMPDIR=str(ray),
        MODEL_PATH=str(model),
        MODEL_ID="Qwen/Qwen3-4B",
        MODEL_LICENSE_APPROVED="1",
        VAL_ONLY="True" if mode == "val" else "False",
        RESUME_MODE="disable",
        RESUME_FROM_PATH="",
        TRAINER_MODE="sync",
        DATA_ROOT=str(output),
        TRAIN_FILE=str(output / "train.parquet"),
        TEST_FILE=str(output / "validation.parquet"),
        TASK_CONFIG=str(output / "task.yaml"),
        RUN_ROOT=str(run),
        CKPTS_DIR=str(checkpoint),
        TRAIN_MAX_SAMPLES="1",
        VAL_MAX_SAMPLES="1",
        TRAIN_BATCH_SIZE="1",
        PPO_MINI_BATCH_SIZE="1",
        ROLLOUT_N="4",
        VAL_ROLLOUT_N="1",
        TOTAL_TRAINING_STEPS="1",
        SAVE_FREQ="1",
        TEST_FREQ="1",
        DATA_SHUFFLE="False",
        LOW_VRAM="1",
        LORA_RANK="16",
        LORA_ALPHA="16",
        SAVE_LORA_ONLY="False",
        ROLLOUT_CPU_OFFLOAD_GB="0",
        ROLLOUT_LAYERED_SUMMON="False",
        ACTOR_PARAM_OFFLOAD="True",
        ACTOR_OPTIMIZER_OFFLOAD="True",
        MAX_PROMPT_LENGTH="8192",
        MAX_RESPONSE_LENGTH="8192",
        PPO_MAX_TOKEN_LEN_PER_GPU="16384",
        GPU_MEMORY_UTILIZATION="0.30",
        ROLLOUT_MAX_NUM_SEQS="1",
        GATEWAY_COUNT="1",
        CONCURRENCY="1",
        AGENT_LOG_DIR=str(run / "agent-logs"),
        DSH_TRACE_ROOT=str(run / "unused-global-traces"),
        DSH_RESULT_ROOT=str(run / "unused-global-results"),
        ROLLOUT_DATA_DIR=str(run / "rollouts"),
        VALIDATION_DATA_DIR=str(run / "validation"),
        PROJECT_NAME="dsh-memory-resident",
        EXP_NAME=run_id,
    )
    operator = dict(
        root=str(run / "chains"),
        runner_python=str(python),
        runtime_executable=str(runtime),
        environment_digest=digest(runtime),
        checkpoint_identity=model_revision,
        family=family,
    )
    overrides = {
        AF + "framework_class_fqn": "uni_agent.framework.memory_chain.NativeMemoryFramework",
        AF + "memory_run_id": run_id,
        AF + "memory_operator": operator,
        AF + "agent_runners.task.trajectory_selection": "all",
        AF + "trajectory_postprocessor_fqn": None,
        AF + "trajectory_postprocessor_kwargs": None,
        AF + "trajectory_postprocessor_pass_context": False,
    }
    # JSON objects are not Hydra dictionaries (quoted keys are illegal); emit leaves instead.
    tail = []
    for key, value in overrides.items():
        if key.endswith("memory_operator"):
            tail.extend("++" + key + "." + k + "=" + json.dumps(v) for k, v in value.items())
        else:
            tail.append("++" + key + "=" + json.dumps(value))
    tail.extend(["trainer.total_epochs=1", "trainer.test_freq=1", "trainer.default_local_dir=" + str(checkpoint)])
    command = ["bash", str(ROOT / "examples/dsh/ops/launch_qwen3_4b_online_rl.sh"), "--foreground", *tail]
    sources = set((ROOT / "examples/dsh/capabilities").glob("memory*.py")) | {Path(__file__), template}
    sources.update((ROOT / "examples/dsh").glob("*.py"))
    for directory in (
        "uni_agent/framework",
        "uni_agent/tasks/dsh",
        "uni_agent/agents/dsh",
        "examples/dsh/memory_closed",
    ):
        sources.update((ROOT / directory).glob("*.py"))
    sources.update(
        ROOT / p
        for p in (
            "examples/dsh/train_qwen3_4b_online_rl.sh",
            "examples/dsh/ops/launch_qwen3_4b_online_rl.sh",
            "deployment/versions/g1-deployment-lock.json",
            "deployment/services/harbor_training_supervisor.py",
        )
    )
    (output / "training.env").write_text("".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items()))
    manifest = dict(
        schema="dsh.memory-resident-preparation.v1",
        status="prepared-not-run",
        mode=mode,
        dataset_kind="fixed-diagnostic-not-heldout",
        counts=dict(train=1, validation=1),
        training=False,
        learning_signal_verified=False,
        repository_root=str(ROOT),
        integration_head=head,
        integration_branch=subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        verl_head=verl_head,
        model_revision_declared=model_revision,
        model_files=model_hashes,
        runtime=dict(path=str(runtime), sha256=digest(runtime), installed=installed),
        sources={str(p): digest(p) for p in sorted(sources)},
        files={str(p): digest(p) for p in sorted(output.iterdir())},
        environment=env,
        command=command,
        wall_seconds=3600 if mode == "val" else 7200,
        caveats=[
            "Train/val are the same fixed family, not independently held out.",
            "All-equal B rewards imply zero GRPO signal; never manufacture failures.",
            "Model revision is declared identity; only listed model files are hashed.",
            "Legacy DSH v2 consumption auditor is not the memory-chain auditor.",
        ],
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for path in output.iterdir():
        path.chmod(0o600)
    return manifest


def check(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest["schema"] != "dsh.memory-resident-preparation.v1" or Path(manifest["repository_root"]) != ROOT:
        raise ValueError("Wrong manifest/checkout")
    if revision(ROOT) != manifest["integration_head"] or revision(ROOT / "verl") != manifest["verl_head"]:
        raise ValueError("Checkout changed; prepare a new run")
    for collection in ("sources", "files", "model_files"):
        for path, expected in manifest[collection].items():
            if digest(path) != expected:
                raise ValueError("Input/source/model changed: " + path)
    if digest(manifest["runtime"]["path"]) != manifest["runtime"]["sha256"]:
        raise ValueError("Runtime changed")
    env = manifest["environment"]
    runtime_probe(Path(env["PYTHON_BIN"]), Path(manifest["runtime"]["path"]))
    for key in ("RUN_ROOT", "CKPTS_DIR", "RAY_TMPDIR"):
        path = Path(env[key])
        if path.exists() or path.is_symlink():
            raise ValueError("Run path already exists")
    subprocess.run(
        [
            env["PYTHON_BIN"],
            "-c",
            "from uni_agent.framework.memory_chain import NativeMemoryFramework;"
            "from examples.dsh.capabilities.memory_training_stage import validate_stage_execution",
        ],
        cwd=env["DATA_ROOT"],
        env={**env, "CUDA_VISIBLE_DEVICES": ""},
        check=True,
        timeout=60,
    )
    return manifest


def launch(manifest_path):
    from deployment.services.harbor_training_supervisor import supervise

    manifest = check(manifest_path)
    if subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], text=True).strip():
        raise ValueError("GPU is in use; identify its owner first")
    env = manifest["environment"]
    run = Path(env["RUN_ROOT"])
    run.mkdir(mode=0o700)
    (run / "chains").mkdir(mode=0o700)
    Path(env["RAY_TMPDIR"]).mkdir(mode=0o700)
    (run / "memory-launch-plan.json").write_text(json.dumps(manifest, indent=2) + "\n")
    supervision = run / "supervision"
    supervision.mkdir(mode=0o700)
    result = supervise(
        manifest["command"],
        ROOT,
        env,
        supervision,
        lambda: None,
        wall_seconds=manifest["wall_seconds"],
        interval=5,
        grace=30,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    for key in (
        "output-dir",
        "run-root",
        "run-id",
        "runtime-executable",
        "runner-python",
        "model-path",
        "model-revision",
    ):
        prep.add_argument("--" + key, required=True)
    prep.add_argument("--mode", choices=("val", "train"), default="val")
    prep.add_argument("--family", choices=("constraints", "updates"), default="constraints")
    for name in ("check", "launch"):
        sub.add_parser(name).add_argument("manifest_path", type=Path)
    args = vars(parser.parse_args())
    action = args.pop("action")
    result = {"prepare": prepare, "check": check, "launch": launch}[action](**args)
    print(json.dumps(result, indent=2))
    if action == "launch" and result["exit_code"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
