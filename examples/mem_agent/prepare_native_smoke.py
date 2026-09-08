"""Fixed, disjoint engineering subsets; not a benchmark training/eval release."""

import argparse
import hashlib
import json
from pathlib import Path

COLUMNS = ("data_source", "prompt", "context", "reward_model", "extra_info")


def select_rows(rows, train_count, val_count):
    if train_count < 1 or val_count < 1 or len(rows) < train_count + val_count:
        raise ValueError("insufficient rows or invalid partition sizes")
    selected = [{key: row[key] for key in COLUMNS} for row in rows[: train_count + val_count]]
    keys = [json.dumps(row["prompt"], sort_keys=True) for row in selected]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate questions in diagnostic partitions")
    return selected[:train_count], selected[train_count:]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    import pyarrow as pa
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-count", type=int, default=4)
    parser.add_argument("--val-count", type=int, default=2)
    args = parser.parse_args()
    rows = pq.read_table(args.source, columns=list(COLUMNS)).to_pylist()
    train, val = select_rows(rows, args.train_count, args.val_count)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, subset in (("train", train), ("val", val)):
        pq.write_table(pa.Table.from_pylist(subset), args.output / f"{name}.parquet")
    manifest = {
        "scope": "native-engineering-diagnostic-not-benchmark",
        "source_revision": args.source_revision,
        "source_sha256": digest(args.source),
        "selection": "first train_count rows, then val_count rows",
        "source_partition": "upstream dev reused only for engineering diagnostic",
        "train_count": len(train),
        "val_count": len(val),
        "files": {name: digest(args.output / f"{name}.parquet") for name in ("train", "val")},
        "columns": COLUMNS,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
