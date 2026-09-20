"""Run an explicit checkpoint manifest serially; preserve every attempt and reject partial evals."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path


def archive_error(path):
    try:
        with zipfile.ZipFile(path) as archive:
            if not any(x.endswith("data.pkl") for x in archive.namelist()):
                return "missing data.pkl"
    except (OSError, zipfile.BadZipFile) as exc:
        return str(exc)
    return None


def is_complete(root, tasks, n):
    try:
        receipt = json.loads((root / "validation.json").read_text())
        result = json.loads((root / "summary.json").read_text())["per_task"]
        return (
            receipt["status"] == "complete"
            and set(result) == set(tasks)
            and all(len(v) == n and all(x in (0, 1) for x in v) for v in result.values())
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def gpu_available(output):
    return output.strip().isdigit() and int(output.strip()) < 2000


def save(path, obj):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(obj, indent=2) + "\n")
    temporary.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path)
    args = ap.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    cfg = json.loads(manifest_bytes)
    root = Path(cfg["output"])
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / "queue.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    identity = root / "manifest.sha256"
    if identity.exists() and identity.read_text().strip() != digest:
        raise SystemExit("Manifest changed: choose a fresh output directory")
    identity.write_text(digest + "\n")
    save(root / "manifest.json", cfg)
    if cfg.get("probe_root"):
        deadline = time.monotonic() + 2 * 3600
        probe = Path(cfg["probe_root"])
        save(root / "gate.json", {"status": "waiting_probe", "probe": str(probe)})
        while True:
            if (probe / "validation.json").exists():
                try:
                    receipt = json.loads((probe / "validation.json").read_text())
                except (OSError, ValueError):
                    if time.monotonic() > deadline:
                        raise SystemExit("Probe receipt unreadable after 2h") from None
                    time.sleep(1)
                    continue
                if receipt.get("status") != "complete":
                    save(root / "gate.json", {"status": "probe_failed", "receipt": receipt})
                    raise SystemExit("Probe failed; no full evaluations started")
                save(root / "gate.json", {"status": "probe_passed"})
                break
            if time.monotonic() > deadline:
                save(root / "gate.json", {"status": "probe_timeout"})
                raise SystemExit("Probe timed out; no full evaluations started")
            time.sleep(30)
    source = Path(__file__).resolve().parent
    state = [
        {"label": item["label"], "checkpoint": item["checkpoint"], "status": "pending"} for item in cfg["versions"]
    ]
    save(root / "status.json", state)
    base = Path(cfg["base"])
    base_result = json.loads((base / "summary.json").read_text())
    tasks = sorted(base_result["per_task"])
    if len(tasks) != 78 or any(len(v) != 4 for v in base_result["per_task"].values()):
        raise SystemExit("Baseline must have all 78 tasks x4")
    if cfg.get("data_sha256"):
        actual = hashlib.sha256(Path(cfg["env"]["EVAL_DATA"]).read_bytes()).hexdigest()
        if actual != cfg["data_sha256"]:
            raise SystemExit("Evaluation data identity changed")
    if cfg.get("base_summary_sha256"):
        actual = hashlib.sha256((base / "summary.json").read_bytes()).hexdigest()
        if actual != cfg["base_summary_sha256"]:
            raise SystemExit("Baseline identity changed")
    for item, row in zip(cfg["versions"], state, strict=True):
        ck = Path(item["checkpoint"]) / "actor/model_world_size_1_rank_0.pt"
        error = archive_error(ck)
        if error:
            row.update(status="unavailable", error=error)
            save(root / "status.json", state)
            continue
        complete = next((p for p in sorted(root.glob(item["label"] + "-attempt*")) if is_complete(p, tasks, 4)), None)
        for attempt in range(1, 3):
            if complete:
                break
            dest = root / f"{item['label']}-attempt{attempt}"
            if dest.exists():
                continue
            row.update(status="waiting_gpu", output=str(dest))
            save(root / "status.json", state)
            deadline = time.monotonic() + 12 * 3600
            while True:
                query = subprocess.run(
                    ["nvidia-smi", "-i", str(cfg["gpu"]), "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if gpu_available(query.stdout):
                    break
                if time.monotonic() > deadline:
                    raise SystemExit("GPU unavailable after 12h; queue can be resumed")
                time.sleep(60)
            env = dict(
                {**os.environ, **cfg["env"]},
                EVAL_ROOT=str(dest),
                EVAL_RUN=item["run"],
                RESUME_FROM=item["checkpoint"],
                CUDA_VISIBLE_DEVICES=str(cfg["gpu"]),
                EVAL_N="4",
                EVAL_LIMIT="0",
                KEEP_GPU_PROCESS="1",
            )
            row.update(status="running", started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            save(root / "status.json", state)
            with (root / f"{item['label']}-attempt{attempt}.log").open("w") as log:
                result = subprocess.run(
                    ["bash", str(source / "eval_val_only.sh")], env=env, stdout=log, stderr=subprocess.STDOUT
                )
            row["returncode"] = result.returncode
            if result.returncode == 0 and is_complete(dest, tasks, 4):
                complete = dest
            else:
                row.update(status="failed_or_incomplete")
                save(root / "status.json", state)
                # Do not retry an identical engine/configuration failure. Keep later versions pending.
                if (
                    not (dest / "summary.json").exists()
                    or json.loads((dest / "summary.json").read_text()).get("samples", 0) == 0
                ):
                    raise SystemExit("Zero-sample failure: stop queue for diagnosis")
        if complete:
            row.update(status="complete", output=str(complete))
            for name, command in [
                (
                    "pair.json",
                    [
                        "eval_pair_report.py",
                        str(base / "summary.json"),
                        str(complete / "summary.json"),
                        "--labels",
                        "base",
                        item["label"],
                    ],
                ),
                ("behavior.json", ["eval_behavior_report.py", f"base={base}", f"{item['label']}={complete}"]),
            ]:
                subprocess.run(
                    [cfg["python"], str(source / command[0]), *command[1:], "--out", str(complete / name)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
            row["comparison"] = json.loads((complete / "pair.json").read_text())["groups"]
        if not complete:
            row.update(status="exhausted")
        save(root / "status.json", state)
    lines = [
        "# Full checkpoint evaluation",
        "",
        "| Version | Status | Rate | Difference vs base | 95% CI |",
        "|---|---|---|---|---|",
    ]
    for row in state:
        stats = row.get("comparison", {}).get("all", {})
        lines.append(
            f"| {row['label']} | {row['status']} | {stats.get('other_rate', '—')} | "
            f"{stats.get('diff', '—')} | {stats.get('ci95', '—')} |"
        )
    (root / "report.md").write_text("\n".join(lines) + "\n")
    if any(x["status"] != "complete" for x in state):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
