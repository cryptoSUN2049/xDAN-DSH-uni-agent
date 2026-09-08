"""Deterministic engineering evidence curriculum; separate from public v1 evaluation."""

import json
import re
from pathlib import Path

from examples.dsh.evolution_verifier import _sha256_bytes

SCHEMA = "dsh.context-file-evidence.v2"
VERIFIER_ID = "dsh-context-file-evidence-v2"


def documents(contract, root):
    root = Path(root).resolve()
    if contract.get("schema") != SCHEMA:
        raise RuntimeError("Invalid context v2 schema")
    result = {}
    for source in contract["sources"]:
        name = source["path"]
        path = (root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(root) or name in result:
            raise RuntimeError("Invalid source identity")
        raw = path.read_bytes()
        if _sha256_bytes(raw) != source["sha256"]:
            raise RuntimeError("Context source hash mismatch")
        fields = {}
        lines = raw.decode().splitlines()
        for number, line in enumerate(lines, 1):
            key, sep, value = line.partition("=")
            if not sep or not key or key in fields:
                raise RuntimeError("Invalid or duplicate source field")
            fields[key] = (value, number)
        result[name] = {"fields": fields, "lines": lines}
    if not result:
        raise RuntimeError("Empty source set")
    return result


def oracle(contract, root):
    docs = documents(contract, root)
    rule = contract["rule"]
    if rule["mode"] not in {"direct", "index", "select"}:
        raise RuntimeError("Invalid authority mode")
    if rule["mode"] == "direct":
        selected = rule["source"]
        if selected not in docs:
            raise RuntimeError("Missing directed source")
    elif rule["mode"] == "index":
        selected = docs[rule["index"]]["fields"]["selected_source"][0]
        if selected not in docs:
            raise RuntimeError("Index target outside allowlist")
    else:
        candidates = []
        for name, doc in docs.items():
            fields = {key: pair[0] for key, pair in doc["fields"].items()}
            if fields.get("project") != rule["project"] or fields.get("component") != rule["component"]:
                continue
            if fields.get("state") != "active":
                continue
            version = fields.get("version", "")
            if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
                raise RuntimeError("Invalid numeric version")
            candidates.append((tuple(int(p) for p in version.split(".")), name))
        candidates.sort()
        if len(candidates) > 1 and candidates[-1][0] == candidates[-2][0]:
            raise RuntimeError("Ambiguous authority priority")
        selected = candidates[-1][1] if candidates else None
    value = docs[selected]["fields"].get(contract["target_key"], (None, 0))[0] if selected else None
    citations = []
    # Every evidence field is explicitly requested in the prompt. A full-file view
    # is required independently, including lines documenting absence/exclusions.
    for ref in contract["required_evidence"]:
        name, line = ref["source"], ref["line"]
        if name not in docs or type(line) is not int or not 1 <= line <= len(docs[name]["lines"]):
            raise RuntimeError("Invalid required evidence")
        citations.append({"source": name, "line": line, "quote": docs[name]["lines"][line - 1]})
    if not citations or len({(c["source"], c["line"]) for c in citations}) != len(citations):
        raise RuntimeError("Empty or duplicate evidence")
    if set(contract["decision_sources"]) != set(docs):
        raise RuntimeError("Decision source coverage must bind the complete candidate set")
    return {
        "status": "answer" if value is not None else "insufficient_evidence",
        "value": value,
        "citations": citations,
    }


def _doc(value="3", *, project="billing", component="worker", version="1.0.0", state="active", **extra):
    fields = dict(project=project, component=component, state=state, version=version, **extra)
    if value is not None:
        fields["max_attempts"] = value
    else:
        fields["status"] = "not_specified"
    return fields


def specifications():
    """Different evidence graphs and rule combinations, not numeric renamings."""
    select = {"mode": "select", "project": "billing", "component": "worker"}
    direct = {"mode": "direct", "source": "sources/current.txt"}
    index = {"mode": "index", "index": "sources/index.txt"}
    current = _doc()
    other = _doc("7", project="analytics")
    old = _doc("9", state="superseded")
    return [
        ("train-D1", "directed", direct, {"current": current, "other": other}),
        ("train-D2", "directed", select, {"current": current, "web": _doc("8", component="web")}),
        (
            "train-D3",
            "directed",
            index,
            {"index": {"selected_source": "sources/current.txt"}, "current": current, "old": old},
        ),
        (
            "train-C1",
            "conflict",
            select,
            {"current": _doc(date="2025-01-01"), "old": _doc("9", state="superseded", date="2026-01-01")},
        ),
        (
            "train-C2",
            "conflict",
            select,
            {"current": current, "other": _doc("8", project="analytics", version="9.0.0")},
        ),
        ("train-C3", "conflict", select, {"current": current, "other": other, "old": old}),
        ("train-M1", "missing", direct, {"current": _doc(None), "old": old}),
        ("train-M2", "missing", select, {"other": other, "web": _doc("8", component="web")}),
        (
            "train-M3",
            "missing",
            select,
            {"current": _doc(None, version="2.0.0", delay_ms="100"), "previous": _doc("9"), "other": other},
        ),
        (
            "train-V1",
            "version",
            select,
            {"previous": _doc("9", version="1.9.0"), "current": _doc("4", version="1.10.0")},
        ),
        (
            "train-V2",
            "version",
            select,
            {
                "previous": current,
                "current": _doc("5", version="2.0.0"),
                "old": _doc("9", version="3.0.0", state="superseded"),
            },
        ),
        (
            "train-V3",
            "version",
            select,
            {
                "previous": current,
                "current": _doc("6", version="2.0.0"),
                "web1": _doc("7", component="web"),
                "web2": _doc("8", component="web", version="9.0.0"),
            },
        ),
        (
            "dev-D",
            "directed",
            index,
            {
                "index": {"selected_source": "sources/current.txt"},
                "current": current,
                "web": _doc("8", component="web"),
                "other": other,
            },
        ),
        (
            "dev-C",
            "conflict",
            select,
            {
                "other": _doc("8", project="analytics", version="9.0.0"),
                "old": _doc("9", state="superseded", version="8.0.0"),
                "previous": current,
                "current": _doc("5", version="2.0.0"),
                "web": _doc("7", component="web"),
            },
        ),
        (
            "dev-M",
            "missing",
            index,
            {"index": {"selected_source": "sources/current.txt"}, "current": _doc(None), "old": old, "other": other},
        ),
        (
            "dev-V",
            "version",
            select,
            {
                "previous": _doc("2", version="2.10.8"),
                "current": _doc("8", version="2.10.12"),
                "old": _doc("9", version="2.11.0", state="superseded"),
                "web": _doc("7", component="web", version="3.0.0"),
            },
        ),
    ]


def prepare(output):
    from examples.dsh.capabilities.context_verifier_v2 import bundle_digest

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = []
    for case_id, family, rule, docs in specifications():
        root = output / case_id
        (root / "sources").mkdir(parents=True, mode=0o700)
        sources, refs = [], []
        for index, (name, fields) in enumerate(docs.items()):
            pairs = list(fields.items())
            # Field ordering differs across documents; dev uses a further layout change.
            shift = (index + (2 if case_id.startswith("dev") else 0)) % len(pairs)
            pairs = pairs[shift:] + pairs[:shift]
            text = "".join(f"{key}={value}\n" for key, value in pairs)
            relative = f"sources/{name}.txt"
            (root / relative).write_text(text)
            sources.append({"path": relative, "sha256": _sha256_bytes(text.encode())})
            refs.extend({"source": relative, "line": n} for n, (key, _) in enumerate(pairs, 1) if key != "date")
        split = "train" if case_id.startswith("train") else "validation"
        contract = dict(
            schema=SCHEMA,
            case_id=case_id,
            structure_id=case_id,
            family=family,
            split=split,
            target_key="max_attempts",
            rule=rule,
            sources=sources,
            required_evidence=refs,
            decision_sources=[s["path"] for s in sources],
        )
        contract["expected"] = oracle(contract, root)
        path = root / "contract.json"
        path.write_text(json.dumps(contract, sort_keys=True, indent=2) + "\n")
        allowed = "\n".join(f"source ID {s['path']} ; view path {root / s['path']}" for s in sources)
        prompt = (
            "Resolve max_attempts from these engineering configuration documents. "
            "Read EVERY allowlisted file using str_replace_editor view with command and path only. "
            "Do not modify files, use other tools, or probe/read outside this allowlist. "
            "Authority rule: " + json.dumps(rule, sort_keys=True) + ". "
            "direct means exactly source; index means read selected_source from index. "
            "select means match project AND component, keep state=active, then choose greatest version "
            "by three integer components (not lexical order, date, or value). "
            "If no eligible source or the selected document lacks max_attempts, return insufficient_evidence "
            "with null value; never fall back to another document. "
            "Return ONLY JSON with exactly status, value, citations. status is answer or insufficient_evidence; "
            "value is a string or null. Each citation has exactly source, line (1-based integer), quote "
            "(exact full original line, without view numbering). citations.source MUST exactly equal "
            "the full relative source ID below, never basename or absolute path. "
            "Cite every line listed in required evidence exactly once; do not add other citations.\n"
            + allowed
            + "\nRequired evidence: "
            + json.dumps(refs, sort_keys=True)
        )
        metadata = dict(
            task_id="dsh/context-v2/" + case_id,
            task_version="2",
            split=split,
            structure_id=case_id,
            verifier_id=VERIFIER_ID,
            verifier_version="2",
            verifier_code_digest=bundle_digest(),
            fixture_path=str(path),
            fixture_sha256=_sha256_bytes(path.read_bytes()),
            capability_scope="file-evidence-only",
        )
        rows.append({"messages": [{"role": "user", "content": prompt}], "metadata": metadata})
    (output / "tasks.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    return rows
