"""Freeze local Harbor task contents and compare evaluation tasks to actual S2 training rows."""

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import tomllib


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_rows(path):
    rows = []
    for extra in pd.read_parquet(path).extra_info:
        meta = extra["tools_kwargs"]["task"]["metadata"]
        root = Path(meta["task_path"])
        instruction = (root / "instruction.md").read_text()
        tokens = re.findall(r"\w+", instruction.lower())
        shingles = {tuple(tokens[i : i + 7]) for i in range(max(0, len(tokens) - 6))}
        name = meta["instance_id"].rsplit("/", 1)[-1]
        name = re.sub(r"^\d+__", "", name)
        name = re.sub(r"^(swe-rebench-v2-fv|terminal-lego-15k)__", "", name)
        repo = re.sub(r"-\d+$", "", name) if re.search(r"__.+-\d+$", name) else None
        files = {}
        for file in sorted(root.rglob("*")):
            if file.is_file():
                files[file.relative_to(root).as_posix()] = digest(file.read_bytes())
        rows.append(
            {
                "id": meta["instance_id"],
                "basename": meta["instance_id"].rsplit("/", 1)[-1],
                "canonical_id": name,
                "repo": repo,
                "path": str(root),
                "instruction_hash": digest(" ".join(tokens).encode()),
                "shingles": shingles,
                "files": files,
                "task_config": tomllib.loads((root / "task.toml").read_text()),
            }
        )
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True, type=Path)
    ap.add_argument("--eval", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    train, evaluation = read_rows(args.train), read_rows(args.eval)
    duplicates = [k for k, n in collections.Counter(x["basename"] for x in evaluation).items() if n > 1]
    near = []
    for item in evaluation:
        a = item["shingles"]
        if len(a) < 30:
            continue
        for candidate in train:
            b = candidate["shingles"]
            if not b or min(len(a), len(b)) / max(len(a), len(b)) < 0.5:
                continue
            overlap = len(a & b)
            similarity = overlap / (len(a) + len(b) - overlap)
            if similarity >= 0.5:
                near.append({"eval": item["id"], "train": candidate["id"], "jaccard_7grams": similarity})
    overlaps = {}
    for field in ("canonical_id", "repo", "instruction_hash"):
        common = {x[field] for x in train if x[field]} & {x[field] for x in evaluation if x[field]}
        overlaps[field] = sorted(common)
    limits = []
    for item in evaluation:
        cfg = item["task_config"]
        limits.append(
            {
                "id": item["id"],
                "agent": cfg.get("agent", {}).get("timeout_sec", 0),
                "verifier": cfg.get("verifier", {}).get("timeout_sec", 0),
                "build": cfg.get("environment", {}).get("build_timeout_sec", 0),
                "cpus": cfg.get("environment", {}).get("cpus"),
                "memory_mb": cfg.get("environment", {}).get("memory_mb"),
            }
        )
    record = {
        "train": str(args.train),
        "train_sha256": digest(args.train.read_bytes()),
        "train_tasks": len(train),
        "data": str(args.eval),
        "data_sha256": digest(args.eval.read_bytes()),
        "tasks": len(evaluation),
        "duplicate_basenames": duplicates,
        "overlaps": overlaps,
        "near_instruction_pairs": near,
        "limitations": (
            "Lexical 7-gram Jaccard >=0.5; not semantic or patch near-duplicate proof. "
            "Repo normalization from task IDs."
        ),
        "max_declared_seconds": max(x["agent"] + x["verifier"] + x["build"] for x in limits),
        "limits": limits,
        "task_content": [{k: v for k, v in x.items() if k not in ("shingles", "task_config")} for x in evaluation],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k not in ("limits", "task_content")}))


if __name__ == "__main__":
    main()
