"""Fixed short-course instances; private truth is never an actor input."""

import json
import random

COURSE_ID = "work-state-short-fact-v1"


def make_short_task(variant: int, seed: int) -> dict:
    if type(variant) is not int or variant not in (0, 1) or type(seed) is not int or seed < 0:
        raise ValueError("Unsupported short-course variant/seed")
    # Seed-indexed permutation gives distinct prescribed train values without looking at model outcomes.
    values = random.Random(70419).sample(range(40, 400), 360)
    capacity = values[seed % 360] if variant == 0 else 1000 + random.Random(seed).randrange(1000)
    source = {"service": "worker", "capacity": capacity}
    name = "sources/service.json"
    if variant == 1:
        source = {"service": "worker", "limits": {"capacity_units": capacity}}
        name = "sources/deployment.json"
    return dict(
        schema="dsh.work-state-task.v1",
        protocol_revision=1,
        course_id=COURSE_ID,
        task_id=f"{COURSE_ID}-ws07-v{variant}-s{seed}",
        family="WS07",
        variant=variant,
        seed=seed,
        writer_goal=(
            "Preserve the worker service capacity from the read-only source for a fresh session. "
            "Read the source first. Create handoff.md containing the supported service/capacity facts, "
            "then create index.md pointing to handoff.md by its relative name. These destinations start "
            "empty; use command=create and file_text. Do not change the source or perform the later "
            "configuration task. Only saved file bytes reach the next session; your final response does "
            "not. After saving the two files, finish. Re-reading unchanged files is unnecessary."
        ),
        reader_goal=(
            "Recover the worker service capacity through the memory index at the supplied path. "
            "Read the index, then the handoff it references, before producing results. Create config.json "
            "with exactly one integer field named capacity, using the recovered value, and plan.json as "
            "an empty JSON array. File contents are business JSON, not tool-call arguments. Do not guess "
            "missing facts or change memory. Only successful file writes count as outputs. Finish after "
            "writing the two result files."
        ),
        writer_files={name: json.dumps(source, sort_keys=True, indent=2) + "\n"},
        reader_files={},
        memory_paths=["index.md", "handoff.md"],
        result_paths=["config.json", "plan.json"],
        truth=dict(
            expected_config={"capacity": capacity},
            dependencies={},
            completed=[],
            required=[],
            oracle_plan=[],
            structure="flat-service-capacity" if variant == 0 else "nested-deployment-limits",
        ),
    )
