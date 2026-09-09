import copy
import json
from pathlib import PurePosixPath

import pytest

from examples.dsh.capabilities.work_state.scoring import score_task
from examples.dsh.capabilities.work_state.tasks import make_task, oracle_memory, oracle_outputs


@pytest.mark.parametrize("family", ["WS01", "WS03", "WS05", "WS06"])
@pytest.mark.parametrize("variant", [0, 1])
def test_reproducible_task_and_oracle(family, variant):
    task = make_task(family, variant, 29)
    assert task == make_task(family, variant, 29)
    assert task != make_task(family, variant, 30)
    assert score_task(task, oracle_outputs(task))["reward"] == 1
    assert len(task["memory_paths"]) <= 6
    assert task["result_paths"] == ["config.json", "plan.json"]
    for files in [task["writer_files"], task["reader_files"]]:
        assert files
        assert all(not PurePosixPath(p).is_absolute() and ".." not in PurePosixPath(p).parts for p in files)
        assert all(isinstance(v, str) for v in files.values())
        assert not set(files) & set(task["memory_paths"] + task["result_paths"])
    assert set(oracle_memory(task)) <= set(task["memory_paths"])
    assert "oracle_outputs" not in task and "oracle_memory" not in task


@pytest.mark.parametrize("family", ["WS01", "WS03", "WS05", "WS06"])
def test_variants_change_business_structure(family):
    assert make_task(family, 0, 3)["truth"]["structure"] != make_task(family, 1, 3)["truth"]["structure"]


@pytest.mark.parametrize(
    "outputs",
    [
        {},
        {"config.json": b"{"},
        {"config.json": b"null"},
        {"config.json": b"\xff"},
        {"config.json": b'{"x":1,"x":2}'},
        {"config.json": b'{"x":NaN}'},
        {"config.json": b"[]"},
        {"config.json": "not bytes"},
    ],
)
def test_bad_output_is_quality_zero(outputs):
    result = score_task(make_task("WS01"), outputs)
    assert result["reward"] == 0 and result["errors"]
    assert 0 <= result["verified_progress"] <= 1


def test_ws01_real_dependency_order_and_no_repeat():
    task = make_task("WS01", 1)
    outputs = oracle_outputs(task)
    plan = json.loads(outputs["plan.json"])
    for actions in [list(reversed(plan)), [task["truth"]["completed"][0]] + plan, plan + plan, plan[:-1]]:
        bad = {**outputs, "plan.json": json.dumps(actions).encode()}
        assert score_task(task, bad)["reward"] == 0
    # Valid alternative topological order should pass, not exact oracle imitation.
    alt = plan.copy()
    alt[0], alt[1] = alt[1], alt[0]
    assert score_task(task, {**outputs, "plan.json": json.dumps(alt).encode()})["reward"] == 1


def test_ws03_incompatible_component_pair_fails():
    task = make_task("WS03")
    output = oracle_outputs(task)
    config = json.loads(output["config.json"])
    config["cache"] = "option-b" if config["cache"] == "option-a" else "option-a"
    assert score_task(task, {**output, "config.json": json.dumps(config).encode()})["reward"] == 0


def test_ws05_newer_wrong_scope_does_not_win():
    task = make_task("WS05")
    output = oracle_outputs(task)
    assert (
        score_task(task, {**output, "config.json": json.dumps(task["truth"]["decoy_config"]).encode()})["reward"] == 0
    )


def test_ws06_public_reader_material_is_sufficient_without_memory():
    task = make_task("WS06", 0, 7)
    public = json.loads(task["reader_files"]["sources/request.json"])
    outputs = {"config.json": json.dumps({"capacity": public["peak"] + public["reserve"]}).encode(), "plan.json": b"[]"}
    assert oracle_memory(task) == {}
    assert score_task(task, outputs)["reward"] == 1


def test_scoring_no_mutation_and_no_memory_file_bonus():
    task = make_task("WS01")
    original = copy.deepcopy(task)
    out = oracle_outputs(task)
    result = score_task(task, out)
    assert score_task(task, {**out, "memory.json": b"look I wrote memory"})["reward"] == 0
    assert task == original and result["reward"] == 1


@pytest.mark.parametrize(
    "args", [("other", 0, 0), ("WS01", 2, 0), ("WS01", True, 0), ("WS01", 0, True), ("WS01", 0, -1)]
)
def test_invalid_controller_spec_rejected(args):
    with pytest.raises(ValueError):
        make_task(*args)


@pytest.mark.parametrize("variant", [0, 1])
def test_ws03_names_do_not_encode_solution_and_seed_changes_assignment(variant):
    chosen = set()
    for seed in range(12):
        task = make_task("WS03", variant, seed)
        solution = json.loads(oracle_outputs(task)["config.json"])
        chosen.add(tuple(sorted(solution.items())))
        for component, name in solution.items():
            assert name in ("option-a", "option-b")
            assert name in json.loads(task["writer_files"][f"sources/{component}.json"])
    assert len(chosen) > 1


def test_ws03_accepts_another_compatible_pair_not_only_oracle():
    task = make_task("WS03")
    chosen = task["truth"]["expected_config"]
    catalog = task["truth"]["catalog"]
    catalog["database"]["another"] = copy.deepcopy(catalog["database"][chosen["database"]])
    catalog["cache"]["another"] = copy.deepcopy(catalog["cache"][chosen["cache"]])
    outputs = oracle_outputs(task)
    outputs["config.json"] = b'{"database":"another","cache":"another"}'
    assert score_task(task, outputs)["reward"] == 1


@pytest.mark.parametrize("variant", [0, 1])
def test_ws03_every_single_component_constraint_violation_fails(variant):
    task = make_task("WS03", variant)
    outputs = oracle_outputs(task)
    chosen = json.loads(outputs["config.json"])
    for component, name in chosen.items():
        bad = {**chosen, component: "option-b" if name == "option-a" else "option-a"}
        assert score_task(task, {**outputs, "config.json": json.dumps(bad).encode()})["reward"] == 0


# Frozen revision-2 source/truth/oracle fingerprints; protocol wording may change.
REVISION2_BUSINESS_SHA256 = {
    "WS01:0": "f9c77af68dae78c1a96eba81576a4148eaadde914b1d7c7a068c67585de5c5ac",
    "WS01:1": "7cec8474c401b1bc14e2bc632ecf76bb01e41341e4cbd60e5853a58d5debfaef",
    "WS03:0": "198101363613bbbba99c9aa1fcb193d4c011d8c4044053a2cd10337f5aa53f0d",
    "WS03:1": "7bd74669a2590857ecb5bea2992b318f637031b133200270481500596da12496",
    "WS05:0": "6f782ad12dbb5c18c5898d5509a125f8d63ed5b6cae72530bfd5979e0a026e1f",
    "WS05:1": "97dbfcc216abdec5d4374960285a25c151151bf3915fbe15d2bb134a234ee647",
    "WS06:0": "9003ed16038ad048942c22d856f0147f7d615fc4c22ec33fa5ca696a736c9c6b",
    "WS06:1": "4da8caab676772cc7a43fdedc4ef656265b85d2e465bfec2c44eab86d4063274",
}


@pytest.mark.parametrize("family", ["WS01", "WS03", "WS05", "WS06"])
@pytest.mark.parametrize("variant", [0, 1])
def test_revision3_public_contract_without_answer_or_business_mutation(family, variant):
    import hashlib

    task = make_task(family, variant, 29)
    assert task["protocol_revision"] == 3
    assert task["reader_goal"] == make_task(family, variant, 30)["reader_goal"]
    assert "top-level" in task["reader_goal"]
    assert "not editor commands" in task["reader_goal"]
    assert "final chat response is not transferred" in task["writer_goal"]
    payload = {k: task[k] for k in ["writer_files", "reader_files", "truth"]}
    payload["oracle_memory"] = {k: b.hex() for k, b in oracle_memory(task).items()}
    payload["oracle_outputs"] = {k: b.hex() for k, b in oracle_outputs(task).items()}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    assert digest == REVISION2_BUSINESS_SHA256[f"{family}:{variant}"]
    assert score_task(task, oracle_outputs(task))["reward"] == 1


@pytest.mark.parametrize("variant", [0, 1])
def test_revision3_ws06_reader_gets_exact_keys_and_can_solve_public_formula(variant):
    task = make_task("WS06", variant, 71)
    source = json.loads(task["reader_files"]["sources/request.json"])
    config = (
        {"capacity": source["peak"] + source["reserve"]}
        if variant == 0
        else {
            "east_capacity": min(source["east_load"], source["limit"]),
            "west_capacity": min(source["west_load"], source["limit"]),
        }
    )
    assert all(name in task["reader_goal"] for name in config)
    assert "integer" in task["reader_goal"]
    assert "empty array" in task["reader_goal"]
    assert score_task(task, {"config.json": json.dumps(config).encode(), "plan.json": b"[]"})["reward"] == 1
    assert oracle_memory(task) == {}
    assert "without creating" in task["writer_goal"]


@pytest.mark.parametrize("variant", [0, 1])
def test_revision3_business_schema_and_action_identity(variant):
    ws1 = make_task("WS01", variant)["reader_goal"]
    assert all(term in ws1 for term in ["capacity", "schema_version", "integer", "completed", "dependencies"])
    ws3 = make_task("WS03", variant)["reader_goal"]
    for component in ["database", "cache"] if variant == 0 else ["encoder", "transport", "storage"]:
        assert component in ws3
    assert "option ID" in ws3 and "string" in ws3
    ws5 = make_task("WS05", variant)["reader_goal"]
    assert all(term in ws5 for term in ["policy.keys", "scope", "revision", "authority", "region", "retention"])
    if variant:
        assert "encryption" in ws5 and "boolean" in ws5
