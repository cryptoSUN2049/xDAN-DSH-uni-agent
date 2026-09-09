import json
from pathlib import Path

import pytest

from examples.dsh.capabilities.audit_memory_generation_boundaries import (
    audit_generation_boundaries,
    generation_segments,
)
from examples.dsh.capabilities.memory_verifier import sha
from tests.uni_agent.examples import test_work_state_stage as helper
from tests.uni_agent.examples.test_work_state_consumption import prepare
from tests.uni_agent.framework.test_native_memory_framework import wired as native_wired

wired = native_wired


def test_multiple_segments_eos_context_and_capacity_tie():
    result = generation_segments(
        [1], [7, 9, 8, 7, 9], [1, 1, 0, 1, 1], eos_ids={9}, vocab_size=20, generation_count=2, capacity_tokens=6
    )
    assert result["all_segments_end_eos"]
    assert [s["end_response_offset"] for s in result["segments"]] == [2, 5]
    assert result["segments"][1]["eos_capacity_tie"]
    assert all(s["original_finish_reason"] is None for s in result["segments"])


@pytest.mark.parametrize(
    "ids,mask,count",
    [
        ([], [], 1),
        ([True], [1], 1),
        ([-1], [1], 1),
        ([20], [1], 1),
        ([1.5], [1], 1),
        ([9], [2], 1),
        ([9], [0], 1),
        ([9], [1], 2),
    ],
)
def test_reject_invalid_or_unobservable_boundaries(ids, mask, count):
    with pytest.raises(ValueError):
        generation_segments([1], ids, mask, eos_ids={9}, vocab_size=20, generation_count=count, capacity_tokens=6)


def test_non_eos_at_capacity_is_unknown_not_reconstructed_length():
    result = generation_segments([1], [7], [1], eos_ids={9}, vocab_size=20, generation_count=1, capacity_tokens=2)
    assert not result["all_segments_end_eos"]
    assert result["segments"][0]["at_capacity"]
    assert result["segments"][0]["status"] == "no-eos-boundary-uncertain"
    assert result["segments"][0]["original_finish_reason"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["eos", "running", "no-eos", "unconsumed", "config-hash", "wrong-eos", "tampered-npz"])
async def test_real_workstate_consumption_gate_and_model_binding(wired, tmp_path, monkeypatch, case):
    original = helper.execute_synthetic_stage

    def execute(*args, **kwargs):
        result = original(*args, **kwargs)
        for t in result.trajectories:
            t.response_ids = [9 if case != "no-eos" else 8]
        return result

    monkeypatch.setattr(helper, "execute_synthetic_stage", execute)
    run, memory, record = await prepare(wired, tmp_path, monkeypatch)
    config = tmp_path / "model-config.json"
    config.write_text(json.dumps({"eos_token_id": 9, "vocab_size": 20}))
    config_sha = sha(config.read_bytes())
    if case == "running":
        (run / "run-manifest.json").write_text(json.dumps({"status": "running"}))
    if case == "unconsumed":
        next((run / "validation").glob("*.jsonl")).unlink()
    if case == "tampered-npz":
        Path(record["items"][0]["stage_npz_path"]).write_bytes(b"changed")
    kwargs = dict(
        memory_root=memory,
        expected_run_id="memory-run",
        model_config=config,
        model_config_sha256=config_sha if case != "config-hash" else "sha256:" + "0" * 64,
        eos_token_ids=[8 if case == "wrong-eos" else 9],
        capacity_tokens=16384,
    )
    before = [(i["stage_receipt_path"], Path(i["stage_receipt_path"]).read_bytes()) for i in record["items"]]
    if case in ("config-hash", "wrong-eos"):
        with pytest.raises(ValueError):
            audit_generation_boundaries(run, **kwargs)
    else:
        report = audit_generation_boundaries(run, **kwargs)
        assert report["passed"] == (case == "eos"), report
        assert report["summary"]["verified_eos_segments"] == (2 if case in ("eos", "running") else 0)
        if case in ("unconsumed", "tampered-npz"):
            assert report["trajectories"] == []
    assert all(Path(p).read_bytes() == raw for p, raw in before)


@pytest.mark.parametrize("bad", [False, True])
def test_generation_config_is_effective_eos_source(tmp_path, bad):
    from examples.dsh.capabilities.audit_memory_generation_boundaries import _model_source

    model = tmp_path / "config.json"
    generation = tmp_path / "generation_config.json"
    model.write_text(json.dumps({"vocab_size": 20, "eos_token_id": 8}))
    generation.write_text(json.dumps({"eos_token_id": [9, 10]}))
    args = (model, sha(model.read_bytes()), generation, sha(generation.read_bytes()), [8] if bad else [9, 10])
    if bad:
        with pytest.raises(ValueError, match="effective model config"):
            _model_source(*args)
    else:
        source = _model_source(*args)
        assert source["eos_token_ids"] == [9, 10]
        assert source["generation_config_sha256"] == sha(generation.read_bytes())
