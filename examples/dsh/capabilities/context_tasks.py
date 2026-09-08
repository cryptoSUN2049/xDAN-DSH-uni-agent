"""Generate four fixed diagnostic instances, not a training campaign or admission receipt."""

import argparse
import json
from pathlib import Path

from examples.dsh.capabilities.context_verifier import VERIFIER_ID, bundle_digest
from examples.dsh.evolution_verifier import _sha256_bytes


def prepare(output: Path):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for family in ("directed", "conflict"):
        for availability in ("present", "missing"):
            case = f"{family}-{availability}"
            root = output / case
            (root / "sources").mkdir(parents=True)
            current = "authority=current\n" + (
                "max_attempts=3\n" if availability == "present" else "status=not_specified\n"
            )
            texts = {"sources/current.txt": current}
            if family == "conflict":
                texts["sources/previous.txt"] = "authority=superseded\nmax_attempts=9\n"
            else:
                texts["sources/unrelated.txt"] = "project=unrelated\nmax_attempts=7\n"
            sources = []
            for path, text in texts.items():
                (root / path).write_text(text)
                sources.append({"path": path, "sha256": _sha256_bytes(text.encode())})
            contract = {
                "schema": "dsh.context-file-evidence.v1",
                "case_id": case,
                "family": family,
                "target_key": "max_attempts",
                "authoritative_source": "sources/current.txt",
                "sources": sources,
                "required_evidence": [{"source": path, "line": 2} for path in texts],
            }
            raw = (json.dumps(contract, sort_keys=True) + "\n").encode()
            fixture = root / "contract.json"
            fixture.write_bytes(raw)
            prompt = (
                "Read each listed source with str_replace_editor view (full file). "
                "Do not read other files or modify anything. "
                "Report max_attempts using current.txt as the only current authority. "
                "previous.txt is superseded; unrelated.txt describes another project. "
                "Never fill a missing current value from them. "
                "Return ONLY JSON with status (answer or insufficient_evidence), value (string or null), "
                "citations (one {source,line,quote} for line 2 of EACH listed source; source is the relative label). "
                "If current.txt lacks max_attempts, return insufficient_evidence with null. "
                "Use these exact absolute paths to view the sources:\n"
                + "\n".join(f"{path}: {root / path}" for path in texts)
            )
            rows.append(
                {
                    "messages": [{"role": "user", "content": prompt}],
                    "metadata": {
                        "task_id": "dsh/context/" + case,
                        "task_version": "1",
                        "verifier_id": VERIFIER_ID,
                        "verifier_version": "1",
                        "verifier_code_digest": bundle_digest(),
                        "fixture_path": str(fixture),
                        "fixture_sha256": _sha256_bytes(raw),
                        "capability_scope": "file-evidence-only",
                    },
                }
            )
    (output / "tasks.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = prepare(args.output)
    print(json.dumps({"output": str(args.output.resolve()), "instances": len(rows), "scope": "file-evidence-only"}))


if __name__ == "__main__":
    main()
