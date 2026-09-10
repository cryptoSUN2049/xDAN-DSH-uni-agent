"""Core course business diversity; oracle helpers remain controller-only."""

import hashlib
import itertools
import json

import pytest

from examples.dsh.capabilities.work_state.core_tasks import make_core_task
from examples.dsh.capabilities.work_state.scoring import score_task
from examples.dsh.capabilities.work_state.tasks import make_task, oracle_memory, oracle_outputs

FAMILIES = ("WS01", "WS03", "WS05", "WS06")
TRAIN = [(f, 0, s) for f in FAMILIES for s in range(1001, 1041 if f == "WS06" else 1161)]
DEV = [(f, 1, s) for f in FAMILIES for s in range(2001, 2041)]


def visible(task):
    return json.dumps({k: task[k] for k in ("writer_files", "reader_files")}, sort_keys=True)


def test_exact_course_has_520_160_unique_visible_tasks_without_split_overlap():
    train = {visible(make_core_task(*item)) for item in TRAIN}
    dev = {visible(make_core_task(*item)) for item in DEV}
    assert len(train) == len(TRAIN) == 520
    assert len(dev) == len(DEV) == 160
    assert not train & dev


@pytest.mark.parametrize("family,variant,seed", TRAIN + DEV)
def test_every_course_task_oracle_wrong_config_and_public_fact_consistency(family, variant, seed):
    task = make_core_task(family, variant, seed)
    output = oracle_outputs(task)
    assert score_task(task, output)["reward"] == 1
    assert score_task(task, {**output, "config.json": b"{}"})["reward"] == 0
    truth = task["truth"]
    files = {k: json.loads(v) for k, v in task["writer_files"].items()}
    if family == "WS01":
        workflow = files["sources/workflow.json"]
        assert workflow["configuration_requirement"] == truth["expected_config"]
        for key in ("completed", "dependencies", "required"):
            assert workflow[key] == truth[key]
        for wrong in [truth["oracle_plan"][:-1], truth["oracle_plan"] * 2]:
            assert score_task(task, {**output, "plan.json": json.dumps(wrong).encode()})["reward"] == 0
    elif family == "WS03":
        catalog = truth["catalog"]
        assert all(files[f"sources/{k}.json"] == v for k, v in catalog.items())
        assert files["sources/requirements.json"] == truth["requirements"]
        public = json.loads(task["reader_files"]["sources/request.json"])
        assert public["requirements"] == truth["requirements"]
        solutions = []
        for values in itertools.product(*catalog.values()):
            config = dict(zip(catalog, values, strict=True))
            if score_task(task, {**output, "config.json": json.dumps(config).encode()})["reward"]:
                solutions.append(config)
        assert solutions == [truth["expected_config"]]
        assert all(name.startswith("option-") for entries in catalog.values() for name in entries)
    elif family == "WS05":
        policy = json.loads(task["reader_files"]["sources/policy.json"])
        records = files["sources/decisions.json"]
        chosen = [
            r["config"]
            for r in records
            if r["scope"] == policy["scope"] and r.get("revision") == policy["operational_revision"]
        ]
        assert len(chosen) == 1
        expected = chosen[0].copy()
        if variant:
            secure = [r for r in records if r["scope"] == policy["scope"] and r.get("authority") == "security"]
            assert len(secure) == 1
            expected["encryption"] = secure[0]["encryption_required"]
        assert expected == truth["expected_config"]
    else:
        assert task["writer_files"] == task["reader_files"]
        assert oracle_memory(task) == {}
        request = files["sources/request.json"]
        expected = (
            {"capacity": request["peak"] + request["reserve"]}
            if variant == 0
            else {f"{region}_capacity": min(request[f"{region}_load"], request["limit"]) for region in ("east", "west")}
        )
        assert expected == truth["expected_config"]


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("variant", (0, 1))
def test_identity_determinism_and_unchanged_public_contract(family, variant):
    task = make_core_task(family, variant, 7)
    old = make_task(family, variant, 7)
    assert task == make_core_task(family, variant, 7)
    assert task["task_id"] == f"work-state-memory-core-v1-{family.lower()}-v{variant}-s7"
    assert task["task_generation"] == "work-state-memory-core-v1"
    for key in ("schema", "protocol_revision", "writer_goal", "reader_goal", "memory_paths", "result_paths"):
        assert task[key] == old[key]
    assert "truth" not in visible(task) and "expected_config" not in visible(task)


def test_business_dimensions_change_not_only_identifiers():
    tasks = {f: [make_core_task(f, v, s) for s in range(1001, 1021) for v in (0, 1)] for f in FAMILIES}
    ws01 = [t["truth"] for t in tasks["WS01"]]
    assert len({t["expected_config"]["schema_version"] for t in ws01}) > 2
    assert len({len(t["dependencies"]) for t in ws01}) > 2
    assert len({len(t["completed"]) for t in ws01}) > 2
    assert len({json.dumps(t["truth"]["catalog"], sort_keys=True) for t in tasks["WS03"]}) == 40
    policies = [json.loads(t["reader_files"]["sources/policy.json"]) for t in tasks["WS05"]]
    assert len({p["scope"] for p in policies}) > 2
    assert len({p["operational_revision"] for p in policies}) > 2
    assert {t["truth"]["expected_config"]["encryption"] for t in tasks["WS05"] if t["variant"]} == {True, False}
    requests = [json.loads(t["reader_files"]["sources/request.json"]) for t in tasks["WS06"]]
    assert len({p["reserve"] for p in requests if "reserve" in p}) > 2


def test_legacy_generator_snapshot_is_unchanged():
    tasks = [make_task(f, v, 29) for f in FAMILIES for v in (0, 1)]
    assert (
        hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest()
        == "d0969835d7b9eea2ef7046588a2a0d73b42114eb760c3233eb4f0ee535d8a183"
    )


@pytest.mark.parametrize(
    "args", [("WS07", 0, 0), ("WS01", True, 0), ("WS01", 2, 0), ("WS01", 0, True), ("WS01", 0, -1), ("WS01", 0, 1.0)]
)
def test_invalid_generation_inputs_fail_closed(args):
    with pytest.raises(ValueError):
        make_core_task(*args)
