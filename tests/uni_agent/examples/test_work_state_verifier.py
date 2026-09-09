import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest

from examples.dsh.capabilities.memory_verifier import canonical, sha
from examples.dsh.capabilities.work_state import verifier
from examples.dsh.capabilities.work_state.tasks import make_task
from tests.uni_agent.examples.test_memory_training_verifier import DiskSandbox
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result
from tests.uni_agent.tasks.test_dsh_task import _config, _HarnessTask
from uni_agent.agents.base import AgentResult


@pytest.fixture
def case(tmp_path):
    memory, output = tmp_path / "memory", tmp_path / "output"
    memory.mkdir()
    output.mkdir()
    source = tmp_path / "source.json"
    source.write_text("source")
    return dict(
        schema="dsh.work-state-stage.v1",
        contract_id="work-state-v1",
        role="writer",
        chain_id="chain",
        source_version=sha(b"source"),
        task=make_task("WS01"),
        read_files={str(source): sha(b"source")},
        write_files=[str(memory / p) for p in make_task("WS01")["memory_paths"]],
        read_missing=[],
        memory_root=str(memory),
        output_root=str(output),
        max_bytes=65536,
    )


def ended(events=()):
    return [*events, {"type": "turn/end", "data": {"reason": {"kind": "completed"}}}]


def test_empty_or_bad_writer_memory_is_eligible_zero(case):
    for raw in [None, b"bad json"]:
        if raw is not None:
            Path(case["write_files"][0]).write_bytes(raw)
        result = verifier.score(case, ended(), "done", True, "A")
        assert result["eligible"] and result["reward"] == 0
        assert result["extra_info"]["reward_scope"] == "deferred-to-reader"


@pytest.mark.parametrize("target,command", [("source", "create"), ("unknown", "view")])
def test_unsafe_action_rejected_even_when_tool_denies(case, target, command):
    path = next(iter(case["read_files"])) if target == "source" else "/unapproved/path"
    events = ended(
        [_call("a", "str_replace_editor", {"command": command, "path": path}, seq=0), _result("a", "denied")]
    )
    result = verifier.score(case, events, "done", True, "A")
    assert not result["eligible"] and result["reward"] == 0


def test_allowed_missing_read_is_not_unsafe(case):
    path = case["write_files"][0]
    case["read_missing"] = [path]
    events = ended(
        [
            _call("a", "str_replace_editor", {"command": "view", "path": path, "view_range": [1, 2]}, seq=0),
            _result("a", "not found"),
        ]
    )
    assert verifier.score(case, events, "done", True, "A")["eligible"]


def test_missing_pair_and_changed_source_rejected(case):
    with pytest.raises((ValueError, RuntimeError)):
        verifier.score(case, ended([_call("a", "str_replace_editor", {}, seq=0)]), "done", True, "A")
    Path(next(iter(case["read_files"]))).write_text("tampered")
    with pytest.raises(ValueError):
        verifier.score(case, ended(), "done", True, "A")


def test_unfinished_is_ineligible(case):
    assert not verifier.score(case, ended(), "done", False, "A")["eligible"]


def run_cli(case, tmp_path, split="train", metadata_contract="work-state-v1", events=None):
    binding = dict(
        schema="dsh.memory-training-stage.v1",
        split=split,
        run_id="run",
        group_uid="group",
        sibling=0,
        checkpoint_identity="base",
    )
    case["training_stage"] = binding
    f = tmp_path / "fixture.json"
    f.write_bytes(canonical(case))
    gateway = "work-state-A"
    trace = tmp_path / "traces" / hashlib.sha256(gateway.encode()).hexdigest()[:24] / "session.jsonl"
    trace.parent.mkdir(parents=True)
    actual_events = ended() if events is None else events
    raw = b"".join(canonical(e) for e in actual_events)
    trace.write_bytes(raw)

    class Agent:
        async def run(self, **_):
            return AgentResult(
                output={"response": "done"},
                finished=True,
                info=dict(
                    adapter="uni-agent-dsh",
                    dsh_session_id="dsh-" + gateway,
                    gateway_session_id=gateway,
                    trace_sha256=sha(raw),
                    trace_path=str(trace),
                    event_count=len(actual_events),
                    finish_reason="completed",
                    keep_trace=True,
                ),
            )

    metadata = dict(
        environment_digest=sha(b"runtime"),
        verifier_id=verifier.VERIFIER_ID,
        verifier_version="1",
        verifier_code_digest=verifier.bundle_digest(),
        task_id=f"dsh/work-state/chain/{case['role']}",
        task_version="1",
        split=split,
        fixture_path=str(f),
        fixture_sha256=sha(f.read_bytes()),
        training_stage=binding,
        contract_id=metadata_contract,
    )
    config = _config(
        verifier_command=[sys.executable, "-m", "examples.dsh.capabilities.work_state.verifier"],
        environment_digest=sha(b"runtime"),
        verifier_id=verifier.VERIFIER_ID,
        verifier_version="1",
        verifier_code_digest=verifier.bundle_digest(),
        result_root=str(tmp_path / "results"),
        workdir=str(tmp_path),
        metadata=metadata,
    )
    return asyncio.run(_HarnessTask(config, DiskSandbox(), Agent()).run())


@pytest.mark.parametrize("split", ["train", "validation"])
def test_real_cli_fresh_zero_writer_receipt(case, tmp_path, split):
    result = run_cli(case, tmp_path, split)
    assert result.reward == 0 and result.finished
    info = result.extra_info["verifier"]
    receipt = json.loads(next((tmp_path / "results").glob("*/verifier-receipt.json")).read_text())
    assert receipt["eligible"] and receipt["fresh"]
    assert info["extra_info"]["training_stage"]["split"] == split


def test_real_cli_contract_mismatch_rejected(case, tmp_path):
    with pytest.raises(RuntimeError):
        run_cli(case, tmp_path, metadata_contract="old")


@pytest.fixture
def reader_case(case, tmp_path):
    from examples.dsh.capabilities.work_state.bundle import pack_bundle, unpack_bundle
    from examples.dsh.capabilities.work_state.tasks import oracle_memory, oracle_outputs
    from uni_agent.tasks.dsh.memory_artifacts import freeze_memory_artifact

    for name, raw in oracle_memory(case["task"]).items():
        (Path(case["memory_root"]) / name).write_bytes(raw)
    packed = pack_bundle(Path(case["memory_root"]), case["task"]["memory_paths"])
    (tmp_path / "packed.bin").write_bytes(packed)
    frozen = freeze_memory_artifact(
        source_root=tmp_path,
        relative_path="packed.bin",
        expected_source_sha256=sha(packed),
        source_version=case["source_version"],
        chain_id=case["chain_id"],
        writer_session_id="A",
        max_bytes=196608,
        output_dir=tmp_path / "frozen",
    )
    unpack_bundle(packed, tmp_path / "unpacked", case["task"]["memory_paths"])
    case.update(
        role="reader",
        writer_binding=dict(
            manifest_sha256=frozen.manifest_sha256,
            content_sha256=frozen.content_sha256,
            dsh_session_id="A",
            receipt_id=sha(b"receipt"),
        ),
        frozen_dir=str(tmp_path / "frozen"),
        bundle_paths=case["task"]["memory_paths"],
        unpacked_root=str(tmp_path / "unpacked"),
        write_files=[str(Path(case["output_root"]) / p) for p in case["task"]["result_paths"]],
    )
    events = []
    for i, (name, raw) in enumerate(oracle_outputs(case["task"]).items()):
        target = Path(case["output_root"]) / name
        target.write_bytes(raw)
        events += [
            _call(
                str(i),
                "str_replace_editor",
                {"command": "create", "path": str(target), "file_text": raw.decode()},
                seq=i,
            ),
            _result(str(i), "created"),
        ]
    return case, ended(events)


def test_reader_real_frozen_bundle_and_actual_writes_credit(reader_case):
    fixture, events = reader_case
    result = verifier.score(fixture, events, "not an answer", True, "B")
    assert result["eligible"] and result["reward"] == 1
    assert result["extra_info"]["reward_scope"] == "terminal-business-result"


def test_preseeded_result_without_successful_write_not_credited(reader_case):
    fixture, _ = reader_case
    result = verifier.score(fixture, ended(), "perfect answer", True, "B")
    assert result["eligible"] and result["reward"] == 0


def test_reader_bad_json_or_missing_artifact_is_legal_zero(reader_case):
    fixture, events = reader_case
    target = Path(fixture["output_root"]) / "config.json"
    target.write_bytes(b"bad")
    result = verifier.score(fixture, events, "done", True, "B")
    assert result["eligible"] and result["reward"] == 0
    target.unlink()
    assert verifier.score(fixture, events, "done", True, "B")["eligible"]


@pytest.mark.parametrize("mutation", ["unpacked", "frozen", "missing_inventory", "writer_identity", "reader_identity"])
def test_reader_freeze_tamper_rejected(reader_case, mutation):
    fixture, events = reader_case
    if mutation == "unpacked":
        (Path(fixture["unpacked_root"]) / "index.md").write_bytes(b"changed")
    if mutation == "frozen":
        (Path(fixture["frozen_dir"]) / "memory.bin").write_bytes(b"changed")
    if mutation == "missing_inventory":
        (Path(fixture["unpacked_root"]) / "handoff.md").write_bytes(b"new")
    if mutation == "writer_identity":
        fixture["writer_binding"]["dsh_session_id"] = "other"
    with pytest.raises((ValueError, OSError)):
        verifier.score(fixture, events, "done", True, "A" if mutation == "reader_identity" else "B")


def test_real_reader_cli_scores_actual_output_artifacts(reader_case, tmp_path):
    fixture, events = reader_case
    result = run_cli(fixture, tmp_path, events=events)
    assert result.reward == 1 and result.finished
    receipt = json.loads(next((tmp_path / "results").glob("*/verifier-receipt.json")).read_text())
    assert receipt["eligible"] and receipt["fresh"]


def test_business_failure_cannot_be_fixed_by_response_claim(reader_case):
    fixture, events = reader_case
    (Path(fixture["output_root"]) / "config.json").write_bytes(b"{}")
    result = verifier.score(fixture, events, "All done, configuration is correct", True, "B")
    assert result["eligible"] and result["reward"] == 0


def test_same_reward_output_mutation_changes_fresh_receipt_evidence(reader_case, tmp_path):
    fixture, events = reader_case
    target = Path(fixture["output_root"]) / "config.json"
    target.write_bytes(b"{}")
    assert run_cli(fixture, tmp_path, events=events).reward == 0
    receipt = json.loads(next((tmp_path / "results").glob("*/verifier-receipt.json")).read_text())
    original = verifier.score(fixture, events, "done", True, "B")
    digest = original["extra_info"]["output_snapshot_sha256"]
    assert len(receipt["evidence"]) == 6
    assert receipt["evidence"][5] == digest
    target.write_bytes(b'{"wrong":true}')
    changed = verifier.score(fixture, events, "done", True, "B")
    assert changed["reward"] == original["reward"] == 0
    assert changed["extra_info"]["output_snapshot_sha256"] != digest
    assert changed["extra_info"]["output_snapshot_sha256"] not in receipt["evidence"]


def test_missing_inventory_changes_output_snapshot(reader_case):
    fixture, events = reader_case
    target = Path(fixture["output_root"]) / "config.json"
    target.unlink()
    missing = verifier.score(fixture, events, "done", True, "B")
    target.write_bytes(b"{}")
    present = verifier.score(fixture, events, "done", True, "B")
    assert missing["reward"] == present["reward"] == 0
    assert missing["extra_info"]["output_snapshot_sha256"] != present["extra_info"]["output_snapshot_sha256"]
