"""Create an auditable MiMo runtime with correct PyTorch jagged dimensions.

The reference checkout is immutable. This changes tensor representation only;
task data, rewards, advantages, model positions and loss formulas are retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

PATCHES = {
    "verl/utils/tensordict_utils.py": (
        "4dc4c321a51e256232751ddb5cb2a2be129076e7f02f36a685fcad6d0d98f5f1",
        (
            (
                "torch.nested.nested_tensor_from_jagged(values=values, offsets=offsets)",
                "torch.nested.nested_tensor_from_jagged(values=values, offsets=offsets, jagged_dim=ragged_idx)",
            ),
            ("    nested_tensor._ragged_idx = ragged_idx\n", ""),
        ),
    ),
    "verl/workers/utils/padding.py": (
        "f3cc823e6ef2099075406f6fe1244498f15a775f0fac90010c0babf1c82cbe7b",
        (
            (
                "position_ids_nested = torch.nested.as_nested_tensor(position_ids_list, layout=torch.jagged)",
                "position_ids_nested = tu.nested_tensor_from_tensor_list(position_ids_list)",
            ),
        ),
    ),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Runtime must use a new directory separate from the immutable source")
    rewritten = {}
    for name, (expected, edits) in PATCHES.items():
        original = source / name
        if not original.is_file() or sha(original) != expected:
            raise ValueError(f"Pinned tensor source mismatch: {name}")
        text = original.read_text()
        for before, after in edits:
            if text.count(before) != 1:
                raise ValueError(f"Tensor compatibility edit is not unique: {name}")
            text = text.replace(before, after)
        compile(text, str(output / name), "exec")
        rewritten[name] = text
    shutil.copytree(source, output, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "._*"))
    for name, text in rewritten.items():
        (output / name).write_text(text)
    report = {
        "schema": "mimo.torch211-runtime.v1",
        "scope": "tensor representation compatibility; no training acceptance",
        "source": str(source),
        "runtime": str(output),
        "changed_files": {
            name: {"before_sha256": expected, "after_sha256": sha(output / name)}
            for name, (expected, _edits) in PATCHES.items()
        },
        "source_unchanged": all(sha(source / name) == expected for name, (expected, _edits) in PATCHES.items()),
    }
    (output / "tensor-compatibility-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output)))


if __name__ == "__main__":
    main()
