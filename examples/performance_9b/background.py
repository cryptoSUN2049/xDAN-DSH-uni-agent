"""Detached, immutable-run CPU screening with explicit status and verification."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from examples.performance_9b.build_release import build, file_hash


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def verify(output):
    manifest = json.loads((output / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        path = output / name
        if path.parent != output or path.stat().st_size != expected["bytes"] or file_hash(path) != expected["sha256"]:
            raise ValueError(f"output verification failed: {name}")
    for source, item in manifest["statistics"].items():
        counts = item["counts"]
        if counts["input_rows"] != sum(counts.get(k, 0) for k in ("screened", "excluded", "quarantine", "duplicate")):
            raise ValueError(f"count conservation failed: {source}")
    return manifest


def render_report(manifest):
    lines = [
        "# 数据结构筛选报告",
        "",
        "状态：筛选产物已验收；尚未通过训练准入。",
        "",
        "| 来源 | 输入 | 结构候选 | 隔离 | 排除 | 重复 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for source, item in manifest["statistics"].items():
        c = item["counts"]
        lines.append(
            "| "
            + source
            + " | "
            + " | ".join(str(c.get(k, 0)) for k in ("input_rows", "screened", "quarantine", "excluded", "duplicate"))
            + " |"
        )
    for pool, result in manifest["sampling"].items():
        lines += [
            "",
            f"## {pool}",
            "",
            f"关联任务组件：{result['unique_prompt_groups']}；选中组件：{result['selected_groups']}。",
            "",
            "领域分布：" + json.dumps(result["group_domains"], ensure_ascii=False),
            "",
            "配额缺口：" + json.dumps(result["quota_deficits"], ensure_ascii=False),
        ]
    lines += ["", "## 限制", ""] + ["- " + x for x in manifest["limitations"]]
    return "\n".join(lines) + "\n"


def run(run_dir):
    status = {"state": "PREFLIGHT", "pid": os.getpid(), "started_at": time.time(), "training_ready": False}
    mutex, stopped = threading.Lock(), threading.Event()

    def update(**values):
        with mutex:
            status.update(values, heartbeat_at=time.time())
            write_json(run_dir / "status.json", status)

    def heartbeat():
        while not stopped.wait(10):
            update()

    def interrupted(signum, frame):
        raise RuntimeError(f"interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    update()
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        config = json.loads((run_dir / "config.json").read_text())
        total = 0
        for source in config["sources"]:
            path = Path(source["path"])
            if not source.get("sha256") or file_hash(path) != source["sha256"]:
                raise ValueError(f"missing/mismatched source SHA256: {source['repo']}")
            total += path.stat().st_size
        required = max(10 * 1024**3, total * 4)
        free = shutil.disk_usage(run_dir).free
        if free < required:
            raise RuntimeError(f"insufficient filesystem space: free={free}, required={required}")
        update(state="PROCESSING", source_bytes=total, filesystem_free_bytes=free, required_free_bytes=required)
        build(config, run_dir / "output")
        update(state="VERIFYING")
        manifest = verify(run_dir / "output")
        (run_dir / "report.md").write_text(render_report(manifest))
        update(state="SUCCEEDED", finished_at=time.time(), sampling=manifest["sampling"])
        return 0
    except Exception as exc:
        traceback.print_exc()
        update(state="FAILED", finished_at=time.time(), error=str(exc))
        return 1
    finally:
        stopped.set()
        thread.join()


def start(config_path, run_dir):
    config = json.loads(config_path.read_text())
    for source in config["sources"]:
        source["path"] = str(Path(source["path"]).resolve())
        if not source.get("sha256"):
            raise ValueError(f"source SHA256 required: {source['repo']}")
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json(run_dir / "config.json", config)
    code = run_dir / "code" / "examples" / "performance_9b"
    code.mkdir(parents=True)
    for path in Path(__file__).parent.glob("*.py"):
        shutil.copy2(path, code / path.name)
    write_json(run_dir / "code-manifest.json", {p.name: file_hash(p) for p in code.glob("*.py")})
    write_json(run_dir / "status.json", {"state": "STARTING", "heartbeat_at": time.time(), "training_ready": False})
    env = os.environ.copy()
    env["PYTHONPATH"] = str(run_dir / "code")
    env["PYTHONNOUSERSITE"] = "1"
    try:
        with (run_dir / "process.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-u", "-m", "examples.performance_9b.background", "worker", "--run-dir", str(run_dir)],
                cwd=run_dir / "code",
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        (run_dir / "pid").write_text(str(process.pid) + "\n")
    except Exception as exc:
        write_json(run_dir / "status.json", {"state": "FAILED", "error": str(exc), "training_ready": False})
        raise
    return {"pid": process.pid, "run_dir": str(run_dir)}


def read_status(run_dir):
    value = json.loads((run_dir / "status.json").read_text())
    value["heartbeat_age_seconds"] = round(time.time() - value.get("heartbeat_at", 0), 1)
    if value["state"] not in ("SUCCEEDED", "FAILED"):
        pid_path = run_dir / "pid"
        pid = value.get("pid") or (int(pid_path.read_text()) if pid_path.exists() else None)
        if pid:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                value["state"] = "INTERRUPTED"
        if value["heartbeat_age_seconds"] > 60:
            value["heartbeat_stale"] = True
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "status", "worker"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if args.command == "worker":
        return run(run_dir)
    if args.command == "start":
        if args.config is None:
            parser.error("start requires --config")
        result = start(args.config, run_dir)
    else:
        result = read_status(run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
