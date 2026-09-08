"""Prepare public T2 data and a baseline configuration; never starts training."""

import argparse
import json
import os
import stat
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from examples.dsh.capability_tasks.log_tool.task_bundle import VERIFIER_ID, build_rows
from examples.dsh.verifier import _require_digest, _sha256_bytes


def prepare(root, output, runner_python, runtime_digest):
    root, output = Path(root).resolve(), Path(output).absolute()
    _require_digest(runtime_digest, label="runtime_digest")
    if output.exists() or output.is_symlink():
        raise ValueError("T2 output must be new")
    probe = subprocess.run(
        [
            str(runner_python),
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
    if _sha256_bytes(Path(installed["path"]).read_bytes()) != runtime_digest:
        raise RuntimeError("Installed T2 runtime hash differs from pin")
    patches = [str(root / "examples/dsh/evolution.patch.yml")]
    rows, bundle = build_rows(root, environment_digest=runtime_digest, patches=patches)
    config = yaml.safe_load((root / "examples/dsh/evolution_task_config_v3_live.yaml").read_text())[0]
    config.update(
        environment_digest=runtime_digest,
        verifier_id=VERIFIER_ID,
        verifier_version="1",
        verifier_code_digest=bundle["sha256"],
        workdir=str(root),
        result_root=str(output / "artifacts/results"),
        verifier_command=[str(runner_python), "-m", "examples.dsh.capability_tasks.log_tool.verifier_cli"],
    )
    config["agent"].update(runner_python=str(runner_python), default_workdir=str(root), patches=patches)
    config["agent"]["model"]["max_tokens_per_turn"] = 4096
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    info = output.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("T2 output filesystem must enforce private owner permissions")

    def write(name, data):
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)

    counts = {}
    for split in ("train", "validation"):
        selected = [r for r in rows if r["extra_info"]["tools_kwargs"]["task"]["metadata"]["split"] == split]
        counts[split] = len(selected)
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(selected), sink)
        write(split + ".parquet", sink.getvalue().to_pybytes())
    write("task.yaml", yaml.safe_dump([config], sort_keys=False).encode())
    environment = dict(
        VAL_ONLY="True",
        RESUME_MODE="disable",
        DSH_RUNTIME_MODE="exe",
        TRAIN_FILE=str(output / "train.parquet"),
        TEST_FILE=str(output / "validation.parquet"),
        TASK_CONFIG=str(output / "task.yaml"),
        RUN_ROOT=str(output),
        PYTHON_BIN=str(runner_python),
        TRAIN_MAX_SAMPLES="4",
        VAL_MAX_SAMPLES="1",
        TRAIN_BATCH_SIZE="1",
        ROLLOUT_N="4",
        VAL_ROLLOUT_N="1",
        TOTAL_TRAINING_STEPS="2",
        LOW_VRAM="1",
        ROLLOUT_CPU_OFFLOAD_GB="0",
        ROLLOUT_LAYERED_SUMMON="False",
        LORA_RANK="16",
        LORA_ALPHA="16",
        MAX_PROMPT_LENGTH="24576",
        MAX_RESPONSE_LENGTH="8192",
        PPO_MAX_TOKEN_LEN_PER_GPU="32768",
        GPU_MEMORY_UTILIZATION="0.30",
        ROLLOUT_MAX_NUM_SEQS="1",
        AGENT_LOG_DIR=str(output / "agent-logs"),
        DSH_TRACE_ROOT=str(output / "artifacts/traces"),
        DSH_RESULT_ROOT=str(output / "artifacts/results"),
        ROLLOUT_DATA_DIR=str(output / "rollouts"),
        VALIDATION_DATA_DIR=str(output / "validation"),
    )
    manifest = dict(
        schema="dsh.t2-preparation.v1",
        status="prepared-only",
        runtime=installed,
        runtime_digest=runtime_digest,
        verifier_bundle=bundle,
        counts=counts,
        evaluation_visibility="public-development-not-hidden",
        environment=environment,
        files={
            n: _sha256_bytes((output / n).read_bytes()) for n in ("task.yaml", "train.parquet", "validation.parquet")
        },
        patches={p: _sha256_bytes(Path(p).read_bytes()) for p in patches},
    )
    write("run-manifest.json", (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "output", "runner-python"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--runtime-digest", required=True)
    print(json.dumps(prepare(**vars(parser.parse_args())), sort_keys=True))


if __name__ == "__main__":
    main()
