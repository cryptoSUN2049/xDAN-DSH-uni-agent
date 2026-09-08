"""Prepare a four-case strict inference bundle; separate execution owns its run evidence.

Fields: eval.parquet uses prompt + tools_kwargs.task metadata (split=test), task.yaml
pins independent context verifier identity and selected DSH runtime environment.
Source/hash manifest records the full imported verifier closure, fixture bytes and
runtime package versions. The existing Task supplies verifier_reward and receipts.
No training, runtime launch, model load or actual context switch occurs here.
"""

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from examples.dsh.capabilities.context_tasks import prepare as prepare_cases
from examples.dsh.capabilities.context_verifier import VERIFIER_ID, bundle_digest
from examples.dsh.prepare_capability_eval import _sha


def prepare(*, repository_root, output_dir, eval_id, runtime_executable, environment_digest, runner_python, run_root):
    root = Path(repository_root).resolve()
    output = Path(output_dir).resolve()
    run = Path(run_root).resolve()
    runtime = Path(runtime_executable).resolve()
    python = Path(runner_python).absolute()
    if root != Path(__file__).resolve().parents[3]:
        raise ValueError("Run the preparer from the selected repository checkout")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", eval_id):
        raise ValueError("Invalid eval identity")
    if output.exists() or Path(output_dir).is_symlink():
        raise ValueError("Output must be a new private directory")
    if run.exists() or Path(run_root).is_symlink() or run.is_relative_to(output) or output.is_relative_to(run):
        raise ValueError("Run root must be new and independent of preparation output")
    if not runtime.is_file() or not os.access(runtime, os.X_OK) or _sha(runtime) != environment_digest:
        raise ValueError("Pinned runtime executable digest mismatch")
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
    if installed["sdk"] != "0.1.3a2" or installed["runtime"] != "0.1.3a2":
        raise ValueError("Context baseline requires SDK/runtime 0.1.3a2")
    verifier_digest = bundle_digest()
    config_source = root / "examples/dsh/evolution_task_config_v3_live.yaml"
    config = yaml.safe_load(config_source.read_text())[0]
    config.update(
        environment_digest=environment_digest,
        verifier_id=VERIFIER_ID,
        verifier_version="1",
        verifier_code_digest=verifier_digest,
        workdir=str(output),
        result_root=str(run / "artifacts/results"),
        verifier_command=[str(python), "-m", "examples.dsh.capabilities.context_verifier"],
    )
    config["agent"].update(runner_python=str(python), default_workdir=str(output), patches=[])
    config["agent"]["model"].update(max_total_tokens=4096, max_tokens_per_turn=1024)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    info = output.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Output filesystem must enforce private owner permissions")
    cases = prepare_cases(output / "cases")
    rows = []
    for case in cases:
        metadata = {**case["metadata"], "split": "test", "environment_digest": environment_digest}
        case_id = metadata["task_id"].rsplit("/", 1)[-1]
        rows.append(
            {
                "data_source": "dsh/context-eval/" + eval_id,
                "uid": eval_id + "-" + case_id,
                "agent_name": "task",
                "prompt": case["messages"],
                "extra_info": {"tools_kwargs": {"task": {"name": "dsh_architecture", "metadata": metadata}}},
            }
        )
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist(rows), sink)
    (output / "eval.parquet").write_bytes(sink.getvalue().to_pybytes())
    (output / "task.yaml").write_text(yaml.safe_dump([config], sort_keys=False))
    for path in output.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    sources = [
        root / "examples/dsh" / name for name in ("verifier.py", "evolution_verifier.py", "evolution_verifier_v2.py")
    ]
    sources.extend(
        Path(__file__).parent / name for name in ("context_verifier.py", "context_tasks.py", "prepare_context_eval.py")
    )
    sources.extend([config_source, root / "examples/dsh/prepare_capability_eval.py"])
    arguments = [
        "--data-path",
        str(output / "eval.parquet"),
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
    manifest = {
        "schema": "dsh.context-eval-preparation.v1",
        "status": "prepared-not-run",
        "eval_id": eval_id,
        "training": False,
        "prompt_revision": cases[0]["metadata"]["prompt_revision"],
        "split": "test",
        "instances": 4,
        "context_switch_verified": False,
        "scope": "file-evidence-only; two diagnostic families, no heldout-generalization claim",
        "runtime": {"path": str(runtime), "sha256": environment_digest, "python": str(python), "versions": installed},
        "verifier_bundle": {"sha256": verifier_digest, "id": VERIFIER_ID, "version": "1"},
        "sources": {str(path.relative_to(root)): _sha(path) for path in sources},
        "files": {str(path.relative_to(output)): _sha(path) for path in sorted(output.rglob("*")) if path.is_file()},
        "execution_root": str(run),
        "inference_arguments": arguments,
        "environment": {"DSH_RUNTIME_MODE": "exe", "PYTHONPATH": f"{root}:{root / 'verl'}"},
        "operator_required": [
            "Create the independent run root before launch.",
            "Pin and pass --model-path and engine/GPU arguments explicitly.",
            "Recheck source/runtime/file hashes and GPU occupancy before launch.",
            "Run with selected runner Python from repository root; never use training launch script.",
        ],
    }
    path = output / "preparation-manifest.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repository-root", "output-dir", "runtime-executable", "runner-python", "run-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("eval-id", "environment-digest"):
        parser.add_argument("--" + name, required=True)
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
