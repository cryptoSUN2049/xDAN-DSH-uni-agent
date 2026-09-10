import json
from pathlib import Path

import pytest

from examples.dsh.capabilities.audit_memory_training import audit_memory_training
from tests.uni_agent.examples.test_audit_memory_training import consumed
from tests.uni_agent.framework.test_native_memory_framework import wired as native_wired
from tests.uni_agent.framework.test_work_state_framework import (
    test_real_workstate_zero_quality_chain_reuses_original_tq as build_zero_chain,
)

wired = native_wired


async def prepare(wired, tmp_path, monkeypatch, partition="val"):
    # Existing CPU integration drives real Task/verifier/StageSpec/freeze/TQ;
    # only the model transport and subsequent trainer JSONL are simulated.
    await build_zero_chain(wired, tmp_path, monkeypatch, partition, budget=8192)
    memory_root = wired[0]._memory_operator.root
    crosswalk = next(memory_root.glob("groups/*/crosswalk.json"))
    run_root, _, _ = consumed(tmp_path, crosswalk)
    return run_root, memory_root, json.loads(crosswalk.read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("partition", ["train", "val"])
async def test_complete_zero_reward_workstate_consumption(wired, tmp_path, monkeypatch, partition):
    root, memory, _ = await prepare(wired, tmp_path, monkeypatch, partition)
    report = audit_memory_training(root, memory_root=memory, expected_run_id="memory-run")
    assert report["passed"], report
    assert report["summary"]["consumed_rows"] == (8 if partition == "train" else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["fixture", "source", "frozen", "unpacked", "output", "same_score_output"])
async def test_mutated_workstate_evidence_rejected(wired, tmp_path, monkeypatch, mutation):
    root, memory, record = await prepare(wired, tmp_path, monkeypatch)
    item = next(i for i in record["items"] if i["role"] == "B")
    receipt_path = Path(item["stage_receipt_path"])
    original_receipt = receipt_path.read_bytes()
    envelope = json.loads(receipt_path.with_name("agent-result.json").read_text())
    fixture_path = Path(envelope["metadata"]["fixture_path"])
    fixture = json.loads(fixture_path.read_text())
    if mutation == "fixture":
        fixture["task"]["truth"]["expected_config"] = {}
        fixture_path.write_text(json.dumps(fixture))
    elif mutation == "source":
        source = next(p for p in fixture["read_files"] if "/sources/" in p)
        Path(source).write_bytes(b"changed")
    elif mutation == "frozen":
        (Path(fixture["frozen_dir"]) / "memory.bin").write_bytes(b"changed")
    elif mutation == "unpacked":
        (Path(fixture["unpacked_root"]) / "index.md").write_text("fabricated index")
    elif mutation == "output":
        from examples.dsh.capabilities.work_state.tasks import oracle_outputs

        for name, raw in oracle_outputs(fixture["task"]).items():
            (Path(fixture["output_root"]) / name).write_bytes(raw)
    else:
        # Both {} and this wrong JSON score zero; bytes still must stay bound.
        (Path(fixture["output_root"]) / "config.json").write_bytes(b'{"wrong":1}')
    report = audit_memory_training(root, memory_root=memory, expected_run_id="memory-run")
    assert not report["passed"] and not report["consumption_verified"]
    assert report["groups"][0]["status"] == "rejected"
    assert receipt_path.read_bytes() == original_receipt
    if mutation == "same_score_output":
        assert any("output snapshot" in reason for reason in report["groups"][0]["reasons"])
