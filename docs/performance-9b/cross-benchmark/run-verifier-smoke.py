"""Run fixed nop/oracle controls in Modal; stop if verifier or environment is invalid."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--task-id", help="Additional control only; leaves fixed model probe selection unchanged")
    args = ap.parse_args()
    manifest = json.loads(args.manifest.read_text())
    dataset = next(d for d in manifest["datasets"] if d["label"] == args.benchmark)
    audit = json.loads(Path(dataset["audit"]).read_text())
    task_id = args.task_id or dataset["probe_ids"][0]
    task = next(x for x in audit["task_content"] if x["id"] == task_id)
    cfg = yaml.safe_load(Path(dataset["task_config"]).read_text())[0]
    root = Path(manifest["output"]) / "verifier-controls-v2" / dataset["label"]
    if args.task_id:
        root = root.parent / (dataset["label"] + "-" + task["basename"])
    root.mkdir(parents=True, exist_ok=True)
    receipts = []
    for agent, expected in [("nop", 0), ("oracle", 1)]:
        trial_name = agent + "-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
        out = root / trial_name
        command = [
            str(Path(manifest["python"]).parent / "harbor"),
            "trial",
            "start",
            "--path",
            task["path"],
            "--agent",
            agent,
            "--env",
            "modal",
            "--trials-dir",
            str(root),
            "--trial-name",
            trial_name,
        ]
        for key, value in cfg["environment_kwargs"].items():
            command += ["--environment-kwarg", f"{key}={json.dumps(value)}"]
        if not out.exists():
            print("launch", dataset["label"], agent, flush=True)
            with (root / (agent + ".log")).open("w") as log:
                proc = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())
            (root / (agent + "-exit.json")).write_text(json.dumps({"exit_code": proc.returncode}))
        result = json.loads((out / "result.json").read_text())
        reward = (result.get("verifier_result") or {}).get("rewards")
        record = {"agent": agent, "expected": expected, "rewards": reward, "exception": result.get("exception_info")}
        receipts.append(record)
        passed = not record["exception"] and reward == {"reward": float(expected)}
        (root / "validation.json").write_text(
            json.dumps({"status": "running" if passed else "failed", "controls": receipts}, indent=2)
        )
        if not passed:
            raise RuntimeError(f"{dataset['label']} {agent}: verifier control failed: {record}")
    (root / "validation.json").write_text(json.dumps({"status": "complete", "controls": receipts}, indent=2))
    print("complete", dataset["label"], flush=True)


if __name__ == "__main__":
    main()
