"""Extract logged training metrics and paired internal-validation deltas."""

import json
import re
import statistics
from pathlib import Path


def summarize(root):
    root = Path(root)
    metrics = []
    fields = {
        "loss": "actor/distillation/loss",
        "grad_norm": "actor/grad_norm",
        "output_tokens_mean": "response_length/mean",
        "truncated_rate": "response_length/clip_ratio",
    }
    for name in ["train-smoke", "train-full"]:
        path = root / f"{name}.log"
        if not path.exists():
            continue
        for line in path.read_text(errors="replace").splitlines():
            line = re.sub(r"\x1b\[[0-9;]*m", "", line)
            step = re.search(r"(?:step:|global_step:|training/global_step:)\s*(\d+)", line)
            if not step:
                continue
            item = {"model_id": name, "step": int(step.group(1))}
            for target, source in fields.items():
                match = re.search(re.escape(source) + r"[:=]\s*([-+\d.eE]+)", line)
                if match:
                    try:
                        item[target] = float(match.group(1))
                    except ValueError:
                        pass
            if len(item) > 2:
                metrics.append(item)
    (root / "train-metrics.jsonl").write_text("".join(json.dumps(m) + "\n" for m in metrics))
    for path in (root / "models").glob("*/eval.json"):
        outputs_path = path.parent / "outputs.json"
        if not outputs_path.exists():
            continue
        evaluation = json.loads(path.read_text())
        outputs = json.loads(outputs_path.read_text())
        for domain in evaluation.get("domains", []):
            lengths = [row["output_tokens"] for row in outputs if row["domain"] == domain["domain"]]
            if lengths:
                domain["output_tokens_median"] = statistics.median(lengths)
        path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2))
    for manifest_path in (root / "adapters-smoke/manifest.json", root / "adapters/manifest.json"):
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        for checkpoint in manifest.get("checkpoints", []):
            for evaluation_path in (root / "models").glob("*/eval.json"):
                evaluation = json.loads(evaluation_path.read_text())
                if (
                    evaluation.get("adapter_reload_verified")
                    and evaluation.get("adapter_path") == checkpoint.get("adapter")
                    and evaluation.get("adapter_weights_sha256") == checkpoint.get("weights_sha256")
                ):
                    checkpoint["generation_reload_verified"] = True
                    checkpoint["reload_evaluation"] = str(evaluation_path.relative_to(root))
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    base_path = root / "models/base-9b/outputs.json"
    if not base_path.exists():
        return
    base_eval = json.loads((base_path.parent / "eval.json").read_text())
    base = {r["extra_info"]["sample_id"]: r for r in json.loads(base_path.read_text())}
    for path in (root / "models").glob("*/eval.json"):
        outputs = path.parent / "outputs.json"
        if not outputs.exists() or path.parent.name == "base-9b":
            continue
        report = json.loads(path.read_text())
        if any(report.get(key) != base_eval.get(key) for key in ("dataset_revision", "budget")):
            report["paired_comparison"] = {"status": "incompatible", "reason": "Dataset or budget differs"}
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            continue
        rows = json.loads(outputs.read_text())
        pairs = {}
        for row in rows:
            original = base.get(row["extra_info"]["sample_id"])
            if original and original["score"] is not None and row["score"] is not None:
                pairs.setdefault(row["domain"], []).append((original["score"], row["score"]))
        report["paired_comparison"] = {
            domain: {
                "n": len(values),
                "mean_delta": sum(b - a for a, b in values) / len(values),
                "improved": sum(b > a for a, b in values),
                "regressed": sum(b < a for a, b in values),
                "note": "Small internal pilot; no significance claim",
            }
            for domain, values in pairs.items()
        }
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    summarize(Path(__file__).resolve().parent)
