"""gpu_orphans.sh: GPU processes marked KEEP_GPU_PROCESS=1 are never listed as orphans."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples/harbor_opd_rl/gpu_orphans.sh"


def fake_proc(tmp_path: Path, environs: dict[int, list[str] | None]) -> Path:
    # /proc/<pid>/environ is NUL-separated; None leaves the file out (unreadable environment).
    proc = tmp_path / "proc"
    for pid, env in environs.items():
        (proc / str(pid)).mkdir(parents=True)
        if env is not None:
            (proc / str(pid) / "environ").write_bytes(b"\0".join(e.encode() for e in env) + b"\0")
    return proc


def orphans(tmp_path: Path, environs: dict[int, list[str] | None]) -> tuple[list[str], str]:
    env = {**os.environ, "PROC_ROOT": str(fake_proc(tmp_path, environs)), "PIDS": " ".join(map(str, environs))}
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout.split(), result.stderr


def test_kept_processes_are_not_orphans(tmp_path):
    listed, kept = orphans(
        tmp_path,
        {
            101: ["PATH=/usr/bin", "KEEP_GPU_PROCESS=1"],  # another session's vllm serve
            102: ["PATH=/usr/bin", "KEEP_GPU_PROCESS=1", "VLLM_X=1"],  # its EngineCore child
            201: ["PATH=/usr/bin", "RAY_ADDRESS=local"],  # a leftover of our own run
            202: None,  # environment unreadable: treated as an orphan, as before the filter
        },
    )
    assert listed == ["201", "202"]
    assert "keep 101" in kept and "keep 102" in kept


def test_only_the_exact_marker_counts(tmp_path):
    listed, _ = orphans(
        tmp_path,
        {301: ["KEEP_GPU_PROCESS=0"], 302: ["XKEEP_GPU_PROCESS=1"], 303: ["KEEP_GPU_PROCESS=11"]},
    )
    assert listed == ["301", "302", "303"]


def test_no_gpu_processes(tmp_path):
    env = {**os.environ, "PROC_ROOT": str(tmp_path), "PIDS": ""}
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout == ""
