"""Pure reproducible development tasks. Never send truth/oracle helpers to actors."""

import json
import random

MEMORY_PATHS = ["index.md", "handoff.md", "tasks.json", "memory.json", "modules.md", "decisions.md"]
RESULT_PATHS = ["config.json", "plan.json"]


def _text(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def make_task(family: str, variant: int = 0, seed: int = 0) -> dict:
    if family not in ("WS01", "WS03", "WS05", "WS06") or type(variant) is not int or variant not in (0, 1):
        raise ValueError("Unsupported family/structural variant")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    rng = random.Random(seed)
    size = rng.randint(20, 200)
    writer, reader = {}, {}
    completed, dependencies, required, plan = [], {}, [], []
    if family == "WS01":
        dependencies = (
            {"initialize": [], "migrate": ["initialize"], "verify": ["migrate"]}
            if variant == 0
            else {
                "initialize": [],
                "build_schema": ["initialize"],
                "build_cache": ["initialize"],
                "switch": ["build_schema", "build_cache"],
                "verify": ["switch"],
            }
        )
        completed = ["initialize"]
        required = list(dependencies)
        plan = required[1:]
        expected = {"capacity": size, "schema_version": 2 if variant == 0 else 3}
        writer["sources/workflow.json"] = _text(
            {
                "dependencies": dependencies,
                "completed": completed,
                "required": required,
                "configuration_requirement": expected,
            }
        )
        reader["sources/notice.json"] = _text(
            {
                "goal": "Complete the migration without repeating completed actions.",
                "configuration_keys": list(expected),
                "plan_format": "JSON array of action names",
            }
        )
        structure = "linear-migration" if variant == 0 else "parallel-join-migration"
    elif family == "WS03":
        if variant == 0:
            expected = {"database": "transactional", "cache": "modern"}
            catalog = {
                "database": {
                    "transactional": {"transactions": True, "protocol": 2},
                    "legacy": {"transactions": False, "protocol": 1},
                },
                "cache": {"modern": {"protocol": 2}, "legacy": {"protocol": 1}},
            }
            requirement = {"transactions": True, "matching_protocol": True}
            structure = "transaction-protocol-pair"
        else:
            expected = {"encoder": "lossless", "transport": "regional", "storage": "durable"}
            catalog = {
                "encoder": {"lossless": {"format": "binary"}, "compact": {"format": "text"}},
                "transport": {
                    "regional": {"format": "binary", "region": "local"},
                    "global": {"format": "text", "region": "remote"},
                },
                "storage": {
                    "durable": {"region": "local", "retention": size},
                    "temporary": {"region": "local", "retention": 0},
                },
            }
            requirement = {"format": "binary", "region": "local", "minimum_retention": size}
            structure = "three-component-format-region-retention"
        # Option identifiers carry no quality hint; preserve facts, randomize the assignment.
        for component, entries in catalog.items():
            names = ["option-a", "option-b"]
            rng.shuffle(names)
            renamed = dict(zip(entries, names, strict=True))
            expected[component] = renamed[expected[component]]
            catalog[component] = {renamed[name]: facts for name, facts in entries.items()}
        for component, entries in catalog.items():
            writer[f"sources/{component}.json"] = _text(entries)
        writer["sources/requirements.json"] = _text(requirement)
        reader["sources/request.json"] = _text(
            {
                "requirements": requirement,
                "component_keys": list(catalog),
                "plan": "No workflow actions; submit an empty array.",
            }
        )
    elif family == "WS05":
        expected = (
            {"region": "local", "retention": size}
            if variant == 0
            else {"region": "local", "retention": size, "encryption": True}
        )
        decoy = {**expected, "region": "remote"}
        records = [
            {"scope": "other-worktree", "revision": 99, "config": decoy},
            {"scope": "this-worktree", "revision": 1, "config": {**expected, "retention": 1}},
            {"scope": "this-worktree", "revision": 2, "config": expected},
        ]
        if variant == 1:
            # Separate security authority overrides a later operational suggestion.
            records[-1]["config"] = {k: v for k, v in expected.items() if k != "encryption"}
            records.append({"scope": "this-worktree", "authority": "security", "encryption_required": True})
            records.append({"scope": "this-worktree", "authority": "advisory", "revision": 100, "encryption": False})
        writer["sources/decisions.json"] = _text(records)
        reader["sources/policy.json"] = _text(
            {
                "scope": "this-worktree",
                "operational_revision": 2,
                "security_overrides_advisory": bool(variant),
                "keys": list(expected),
                "plan": "No workflow actions; submit an empty array.",
            }
        )
        structure = "scope-and-revision" if variant == 0 else "scope-plus-independent-security-authority"
    else:
        if variant == 0:
            public = {"peak": size, "reserve": 7, "rule": "capacity = peak + reserve"}
            expected = {"capacity": size + 7}
            structure = "single-capacity-sum"
        else:
            public = {
                "east_load": size,
                "west_load": size + 9,
                "limit": size + 4,
                "rule": "Each regional capacity is min(regional load, limit). Keep separate regions.",
            }
            expected = {"east_capacity": size, "west_capacity": size + 4}
            structure = "two-regions-independent-cap"
        public["plan"] = "No workflow actions; submit an empty array."
        writer["sources/request.json"] = _text(public)
        reader["sources/request.json"] = _text(public)
    truth = dict(
        expected_config=expected,
        dependencies=dependencies,
        completed=completed,
        required=required,
        oracle_plan=plan,
        structure=structure,
    )
    if family == "WS03":
        truth.update(catalog=catalog, requirements=requirement)
    if family == "WS05":
        truth["decoy_config"] = decoy
    task_id = f"work-state-{family.lower()}-v{variant}-s{seed}"
    common = (
        "Use only the operator-permitted str_replace_editor file actions. Read results before basing new "
        "writes on them. Memory artifacts are optional; organize only useful recovery state. "
        "Never modify source files or controller evidence. "
    )
    writer_goal = common + (
        "Your role in session A is to prepare recovery state only. Do not execute the configuration "
        "or workflow task, advance completed actions, or change any source. Session B will perform "
        "that task in a fresh conversation. Read the authoritative sources, then preserve useful "
        "facts, requirements, dependencies, completed work and unresolved questions exactly as supported "
        "by those sources; distinguish observed state from requested targets. Do not change requested "
        "values or increment version numbers. Your source files and conversation will not be copied "
        "to B. Choose only useful memory files and make any saved state discoverable from index.md. "
        "The available memory paths are optional destinations, not a checklist of files that must exist. "
        "Once useful recovery state has been saved and any chosen verification is complete, finish with "
        "a brief handoff summary. Do not repeatedly probe absent optional files."
    )
    if family == "WS06":
        writer_goal = (
            common + "The next session already receives the complete short request; persistence is unnecessary. "
            "You may finish immediately with a short handoff summary without creating or inspecting memory files."
        )
    reader_goal = (
        common + "Recover relevant work state from the memory index if present and your public sources. "
        "Create config.json as a JSON object and plan.json as an ordered JSON array of action names. "
        "Do not invent missing facts. The controller independently executes/checks these artifacts."
    )
    return dict(
        schema="dsh.work-state-task.v1",
        protocol_revision=2,
        task_id=task_id,
        family=family,
        variant=variant,
        seed=seed,
        writer_goal=writer_goal,
        reader_goal=reader_goal,
        writer_files=writer,
        reader_files=reader,
        memory_paths=list(MEMORY_PATHS),
        result_paths=list(RESULT_PATHS),
        truth=truth,
    )


def oracle_memory(task: dict) -> dict[str, bytes]:
    """Controller canary only; never inject into student episodes."""
    if task["family"] == "WS06":
        return {}
    files = task["writer_files"]
    return {
        "index.md": b"Recovery evidence is preserved in modules.md. Read it before deciding.\n",
        "modules.md": "\n".join(f"## {name}\n{text}" for name, text in files.items()).encode(),
    }


def oracle_outputs(task: dict) -> dict[str, bytes]:
    """Controller canary only; result artifacts, not on-policy data."""
    return {
        "config.json": _text(task["truth"]["expected_config"]).encode(),
        "plan.json": _text(task["truth"]["oracle_plan"]).encode(),
    }
