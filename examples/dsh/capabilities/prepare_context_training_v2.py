"""Prepare independent v2 online-RL train/dev inputs; no GPU or training is started."""

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from examples.dsh.capabilities.context_tasks_v2 import VERIFIER_ID
from examples.dsh.capabilities.context_tasks_v2 import prepare as prepare_cases
from examples.dsh.capabilities.context_verifier_v2 import bundle_digest
from examples.dsh.evolution_verifier import _sha256_bytes


def prepare(*, repository_root, output_dir, run_id, runtime_executable, environment_digest, runner_python, run_root):
    root, output, run = Path(repository_root).resolve(), Path(output_dir).absolute(), Path(run_root).absolute()
    runtime, python = Path(runtime_executable).resolve(), Path(runner_python).absolute()
    if root != Path(__file__).resolve().parents[3]:
        raise ValueError("Run from the selected repository checkout")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise ValueError("Invalid run identity")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be a new private directory")
    if (
        run.exists()
        or run.is_symlink()
        or run.resolve().is_relative_to(output.resolve())
        or output.resolve().is_relative_to(run.resolve())
    ):
        raise ValueError("Run must be new and independent of preparation output")
    if (
        not runtime.is_file()
        or not os.access(runtime, os.X_OK)
        or _sha256_bytes(runtime.read_bytes()) != environment_digest
    ):
        raise ValueError("Pinned runtime digest mismatch")
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import json;from importlib.metadata import version;"
            "from deepseek_harness_runtime import bundled_runtime_path;"
            "print(json.dumps(dict(path=str(bundled_runtime_path()),"
            "sdk=version('deepseek-harness-sdk'),runtime=version('deepseek-harness-runtime-bin'))))",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    installed = json.loads(probe.stdout)
    if (
        Path(installed["path"]).resolve() != runtime
        or installed["sdk"] != "0.1.3a2"
        or installed["runtime"] != "0.1.3a2"
    ):
        raise ValueError("Requires selected SDK/runtime 0.1.3a2")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    if output.stat().st_uid != os.getuid() or stat.S_IMODE(output.stat().st_mode) != 0o700:
        raise ValueError("Output must enforce private owner permissions")
    cases = prepare_cases(output / "cases")
    counts = {}
    for split in ("train", "validation"):
        rows = []
        for case in cases:
            if case["metadata"]["split"] != split:
                continue
            metadata = {**case["metadata"], "environment_digest": environment_digest}
            rows.append(
                dict(
                    data_source="dsh/context-v2/" + run_id,
                    uid=run_id + "-" + metadata["structure_id"],
                    agent_name="task",
                    prompt=case["messages"],
                    extra_info={"tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": metadata}}},
                )
            )
        counts[split] = len(rows)
        pq.write_table(pa.Table.from_pylist(rows), output / (split + ".parquet"))
    config_path = root / "examples/dsh/evolution_task_config_v3_live.yaml"
    config = yaml.safe_load(config_path.read_text())[0]
    config.update(
        environment_digest=environment_digest,
        verifier_id=VERIFIER_ID,
        verifier_version="2",
        verifier_code_digest=bundle_digest(),
        workdir=str(output),
        result_root=str(run / "artifacts/results"),
        verifier_command=[str(python), "-m", "examples.dsh.capabilities.context_verifier_v2"],
    )
    config["agent"].update(runner_python=str(python), default_workdir=str(output), patches=[], run_timeout=900)
    config["sandbox"]["runtime_timeout"] = 900
    config["agent"]["model"].update(max_total_tokens=8192, max_tokens_per_turn=2048)
    (output / "task.yaml").write_text(yaml.safe_dump([config], sort_keys=False))
    environment = dict(
        VAL_ONLY="True",
        RESUME_MODE="disable",
        DSH_RUNTIME_MODE="exe",
        TRAINER_MODE="sync",
        DATA_ROOT=str(output),
        TRAIN_FILE=str(output / "train.parquet"),
        TEST_FILE=str(output / "validation.parquet"),
        TASK_CONFIG=str(output / "task.yaml"),
        RUN_ROOT=str(run),
        PYTHON_BIN=str(python),
        DSH_VENV=str(python.parent.parent),
        PYTHONPATH=f"{root}:{root / 'verl'}",
        TRAIN_MAX_SAMPLES="12",
        VAL_MAX_SAMPLES="4",
        TRAIN_BATCH_SIZE="1",
        PPO_MINI_BATCH_SIZE="1",
        ROLLOUT_N="4",
        VAL_ROLLOUT_N="1",
        TOTAL_TRAINING_STEPS="2",
        SAVE_FREQ="1",
        TEST_FREQ="1",
        DATA_SHUFFLE="True",
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
        CKPTS_DIR=f"/workspace/uni-agent-g1/checkpoint/{run_id}",
        AGENT_LOG_DIR=str(run / "agent-logs"),
        DSH_TRACE_ROOT=str(run / "artifacts/traces"),
        DSH_RESULT_ROOT=str(run / "artifacts/results"),
        ROLLOUT_DATA_DIR=str(run / "rollouts"),
        VALIDATION_DATA_DIR=str(run / "validation"),
        PROJECT_NAME="dsh-context-v2",
        EXP_NAME=run_id,
    )
    (output / "training.env").write_text(
        "".join(f"export {key}={shlex.quote(value)}\n" for key, value in environment.items())
    )
    sources = [
        root / "examples/dsh" / name for name in ("verifier.py", "evolution_verifier.py", "evolution_verifier_v2.py")
    ]
    sources.extend(
        Path(__file__).with_name(name)
        for name in ("context_tasks_v2.py", "context_verifier_v2.py", Path(__file__).name)
    )
    sources.extend([config_path, root / "deployment/versions/g1-deployment-lock.json"])
    inference_arguments = [
        "--data-path",
        str(output / "validation.parquet"),
        "--task-config",
        str(output / "task.yaml"),
        "--n",
        "1",
        "--limit",
        "4",
        "--dsh-strict-audit",
        "--require-result",
        "--dsh-trace-root",
        str(run / "artifacts/traces"),
        "--dsh-result-root",
        str(run / "artifacts/results"),
        "--log-dir",
        str(run / "agent-logs"),
        "--result-path",
        str(run / "result.json"),
        "--inference-evidence-path",
        str(run / "inference-evidence.json"),
    ]
    manifest = dict(
        schema="dsh.context-online-rl-preparation.v2",
        status="prepared-not-run",
        dataset_id=run_id,
        counts=counts,
        training_method="online-grpo",
        evaluation_visibility="public-development-not-hidden",
        runtime=dict(path=str(runtime), sha256=environment_digest, python=str(python), versions=installed),
        verifier_bundle=dict(id=VERIFIER_ID, version="2", sha256=bundle_digest()),
        sources={str(p.relative_to(root)): _sha256_bytes(p.read_bytes()) for p in sources},
        files={
            str(p.relative_to(output)): _sha256_bytes(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()
        },
        environment=environment,
        inference_arguments=inference_arguments,
        operator_required=[
            "Pin MODEL_PATH and review license; source training.env before the existing ops launcher.",
            "Default VAL_ONLY=True. Only after real reward-diversity diagnosis set VAL_ONLY=False.",
            "Use an owned-process wall-clock supervisor. Two steps sample a subset, not all 12 tasks.",
            "Do not use strict inference validation partition with train split rows.",
            "Independent reload needs a newly prepared bundle/run root and resume path override.",
        ],
    )
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    for path in output.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repository-root", "output-dir", "runtime-executable", "runner-python", "run-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("run-id", "environment-digest"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args())), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
