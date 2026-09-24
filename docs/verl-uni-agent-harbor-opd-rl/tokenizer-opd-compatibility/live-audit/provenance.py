"""Read-only model/config and deployed source identities for this audit."""

import hashlib
import json
from pathlib import Path

ROOT = Path("/workspace/verl-uni-agent-harbor-opd-rl")
RUN = ROOT / "runs/opd-live-acceptance-20260924"
SOURCE = ROOT / "src/uni-agent/verl/verl"


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


paths = [
    SOURCE / s
    for s in [
        "experimental/teacher_loop/teacher_manager.py",
        "trainer/distillation/losses.py",
        "workers/config/distillation.py",
        "trainer/ppo/core_algos.py",
    ]
]
teacher = paths[0].read_text().splitlines()
result = {
    "source_sha256": {str(p): digest(p) for p in paths},
    "teacher_sampling_source_lines": [{"line": i + 1, "text": s} for i, s in enumerate(teacher) if 35 <= i <= 57],
    "models": {},
    "scope": "Local model config/tokenizer/index hashes, shard sizes; not full shard content rehash",
}
for name in ["Qwen3.5-9B", "Qwen3.8-27B"]:
    model = Path("/workspace/models") / name
    result["models"][name] = {
        "path": str(model),
        "metadata_sha256": {
            p.name: digest(p)
            for p in model.iterdir()
            if p.is_file() and (p.suffix in [".json", ".jinja"] or p.name == "merges.txt")
        },
        "shards": {p.name: p.stat().st_size for p in model.glob("*.safetensors")},
    }
(RUN / "provenance.json").write_text(json.dumps(result, indent=2))
