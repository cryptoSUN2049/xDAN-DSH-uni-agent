"""Materialize the shared eval set (eval-set-v1, 78 tasks) as Harbor task dirs + parquet.

    python examples/harbor_opd_rl/prepare_eval_set.py --out /workspace/.../data-eval-set-v1

The eval tasks are exactly the ones the training data stage *excludes* (reserved) and
mostly lack training audits, so 10_data.sh cannot build them; this script reads the
frozen list from the Full repo, unpacks only those tasks from their runtime-v1
archives, applies the same docker_image rules as 10_data.sh (so tasks run as they did
in the audit), and writes <out>/eval/harbor_tasks-eval.parquet plus selection.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path

SOURCES = {"swe": "swe-rebench-v2-fv", "terminal-lego": "terminal-lego-15k"}


def _norm(image: str) -> str:
    for prefix in ("docker.io/library/", "docker.io/"):
        if image.startswith(prefix):
            return image[len(prefix) :]
    return image


def strip_docker_image(task_dir: Path, strip_prefixes: tuple[str, ...] = ("terminal-lego/",)) -> str | None:
    """Same rule as 10_data.sh: drop an unpullable alias or a docker_image equal to the
    Dockerfile's FROM, so Harbor builds environment/Dockerfile (whose extra layers the
    verifier needs). Returns the reason, or None when the task is left as is."""
    toml_path, dockerfile = task_dir / "task.toml", task_dir / "environment" / "Dockerfile"
    text = toml_path.read_text()
    m = re.search(r'^docker_image\s*=\s*"([^"]+)"\s*$', text, re.M)
    if not (m and dockerfile.exists()):
        return None
    image = m.group(1)
    base = re.search(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", dockerfile.read_text(), re.M | re.I)
    if image.startswith(strip_prefixes):
        reason = "alias"
    elif base and _norm(base.group(1)) == _norm(image):
        reason = "base-image"
    else:
        return None
    note = f"# docker_image {image} removed by prepare_eval_set.py ({reason}); built from environment/Dockerfile\n"
    toml_path.write_text(text[: m.start()] + note + text[m.end() :])
    return reason


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="gump2049/xDAN-Harbor-Stage1-Tasks-Full")
    ap.add_argument("--eval-set", default="eval-set-v1")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    from huggingface_hub import hf_hub_download, snapshot_download

    local = args.out / "repo"
    selected_path = hf_hub_download(args.repo, f"{args.eval_set}/selected.json", repo_type="dataset", local_dir=local)
    selected = json.load(open(selected_path))
    wanted = {(SOURCES[t["source"]], t["task"]): t for t in selected["tasks"]}
    index = hf_hub_download(args.repo, "index/tasks.jsonl", repo_type="dataset", local_dir=local)
    rows = {}
    for line in open(index):
        r = json.loads(line)
        if (r["source"], r["task"]) in wanted:
            rows[(r["source"], r["task"])] = r
    missing = sorted(set(wanted) - set(rows))
    if missing:
        raise SystemExit(f"{len(missing)} eval tasks not in index: {missing[:5]}")

    batches: dict[str, set[str]] = {}
    for r in rows.values():
        batch_root, name = r["task_dir"].rsplit("/runtime-v1/", 1)[0], r["task_dir"].rsplit("/", 1)[1]
        batches.setdefault(batch_root, set()).add(name)
    snapshot_download(
        args.repo,
        repo_type="dataset",
        local_dir=local,
        allow_patterns=[f"{b}/runtime-v1.tar.gz" for b in batches] + [f"{b}/runtime-v1/*" for b in batches],
    )
    for batch_root, names in batches.items():
        if all((local / batch_root / "runtime-v1" / n).is_dir() for n in names):
            continue
        with tarfile.open(local / batch_root / "runtime-v1.tar.gz") as tf:
            members = [m for m in tf if m.name.split("/")[1:2] and m.name.split("/")[1] in names]
            tf.extractall(local / batch_root, members=members, filter="data")
        print("unpacked", len(names), "tasks from", batch_root)

    task_root = args.out / "tasks-eval"
    shutil.rmtree(task_root, ignore_errors=True)
    task_root.mkdir(parents=True)
    stripped = Counter()
    for (source, task), r in sorted(rows.items()):
        dst = task_root / f"{source}__{task}"
        shutil.copytree(local / r["task_dir"], dst)
        reason = strip_docker_image(dst)
        if reason:
            stripped[f"{source}:{reason}"] += 1
    print("tasks", len(rows), "docker_image stripped", dict(stripped))

    subprocess.run(
        [sys.executable, "-m", "uni_agent.tasks.harbor.preprocess", "--task-root", str(task_root)]
        + ["--local-save-dir", str(args.out / "eval")],
        check=True,
        cwd=os.environ.get("REPO_ROOT", "."),
    )
    parquet = next((args.out / "eval").glob("*.parquet"))
    (args.out / "selection.json").write_text(
        json.dumps(
            {
                "repo": args.repo,
                "eval_set": args.eval_set,
                "frozen_at": selected.get("frozen_at"),
                "tasks": [
                    {"source": s, "task": t, **{k: wanted[(s, t)].get(k) for k in ("base_successes", "base_graded")}}
                    for (s, t) in sorted(rows)
                ],
                "parquet": str(parquet),
                "docker_image_stripped": dict(stripped),
            },
            indent=1,
        )
    )
    print("parquet", parquet)


if __name__ == "__main__":
    main()
