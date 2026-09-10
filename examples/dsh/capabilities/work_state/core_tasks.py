"""Versioned core-course business facts; legacy generation remains unchanged."""

import random

from examples.dsh.capabilities.work_state.tasks import _text, make_task

TASK_GENERATION = "work-state-memory-core-v1"


def _catalog(rng, entries):
    """The first factual candidate is valid; shuffled neutral IDs hide that position."""
    names = [f"option-{letter}" for letter in "abcd"[: len(entries)]]
    rng.shuffle(names)
    return dict(zip(names, entries, strict=True)), names[0]


def make_core_task(family: str, variant: int = 0, seed: int = 0) -> dict:
    """Generate controller task data, never expose truth through actor files/goals."""
    if family not in ("WS01", "WS03", "WS05", "WS06"):
        raise ValueError("Unsupported core family")
    # The legacy constructor validates the exact integer variant/seed types.
    task = make_task(family, variant, seed)
    task["task_generation"] = TASK_GENERATION
    task["task_id"] = f"work-state-memory-core-v1-{family.lower()}-v{variant}-s{seed}"
    rng = random.Random(seed)
    # Injective for the actual course seed set (all distinct modulo prime 4093).
    # This quantity participates in business constraints, rather than an ID/nonce.
    quantity = 32 + (73 * seed + 19) % 4093
    writer, reader, truth = task["writer_files"], task["reader_files"], task["truth"]
    if family == "WS01":
        if variant == 0:
            names = ["initialize", "prepare", "copy", "migrate", "switch", "verify", "finalize"][: 3 + seed % 5]
            dependencies = {name: names[i - 1 : i] for i, name in enumerate(names)}
        else:
            branches = ["build_schema", "build_cache", "build_index", "build_queue"][: 2 + seed % 3]
            dependencies = {"initialize": [], **{name: ["initialize"] for name in branches}}
            dependencies.update(switch=branches, verify=["switch"])
            if seed % 2:
                dependencies["finalize"] = ["verify"]
            names = list(dependencies)
        completed = names[: seed % (len(names) - 1)]
        expected = {"capacity": quantity, "schema_version": 2 + seed % 7}
        truth.update(
            expected_config=expected,
            dependencies=dependencies,
            completed=completed,
            required=names,
            oracle_plan=names[len(completed) :],
        )
        writer["sources/workflow.json"] = _text(
            dict(dependencies=dependencies, completed=completed, required=names, configuration_requirement=expected)
        )
    elif family == "WS03":
        extra = bool(seed % 2)
        if variant == 0:
            protocol = quantity
            entries = {
                "database": [
                    {"transactions": True, "protocol": protocol},
                    {"transactions": True, "protocol": protocol + 1},
                    {"transactions": False, "protocol": protocol + 2},
                ],
                "cache": [{"protocol": protocol}, {"protocol": protocol + 2}, {"protocol": protocol + 3}],
            }
            if extra:
                entries["database"].append({"transactions": False, "protocol": protocol + 3})
                entries["cache"].append({"protocol": protocol + 4})
            requirement = {"transactions": True, "matching_protocol": True}
        else:
            formats = ("binary", "text", "columnar", "framed")
            regions = ("east", "west", "north", "south")
            fmt, other_fmt = formats[seed % 4], formats[(seed + 1) % 4]
            region, other_region = regions[(seed // 4) % 4], regions[(seed // 4 + 1) % 4]
            entries = {
                "encoder": [{"format": fmt}, {"format": other_fmt}, {"format": formats[(seed + 2) % 4]}],
                "transport": [
                    {"format": fmt, "region": region},
                    {"format": fmt, "region": other_region},
                    {"format": other_fmt, "region": region},
                ],
                "storage": [
                    {"region": region, "retention": quantity + seed % 11},
                    {"region": region, "retention": quantity - 1},
                    {"region": other_region, "retention": quantity + 12},
                ],
            }
            if extra:
                entries["encoder"].append({"format": formats[(seed + 3) % 4]})
                entries["transport"].append({"format": other_fmt, "region": other_region})
                entries["storage"].append({"region": region, "retention": quantity - 2})
            requirement = {"format": fmt, "region": region, "minimum_retention": quantity}
        catalog, expected = {}, {}
        for component, candidates in entries.items():
            catalog[component], expected[component] = _catalog(rng, candidates)
        writer.clear()
        writer.update({f"sources/{component}.json": _text(options) for component, options in catalog.items()})
        writer["sources/requirements.json"] = _text(requirement)
        reader["sources/request.json"] = _text(
            dict(
                requirements=requirement,
                component_keys=list(catalog),
                plan="No workflow actions; submit an empty array.",
            )
        )
        truth.update(expected_config=expected, catalog=catalog, requirements=requirement)
    elif family == "WS05":
        scopes = ("workspace-copper", "workspace-maple", "workspace-river", "workspace-cedar", "workspace-stone")
        scope, other_scope = scopes[seed % 5], scopes[(seed + 1) % 5]
        regions = ("east", "west", "north", "south")
        region, other_region = regions[seed % 4], regions[(seed + 1) % 4]
        revision = 2 + (seed * 17) % 97
        expected = {"region": region, "retention": quantity}
        decoy = {**expected, "region": other_region}
        records = [
            {"scope": other_scope, "revision": revision + 100, "config": decoy},
            {"scope": scope, "revision": revision - 1, "config": {**expected, "retention": quantity - 1}},
            {"scope": scope, "revision": revision, "config": expected.copy()},
        ]
        if variant:
            secure = bool(seed % 2)
            expected["encryption"] = secure
            decoy["encryption"] = not secure
            records.extend(
                [
                    {"scope": scope, "authority": "security", "encryption_required": secure},
                    {"scope": scope, "authority": "advisory", "revision": revision + 101, "encryption": not secure},
                ]
            )
        rng.shuffle(records)
        writer["sources/decisions.json"] = _text(records)
        reader["sources/policy.json"] = _text(
            dict(
                scope=scope,
                operational_revision=revision,
                security_overrides_advisory=bool(variant),
                keys=list(expected),
                plan="No workflow actions; submit an empty array.",
            )
        )
        truth.update(expected_config=expected, decoy_config=decoy)
    else:
        if variant == 0:
            public = dict(peak=quantity, reserve=1 + seed % 23, rule="capacity = peak + reserve")
            expected = {"capacity": public["peak"] + public["reserve"]}
        else:
            public = dict(
                east_load=quantity + (seed % 5 - 2) * 3,
                west_load=quantity + ((seed // 5) % 5 - 2) * 4,
                limit=quantity,
                rule="Each regional capacity is min(regional load, limit). Keep separate regions.",
            )
            expected = {
                f"{region}_capacity": min(public[f"{region}_load"], public["limit"]) for region in ("east", "west")
            }
        public["plan"] = "No workflow actions; submit an empty array."
        writer["sources/request.json"] = reader["sources/request.json"] = _text(public)
        truth["expected_config"] = expected
    return task
