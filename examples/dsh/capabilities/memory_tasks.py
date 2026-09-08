"""Two small diagnostic families, not a heldout capability benchmark."""

from pathlib import Path

from examples.dsh.capabilities.memory_verifier import canonical, sha


def writer_fixture(root: Path, chain_id: str, family: str):
    if family == "constraints":
        facts = {"region": "eu-west-test", "forbidden": "public_bucket"}
        source = {"version": 1, "facts": facts}
    elif family == "updates":
        facts = {"region": "ap-south-test", "forbidden": "public_bucket"}
        source = {"version": 2, "superseded": {"version": 1, "region": "eu-west-test"}, "facts": facts}
    else:
        raise ValueError("Unsupported memory diagnostic family")
    source_raw = canonical(source)
    source_version = sha(source_raw)
    expected = {"source_version": source_version, "facts": facts}
    return {
        "schema": "dsh.memory-stage.v1",
        "chain_id": chain_id,
        "role": "writer",
        "family": family,
        "source_version": source_version,
        "source_path": str(root / "source.json"),
        "source_sha256": sha(source_raw),
        "memory_path": str(root / "memory.json"),
        "max_bytes": 4096,
        "expected_memory": expected,
    }, source_raw


def writer_prompt(fixture):
    return (
        f"Read {fixture['source_path']} with str_replace_editor. Preserve the current authoritative facts, "
        "including the forbidden action; superseded facts must not replace current facts. "
        f"Write {fixture['memory_path']} as a JSON object with exactly source_version and facts. "
        f"Use source_version={fixture['source_version']!r}; copy the source's current facts object faithfully. "
        "Use file tools to write persistent memory for a new independent session. Finish after writing."
    )


def reader_prompt(fixture):
    return (
        f"This is a new session. Read {fixture['question_path']} and {fixture['memory_path']} using "
        "str_replace_editor. Answer the question from the saved memory. Return only JSON with exactly "
        "status='answer', facts (the remembered current facts object), and source_version "
        "(copied from the memory). Do not infer unavailable facts."
    )
