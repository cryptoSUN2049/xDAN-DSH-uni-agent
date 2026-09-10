import json
from pathlib import Path

import pytest

from examples.dsh.capabilities.audit_memory_training import audit_memory_training
from tests.uni_agent.framework.test_native_memory_framework import run
from tests.uni_agent.framework.test_native_memory_framework import wired as framework_wired

wired = framework_wired


def consumed(tmp_path, crosswalk):
    root = tmp_path / "trainer"
    root.mkdir(exist_ok=True)
    (root / "run-manifest.json").write_text(json.dumps({"status": "completed"}))
    record = json.loads(crosswalk.read_text())
    folder = root / ("rollouts" if record["partition"] == "train" else "validation")
    folder.mkdir(exist_ok=True)
    terminal = {
        json.loads(Path(c["receipt_path"]).read_text())["chain_id"]: json.loads(Path(c["receipt_path"]).read_text())[
            "terminal_reward"
        ]
        for c in record["chains"]
    }
    rows = [
        dict(
            uid=i["tq_key"],
            step=record["global_steps"],
            score=terminal[i["chain_id"]] if record["partition"] == "val" else i["stage_reward"],
        )
        for i in record["items"]
    ]
    file = folder / "7.jsonl"
    file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return root, file, rows


@pytest.mark.asyncio
@pytest.mark.parametrize("partition", ["train", "val"])
async def test_real_stage_crosswalk_independent_consumption(wired, tmp_path, partition):
    framework, *_ = wired
    await run(framework, partition)
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    root, _, rows = consumed(tmp_path, crosswalk)
    report = audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")
    assert report["passed"] and report["consumption_verified"]
    assert report["summary"]["consumed_rows"] == len(rows)
    assert report["groups"][0]["crosswalk_consumption_verified"] is False
    assert json.loads(crosswalk.read_text())["status"] == "prepared-not-consumed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["missing", "duplicate", "unknown", "step", "score", "partition", "unsubmitted", "hash", "version", "trace"],
)
async def test_reject_invalid_or_incomplete_consumption(wired, tmp_path, failure):
    framework, *_ = wired
    await run(framework, "val")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    root, file, rows = consumed(tmp_path, crosswalk)
    if failure == "missing":
        rows.pop()
    elif failure == "duplicate":
        rows.append(rows[0].copy())
    elif failure == "unknown":
        rows.append(dict(uid="unknown_0_0", step=7, score=1))
    elif failure == "step":
        rows[0]["step"] = 8
    elif failure == "score":
        rows[0]["score"] = 0.25
    elif failure == "partition":
        file.unlink()
        (root / "rollouts").mkdir()
        file = root / "rollouts/7.jsonl"
    elif failure == "unsubmitted":
        crosswalk.with_name("submission.json").unlink()
    elif failure == "hash":
        record = json.loads(crosswalk.read_text())
        Path(record["items"][0]["stage_npz_path"]).write_bytes(b"changed")
    elif failure == "version":
        record = json.loads(crosswalk.read_text())
        record["items"][0]["version_evidence"]["version_evidence_complete"] = False
        crosswalk.write_text(json.dumps(record))
    elif failure == "trace":
        record = json.loads(crosswalk.read_text())
        result = Path(record["items"][0]["stage_receipt_path"]).parents[1]
        next((result.parent / "traces").glob("*/session.jsonl")).write_bytes(b"changed")
    file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    report = audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")
    assert not report["passed"] and not report["consumption_verified"]


@pytest.mark.asyncio
async def test_submission_alone_never_proves_consumption(wired, tmp_path):
    framework, *_ = wired
    await run(framework, "val")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    root, file, _ = consumed(tmp_path, crosswalk)
    file.unlink()
    report = audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")
    assert not report["passed"]
    assert report["groups"][0]["status"] == "submitted-unconsumed"
    assert report["groups"][0]["submission_verified"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["frozen", "sibling", "submission_keys", "run_id", "nonfinite", "truncated", "not_completed"]
)
async def test_bound_evidence_and_terminal_failures(wired, tmp_path, failure):
    framework, *_ = wired
    await run(framework, "val")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    root, file, _ = consumed(tmp_path, crosswalk)
    record = json.loads(crosswalk.read_text())
    if failure == "frozen":
        receipt = json.loads(Path(record["chains"][0]["receipt_path"]).read_text())
        Path(receipt["frozen_content_path"]).write_bytes(b"changed")
    elif failure == "sibling":
        record["chains"] = []
        crosswalk.write_text(json.dumps(record))
    elif failure == "submission_keys":
        submission = json.loads(crosswalk.with_name("submission.json").read_text())
        submission["keys"].reverse()
        crosswalk.with_name("submission.json").write_text(json.dumps(submission))
    elif failure == "nonfinite":
        file.write_text('{"uid":"group-1_0_0","step":7,"score":NaN}\n')
    elif failure == "truncated":
        with file.open("a") as output:
            output.write('{"uid":')
    elif failure == "not_completed":
        (root / "run-manifest.json").write_text('{"status":"running"}')
    report = audit_memory_training(
        root,
        memory_root=framework._memory_operator.root,
        expected_run_id="different" if failure == "run_id" else "memory-run",
    )
    assert not report["passed"]
    assert report["consumption_verified"] is (failure == "not_completed")


def test_empty_run_cannot_pass(tmp_path):
    (tmp_path / "run-manifest.json").write_text('{"status":"completed"}')
    report = audit_memory_training(tmp_path, memory_root=tmp_path, expected_run_id="memory-run")
    assert not report["passed"] and not report["consumption_verified"]


@pytest.mark.asyncio
async def test_failed_queue_write_never_claims_submitted(wired, tmp_path):
    framework, _, queue, _ = wired
    queue.fail = True
    await run(framework, "val")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    root, file, _ = consumed(tmp_path, crosswalk)
    file.unlink()
    report = audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")
    assert report["groups"][0]["status"] == "prepared-unsubmitted"
    assert not report["groups"][0]["submission_verified"]
    assert not report["passed"]


@pytest.mark.asyncio
async def test_fixed_verl_training_logger_retains_a1_b0_scores(wired, tmp_path, monkeypatch):
    """Execute pinned logger/write methods over actual framework TQ fields on CPU."""
    import ast
    import os
    from contextlib import nullcontext
    from types import SimpleNamespace

    import numpy as np
    import torch

    from tests.uni_agent.tasks.test_dsh_task import _HarnessTask

    original = _HarnessTask.build_agent

    def altered_reader(self):
        agent = original(self)
        original_run = agent.run

        async def run_agent(**kwargs):
            result = await original_run(**kwargs)
            if self.config.metadata["task_id"].endswith("/reader"):
                result.output["response"] = '{"status":"answer","facts":{},"source_version":"wrong"}'
            return result

        agent.run = run_agent
        return agent

    monkeypatch.setattr(_HarnessTask, "build_agent", altered_reader)
    framework, _, queue, _ = wired
    await run(framework, "train")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    root, file, _ = consumed(tmp_path, crosswalk)
    file.unlink()
    source = Path("verl/verl/trainer/ppo/v1/trainer_base.py")
    tree = ast.parse(source.read_text())
    methods = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name in ("_log_rollout_data", "_write_generations")
    ]
    for method in methods:
        method.decorator_list = []
    batch = queue.batches[0]
    fields = batch["fields"]

    def fetch(**kwargs):
        assert kwargs["keys"] == batch["keys"]
        # Actual stage rm_scores; only absent task reward_model is represented as None.
        return {name: fields.get(name) for name in kwargs["select_fields"]}

    scope = dict(
        os=os,
        json=json,
        np=np,
        torch=torch,
        KVBatchMeta=object,
        marked_timer=lambda *a, **kw: nullcontext(),
        tq=SimpleNamespace(kv_batch_get=fetch),
    )
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), scope)
    trainer = SimpleNamespace(tokenizer=SimpleNamespace(pad_token_id=0, decode=lambda ids, **kw: "CPU"))
    trainer._dump_generations = lambda **kw: scope["_write_generations"](**kw, global_steps=7)
    scope["_log_rollout_data"](trainer, SimpleNamespace(keys=batch["keys"], partition_id="train"), {}, str(file.parent))
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    assert [row["score"] for row in rows] == [1.0, 0.0] * 4
    assert audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")[
        "passed"
    ]
    # Validation-style broadcast is invalid for the training rollout logger.
    rows[0]["score"] = 0.0
    file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert not audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")[
        "passed"
    ]
    # The actual advantage writeback cannot overwrite rm_scores.
    advance = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_compute_advantage")
    assignments = [
        n
        for n in ast.walk(advance)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "fields" for t in n.targets)
    ]
    assert ast.literal_eval(max(assignments, key=lambda n: n.lineno).value) == ["advantages", "returns"]


@pytest.mark.asyncio
async def test_multiple_contexts_must_all_be_consumed(wired, tmp_path):
    from copy import deepcopy

    framework, manager, _, _ = wired
    original = manager.finalize_session

    async def contexts(session_id):
        trajectories = await original(session_id)
        return [deepcopy(trajectories[0]), trajectories[0]]

    manager.finalize_session = contexts
    result = await run(framework, "val")
    assert result["num_success_sessions"] == 1, result
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    root, file, rows = consumed(tmp_path, crosswalk)
    assert len(rows) == 4
    assert audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")[
        "passed"
    ]
    rows.pop(1)  # Missing the second real A context, despite B being present.
    file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    report = audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")
    assert not report["passed"]
    assert report["groups"][0]["missing_keys"] == ["group-1_0_1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("group_uid", "other"), ("session_index", 3), ("num_trajectories", 2)])
async def test_original_stage_scope_and_context_count_checked(wired, field, value):
    from examples.dsh.capabilities.audit_memory_training import _stage_lineage

    framework, *_ = wired
    await run(framework, "val")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(crosswalk.read_text())
    meta_path = Path(record["items"][0]["stage_json_path"])
    meta = json.loads(meta_path.read_text())
    meta[field] = value
    meta_path.write_text(json.dumps(meta))
    # Exercise the semantic check independently of the earlier crosswalk SHA gate.
    with pytest.raises(ValueError, match="Stage"):
        _stage_lineage(record)


def test_short_course_requires_bound_run_plan(tmp_path):
    from examples.dsh.capabilities.audit_memory_training import _validate_task_course

    task = {"family": "WS07", "course_id": "work-state-short-fact-v1"}
    with pytest.raises((ValueError, FileNotFoundError)):
        _validate_task_course(task, tmp_path)
    plan = tmp_path / "memory-launch-plan.json"
    plan.write_text(json.dumps({"course_id": "work-state-v1"}))
    with pytest.raises(ValueError, match="course"):
        _validate_task_course(task, tmp_path)


def test_short_course_rechecks_dataset_plan_binding(tmp_path):
    from examples.dsh.capabilities.audit_memory_training import _validate_task_course, sha

    task = {"family": "WS07", "course_id": "work-state-short-fact-v1"}
    plan = tmp_path / "memory-launch-plan.json"
    plan.write_text(json.dumps({"course_id": task["course_id"]}))
    manifest = tmp_path / "run-manifest.json"
    manifest.write_text(
        json.dumps({"paths": {"dataset_manifest": str(plan)}, "sha256": {"dataset_manifest": sha(plan.read_bytes())}})
    )
    _validate_task_course(task, tmp_path)
    plan.write_text(plan.read_text() + " ")
    with pytest.raises(ValueError, match="binding"):
        _validate_task_course(task, tmp_path)


def test_legacy_course_does_not_need_new_plan(tmp_path):
    from examples.dsh.capabilities.audit_memory_training import _validate_task_course

    _validate_task_course({"family": "WS01"}, tmp_path)
    with pytest.raises(ValueError, match="course"):
        _validate_task_course({"family": "WS01", "course_id": "work-state-short-fact-v1"}, tmp_path)


def test_short_course_cannot_reload_foreign_course(tmp_path):
    from examples.dsh.capabilities.audit_memory_training import _validate_task_course, sha

    task = {"family": "WS07", "course_id": "work-state-short-fact-v1"}
    plan = tmp_path / "memory-launch-plan.json"
    plan.write_text(json.dumps({"course_id": task["course_id"], "checkpoint_origin": {"course_id": "work-state-v1"}}))
    (tmp_path / "run-manifest.json").write_text(
        json.dumps({"paths": {"dataset_manifest": str(plan)}, "sha256": {"dataset_manifest": sha(plan.read_bytes())}})
    )
    with pytest.raises(ValueError, match="mother course"):
        _validate_task_course(task, tmp_path)


@pytest.mark.asyncio
async def test_validation_broadcasts_verified_terminal_reward(wired, tmp_path, monkeypatch):
    from tests.uni_agent.tasks.test_dsh_task import _HarnessTask

    original = _HarnessTask.build_agent

    def altered_reader(self):
        agent = original(self)
        original_run = agent.run

        async def run_agent(**kwargs):
            result = await original_run(**kwargs)
            if self.config.metadata["task_id"].endswith("/reader"):
                result.output["response"] = '{"status":"answer","facts":{},"source_version":"wrong"}'
            return result

        agent.run = run_agent
        return agent

    monkeypatch.setattr(_HarnessTask, "build_agent", altered_reader)
    framework, *_ = wired
    await run(framework, "val")
    crosswalk = next(framework._memory_operator.root.glob("groups/*/crosswalk.json"))
    record = json.loads(crosswalk.read_text())
    assert [item["stage_reward"] for item in record["items"]] == [1.0, 0.0]
    root, file, rows = consumed(tmp_path, crosswalk)
    assert [row["score"] for row in rows] == [0.0, 0.0]
    assert audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")[
        "passed"
    ]
    rows[0]["score"] = 1.0
    file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert not audit_memory_training(root, memory_root=framework._memory_operator.root, expected_run_id="memory-run")[
        "passed"
    ]


def test_pinned_validation_dump_broadcasts_final_sample_per_session():
    """Execute the actual pinned validation dump block with unequal A/B scores."""
    import ast
    from types import SimpleNamespace

    source = Path("verl/verl/trainer/ppo/v1/trainer_base.py")
    tree = ast.parse(source.read_text())
    validate = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_validate")
    block = next(
        n
        for n in validate.body
        if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "val_data_dir"
    )
    captured = {}
    scope = dict(
        self=SimpleNamespace(_dump_generations=lambda **kw: captured.update(kw)),
        val_data_dir="unused",
        dump_all_keys=["group_0_1", "group_0_0", "other_0_0", "other_0_1"],
        dump_all_inputs=["B", "A", "A2", "B2"],
        dump_all_outputs=["b", "a", "a2", "b2"],
        session_to_sample_idx={"group_0": 0, "other_0": 1},
        sample_gts=["truth", "truth2"],
        sample_scores=[1.0, 0.0],
        reward_extra_infos_dict={},
    )
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(source), "exec"), scope)
    assert captured["reward_extra_infos_dict"]["uid"] == ["group_0_0", "group_0_1", "other_0_0", "other_0_1"]
    assert captured["scores"] == [1.0, 1.0, 0.0, 0.0]


@pytest.mark.parametrize("generation", ["unknown", None])
def test_audit_rejects_unknown_generation(tmp_path, generation):
    from examples.dsh.capabilities.audit_memory_training import _validate_task_course

    with pytest.raises(ValueError, match="generation"):
        _validate_task_course({"family": "WS01", "task_generation": generation}, tmp_path)


def test_core_generation_requires_matching_plan_and_full_binding(tmp_path):
    from examples.dsh.capabilities.audit_memory_training import _validate_task_course, sha

    task = {"family": "WS01", "task_generation": "work-state-memory-core-v1"}
    plan = tmp_path / "memory-launch-plan.json"
    plan.write_text(json.dumps({"course_id": "work-state-v1"}))
    with pytest.raises(ValueError, match="course"):
        _validate_task_course(task, tmp_path)
    plan.write_text(json.dumps({"course_id": "work-state-memory-core-v1"}))
    (tmp_path / "run-manifest.json").write_text(
        json.dumps({"paths": {"dataset_manifest": str(plan)}, "sha256": {"dataset_manifest": sha(plan.read_bytes())}})
    )
    _validate_task_course(task, tmp_path)
    plan.write_text(plan.read_text() + " ")
    with pytest.raises(ValueError, match="binding"):
        _validate_task_course(task, tmp_path)
