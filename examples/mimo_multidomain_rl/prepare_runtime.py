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

OLD_POSITION_BOUNDARY = """def maybe_fix_3d_position_ids(data: TensorDict):
    # note for tensordict with pickle/unpickle. nested tensor in tensordict after consolidate and pickle/unpickle
    # will incur indexing error for ragged tensor. This only happens when using 3D position ids in VLMs.
    # This is likely a bug in tensordict. As a workaround, we manually set _ragged_index.
    if "position_ids" in data.keys() and data["position_ids"].dim() == 3 and data["position_ids"].is_nested:
        data["position_ids"]._ragged_idx = 2
"""

NEW_POSITION_BOUNDARY = '''def maybe_fix_3d_position_ids(data: TensorDict):
    """Normalize TQ's mRoPE packing without changing any position values.

    TQ may pack equal-length (axes, tokens) samples with the axes dimension
    jagged. Merely changing _ragged_idx then makes offsets describe the wrong
    dimension. Rebuild through the public constructor at the worker boundary,
    preserving the public shape/offsets interpretation of the received tensor.
    """
    position_ids = data.get("position_ids")
    if position_ids is None or position_ids.dim() != 3 or not position_ids.is_nested:
        return
    input_ids = data.get("input_ids")
    token_lengths = None
    if input_ids is not None and input_ids.is_nested and input_ids.layout == torch.jagged:
        token_lengths = input_ids.offsets().diff().tolist()
    if position_ids.layout != torch.jagged:
        items = list(position_ids.unbind())
    else:
        values, offsets = position_ids.values(), position_ids.offsets()
        lengths = offsets.diff().tolist()
        # TensorDict consolidate/pickle can lose even the public shape's
        # jagged dimension. Use backing dimensions AND the input token counts.
        # This also disambiguates square buffers without trusting _ragged_idx.
        axes_ragged = int(offsets[-1]) == values.shape[0]
        tokens_ragged = int(offsets[-1]) == values.shape[1]
        if token_lengths is not None:
            axes_ragged = axes_ragged and token_lengths == [values.shape[1]] * len(lengths)
            tokens_ragged = tokens_ragged and token_lengths == lengths
        if axes_ragged and tokens_ragged:
            # Both candidates are equivalent only for a single square sample.
            if len(lengths) != 1:
                raise ValueError("mRoPE jagged orientation is ambiguous")
            items = [values]
        elif axes_ragged:
            items = list(values.split(lengths, dim=0))
        elif tokens_ragged:
            items = list(values.split(lengths, dim=1))
        else:
            raise ValueError("mRoPE positions disagree with input token lengths or offsets")
    if not items or any(item.dim() != 2 or item.shape[0] != items[0].shape[0] for item in items):
        raise ValueError("mRoPE samples must retain a common position axis count")
    if token_lengths is not None:
        if [item.shape[-1] for item in items] != token_lengths:
            raise ValueError("mRoPE positions disagree with input token lengths")
    data["position_ids"] = nested_tensor_from_tensor_list(items, ragged_idx=2)
'''

PATCHES = {
    "verl/utils/tensordict_utils.py": (
        "4dc4c321a51e256232751ddb5cb2a2be129076e7f02f36a685fcad6d0d98f5f1",
        (
            (
                "torch.nested.nested_tensor_from_jagged(values=values, offsets=offsets)",
                "torch.nested.nested_tensor_from_jagged(values=values, offsets=offsets, jagged_dim=ragged_idx)",
            ),
            ("    nested_tensor._ragged_idx = ragged_idx\n", ""),
            (OLD_POSITION_BOUNDARY, NEW_POSITION_BOUNDARY),
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
        "schema": "mimo.torch211-runtime.v2",
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
