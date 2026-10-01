"""Freeze published MiMo rows without changing their schema or reward semantics.

Run on cloud CPU only. Preparation is not task runtime or training acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path, PurePosixPath

LOCK_PATH = Path(__file__).with_name("source-lock.json")
DOMAINS = ("code", "cyber", "general", "webdev", "music")
FIXTURE_ABC = "X:1\nT:t\nM:4/4\nL:1/8\nK:C\nCDEF|GABc|c4|z4|"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def instance(row: dict) -> dict:
    raw = row["extra_info"].get("instance_json")
    if raw is None:
        return {}
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("instance_json must encode an object")
    outer = row["extra_info"].get("dataset_type")
    if outer is not None and outer != result.get("dataset_type"):
        raise ValueError("outer and inner dataset_type disagree")
    return result


def task_id(row: dict, domain: str) -> str:
    key = "src_id" if domain == "music" else "instance_id"
    value = row["extra_info"].get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing source identity {key}")
    return value


def select_rows(rows: list[dict], domain: str, seed: int) -> list[tuple[int, dict, str]]:
    """Two train + one heldout, frozen before evaluating policy or rewards."""
    ids = [task_id(row, domain) for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate source task ids in {domain}")
    if len(rows) < 3:
        raise ValueError("need at least three distinct tasks")
    ranked = sorted(
        enumerate(rows),
        key=lambda item: (
            len(canonical(item[1]["prompt"])),
            sha256(f"{seed}:{task_id(item[1], domain)}".encode()),
        ),
    )
    if domain == "general":
        selected = []
        for kind in ("terminal_bench", "general_agent"):
            candidates = [item for item in ranked if instance(item[1]).get("dataset_type") == kind]
            if not candidates:
                raise ValueError(f"General missing required branch {kind}")
            selected.append(candidates[0])
    elif domain == "code":
        preferred = ("format-code-task-001661", "format-code-task-002549")
        selected = [next((item for item in ranked if task_id(item[1], domain) == name), None) for name in preferred]
        if any(item is None for item in selected):
            raise ValueError("locked Code task identity absent")
    elif domain == "music":
        selected = [ranked[0]]
        language = ranked[0][1]["extra_info"].get("lang")
        selected.append(next((item for item in ranked[1:] if item[1]["extra_info"].get("lang") != language), ranked[1]))
    else:
        selected = ranked[:2]
    chosen = {item[0] for item in selected}
    heldout = next(item for item in ranked if item[0] not in chosen)
    return [(index, row, "train") for index, row in selected] + [(*heldout, "heldout")]


def safe_asset_path(path: str) -> PurePosixPath:
    result = PurePosixPath(path)
    if result.is_absolute() or ".." in result.parts or not result.parts:
        raise ValueError("unsafe dataset asset path")
    return result


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "mimo-reference-prepare/1"}), timeout=120
    ) as response:
        return response.read()


def verified_source(path: Path, spec: dict, url: str) -> bytes:
    raw = path.read_bytes() if path.exists() else fetch(url)
    if len(raw) != spec["bytes"] or sha256(raw) != spec["sha256"]:
        raise ValueError(f"source bytes/hash mismatch: {spec['path']}")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return raw


def tree_files(repository: str, revision: str, prefix: str) -> list[str]:
    safe_asset_path(prefix)
    url = f"https://huggingface.co/api/datasets/{repository}/tree/{revision}/{urllib.parse.quote(prefix)}?recursive=true&limit=1000"
    paths = []
    while url:
        with urllib.request.urlopen(url, timeout=120) as response:
            entries = json.load(response)
            links = response.headers.get("Link", "")
        paths.extend(entry["path"] for entry in entries if entry["type"] == "file")
        url = next((part.split("<", 1)[1].split(">", 1)[0] for part in links.split(",") if 'rel="next"' in part), None)
        if url and not url.startswith("https://huggingface.co/api/datasets/"):
            raise ValueError("unexpected pagination destination")
    if not paths:
        raise ValueError(f"missing asset prefix {prefix}")
    return sorted(paths)


def prepare(output: Path, source_cache: Path, lock: dict, with_assets: bool = False) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    dataset = lock["dataset"]
    destination = output / "manifest.json"
    if destination.exists():
        raise ValueError("refusing to overwrite a frozen manifest")
    base = f"https://huggingface.co/datasets/{dataset['repository']}/resolve/{dataset['revision']}/"
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "mimo.multidomain-task-manifest.v1",
        "status": "prepared-not-runtime-admitted",
        "source_lock_sha256": sha256(canonical(lock)),
        "dataset": dataset,
        "tasks": [],
        "outputs": {},
    }
    for domain in ("music", *(name for name in DOMAINS if name != "music")):
        spec = dataset["files"][domain]
        path = source_cache / safe_asset_path(spec["path"])
        verified_source(path, spec, base + spec["path"])
        table = pq.read_table(path)
        if table.num_rows != spec["rows"]:
            raise ValueError(f"source row count mismatch: {domain}")
        rows = table.to_pylist()
        selected = select_rows(rows, domain, lock["selection"]["seed"])
        for split in ("train", "heldout"):
            indices = [index for index, _, part in selected if part == split]
            target = output / domain / f"{split}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table.take(pa.array(indices, type=pa.int64())), target)
            manifest["outputs"][f"{domain}/{split}"] = {
                "path": str(target),
                "sha256": sha256(target.read_bytes()),
                "rows": len(indices),
            }
        for index, row, split in selected:
            inst = instance(row)
            record = {
                "domain": domain,
                "split": split,
                "task_id": task_id(row, domain),
                "source_path": spec["path"],
                "source_revision": dataset["revision"],
                "source_row": index,
                "source_file_sha256": spec["sha256"],
                "row_sha256": sha256(canonical(row)),
                "original_row": row,
                "instance": inst,
                "image": inst.get("docker_image"),
                "image_digest": None,
                "image_status": "not-applicable" if domain == "music" else "unresolved",
                "assets": [],
                "assets_status": "not-applicable",
            }
            if domain == "general" and inst.get("env_task_dir"):
                prefix = "general/" + str(safe_asset_path(inst["env_task_dir"]))
                record["assets_status"] = "pending-download"
                if with_assets:
                    for asset in tree_files(dataset["repository"], dataset["revision"], prefix):
                        relative = safe_asset_path(asset)
                        if not str(relative).startswith(prefix + "/"):
                            raise ValueError("asset escaped selected task prefix")
                        content = fetch(base + urllib.parse.quote(asset))
                        target = output / "assets" / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                        record["assets"].append(
                            {
                                "path": str(relative),
                                "local_path": str(target),
                                "bytes": len(content),
                                "sha256": sha256(content),
                            }
                        )
                    record["assets_status"] = "content-hashed-not-runtime-admitted"
            if domain == "general" and inst.get("dataset_type") == "terminal_bench":
                tests = json.loads(inst["tests_files"])
                if not isinstance(tests, dict) or not tests:
                    raise ValueError("terminal_bench tests_files must contain files")
                record["embedded_tests"] = [
                    {"path": str(safe_asset_path(name)), "sha256": sha256(content.encode())}
                    for name, content in tests.items()
                ]
            manifest["tasks"].append(record)
    manifest["domain_counts"] = dict(Counter(task["domain"] for task in manifest["tasks"]))
    encoded = canonical(manifest)
    destination.write_bytes(encoded)
    return manifest


def _music_worker(source: str, binary: str) -> dict:
    import socket

    os.environ["ABC2MIDI_BIN"] = binary
    sys.path.insert(0, source)
    scorer = importlib.import_module("recipes.design.music.scorer")
    return {
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "abc2midi": binary,
        "fenced": scorer.compute_score("music", f"```abc\n{FIXTURE_ABC}\n```"),
        "bare": scorer.compute_score("music", f"Write the final score.\n\n{FIXTURE_ABC}"),
    }


def music_preflight(source: Path, binary: Path, lock: dict) -> dict:
    import ray

    if ray.is_initialized():
        raise ValueError("music preflight requires an independent owned Ray cluster")
    baseline = source / lock["music_scorer"]["path"] / lock["music_scorer"]["baseline"]
    if sha256(baseline.read_bytes()) != lock["music_scorer"]["baseline_sha256"]:
        raise ValueError("Music baseline hash mismatch")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("abc2midi must be executable")
    ray.init(address="local", num_cpus=2, num_gpus=0, include_dashboard=False, log_to_driver=False)
    try:
        worker = ray.remote(num_cpus=1)(_music_worker)
        results = ray.get([worker.remote(str(source.resolve()), str(binary.resolve())) for _ in range(2)])
    finally:
        ray.shutdown()
    if any(not 0 < result[kind] < 1 for result in results for kind in ("fenced", "bare")):
        raise ValueError("Music actual worker scores must be strictly between zero and one")
    return {
        "status": "cpu-worker-preflight-passed-not-training",
        "baseline_sha256": sha256(baseline.read_bytes()),
        "binary_sha256": sha256(binary.read_bytes()),
        "workers": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path)
    parser.add_argument("--assets", action="store_true")
    parser.add_argument("--music-source", type=Path)
    parser.add_argument("--abc2midi", type=Path)
    args = parser.parse_args()
    lock = json.loads(LOCK_PATH.read_text())
    if args.music_source:
        if not args.abc2midi:
            parser.error("--music-source requires --abc2midi")
        args.output.mkdir(parents=True, exist_ok=True)
        report = music_preflight(args.music_source, args.abc2midi, lock)
        (args.output / "music-worker-preflight.json").write_bytes(canonical(report))
        print(json.dumps(report))
    else:
        if not args.source_cache:
            parser.error("data preparation requires --source-cache")
        manifest = prepare(args.output, args.source_cache, lock, args.assets)
        print(
            json.dumps(
                {
                    "status": manifest["status"],
                    "domain_counts": manifest["domain_counts"],
                    "manifest_sha256": sha256(canonical(manifest)),
                }
            )
        )


if __name__ == "__main__":
    main()
