"""Prepare one runtime-grounded Tool query baseline; never starts GPU or DSH."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from examples.dsh.evolution_v3_live import (
    _LIVE_VERIFIER_CODE_PATHS,
    _bundle_identity,
    build_live_task_rows,
    load_live_scenarios,
)

PROMPT = (
    "Determine which capabilities are available through the current runtime Tool inventory. "
    "Use live runtime observations to discover a queryable interface and actually query the available capabilities. "
    "Do not modify runtime components or files, use bash, or claim a reward. "
    "Make at most one tool call per assistant turn, at most four tool calls and six turns. "
    "Report an evidence-supported conclusion. This is a runtime-grounded Tool query, not an open-ended discovery task."
)


def _sha(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(*, repository_root, output_dir, eval_id, runtime_executable, environment_digest, runner_python):
    root = Path(repository_root).resolve()
    output = Path(output_dir).absolute()
    runtime = Path(runtime_executable).resolve()
    python = Path(runner_python).absolute()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", eval_id):
        raise ValueError("Invalid eval identity")
    if not runtime.is_file() or _sha(runtime) != environment_digest:
        raise ValueError("Pinned runtime digest mismatch")
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be a new private directory")
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import json; from importlib.metadata import version; "
            "from deepseek_harness_runtime import bundled_runtime_path; "
            'print(json.dumps(dict(path=str(bundled_runtime_path()), sdk=version("deepseek-harness-sdk"), '
            'runtime=version("deepseek-harness-runtime-bin"))))',
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    installed = json.loads(probe.stdout)
    if Path(installed["path"]).resolve() != runtime:
        raise ValueError("Runner Python resolves a different runtime")
    source = root / "examples/dsh/evolution_v3_live_scenarios.jsonl"
    scenarios = load_live_scenarios(source, repository_root=root)
    selected = [scenario for scenario in scenarios if scenario["family_id"] == "runtime-grounding"]
    if len(selected) != 1:
        raise ValueError("Expected exactly one runtime-grounding scenario")
    bundle = _bundle_identity((*_LIVE_VERIFIER_CODE_PATHS, source), repository_root=root)
    patches = [str(root / "examples/dsh/evolution.patch.yml")]
    rows = build_live_task_rows(
        selected,
        repository_root=root,
        environment_digest=environment_digest,
        verifier_code_digest=bundle["sha256"],
        profile="sdk-minimal",
        patches=patches,
    )
    rows[0]["prompt"] = [{"role": "user", "content": PROMPT}]
    rows[0]["data_source"] = "dsh/capability-eval/" + eval_id
    rows[0]["uid"] = eval_id + "-runtime-grounding"
    rows[0]["agent_name"] = "task"
    config = yaml.safe_load((root / "examples/dsh/evolution_task_config_v3_live.yaml").read_text())[0]
    config.update(
        environment_digest=environment_digest,
        verifier_code_digest=bundle["sha256"],
        workdir=str(root),
        result_root=str(output / "artifacts/results"),
    )
    config["agent"].update(runner_python=str(python), default_workdir=str(root), patches=patches)
    config["agent"]["model"]["max_tokens_per_turn"] = 2048
    config["verifier_command"] = [
        str(python),
        "-m",
        "examples.dsh.evolution_v3_live_verifier",
        "--scenario-file",
        str(source),
    ]
    paths = dict(
        agent_log_dir=str(output / "agent-logs"),
        trace_root=str(output / "artifacts/traces"),
        result_root=str(output / "artifacts/results"),
        rollout_data_dir=str(output / "rollouts"),
        validation_data_dir=str(output / "validation"),
    )
    environment = dict(
        VAL_ONLY="True",
        RESUME_MODE="disable",
        DSH_RUNTIME_MODE="exe",
        TRAIN_FILE=str(output / "eval.parquet"),
        TEST_FILE=str(output / "eval.parquet"),
        TASK_CONFIG=str(output / "task.yaml"),
        RUN_ROOT=str(output),
        PROJECT_NAME="dsh-capability-eval",
        EXP_NAME=eval_id,
        PYTHON_BIN=str(python),
        TRAIN_MAX_SAMPLES="1",
        VAL_MAX_SAMPLES="1",
        ROLLOUT_N="1",
        VAL_ROLLOUT_N="1",
        AGENT_LOG_DIR=paths["agent_log_dir"],
        DSH_TRACE_ROOT=paths["trace_root"],
        DSH_RESULT_ROOT=paths["result_root"],
        ROLLOUT_DATA_DIR=paths["rollout_data_dir"],
        VALIDATION_DATA_DIR=paths["validation_data_dir"],
    )
    manifest = dict(
        schema="dsh.capability-eval-preparation.v1",
        status="prepared",
        eval_id=eval_id,
        scope="runtime-grounded Tool capability query; not open-ended autonomous discovery",
        limitations=[
            "Original trusted v3 rubric retained; no new independent problem instance.",
            "Shared eval.parquet train input is a VAL_ONLY loader placeholder, not a training split.",
            "Verifier checks a live listed Tool-provider query; not full final-answer correctness.",
            "Preparation validates the runtime selection now; recheck runtime and source hashes before execution.",
        ],
        runtime=dict(path=str(runtime), sha256=environment_digest, python=str(python), versions=installed),
        verifier_bundle=bundle,
        patches=[dict(path=p, sha256=_sha(Path(p))) for p in patches],
        metadata=rows[0]["extra_info"]["tools_kwargs"]["task"]["metadata"],
        paths=paths,
        rollout=dict(train_n=1, validation_n=1),
        environment=environment,
    )
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    actual = output.lstat()
    if not stat.S_ISDIR(actual.st_mode) or actual.st_uid != os.getuid() or stat.S_IMODE(actual.st_mode) != 0o700:
        raise ValueError("Output filesystem must enforce private owner permissions")

    def write(name, data):
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)

    write("task.yaml", yaml.safe_dump([config], sort_keys=False).encode())
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows), sink)
    write("eval.parquet", sink.getvalue().to_pybytes())
    manifest["files"] = {name: _sha(output / name) for name in ("task.yaml", "eval.parquet")}
    write("run-manifest.json", (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repository-root", "output-dir", "runtime-executable", "runner-python"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("eval-id", "environment-digest"):
        parser.add_argument("--" + name, required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
