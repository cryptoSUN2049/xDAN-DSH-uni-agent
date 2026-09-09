import copy
import json

import pytest

from examples.dsh.capabilities.work_state.scoring import score_task
from examples.dsh.capabilities.work_state.tasks import make_task, oracle_outputs


def test_short_course_dynamic_inputs_and_no_reader_truth():
    train = [make_task("WS07", 0, seed) for seed in range(101, 109)]
    dev = [make_task("WS07", 1, seed) for seed in (901, 902)]
    values = [t["truth"]["expected_config"]["capacity"] for t in train]
    assert len(set(values)) == 8 and all(40 <= v <= 399 for v in values)
    assert all(1000 <= t["truth"]["expected_config"]["capacity"] <= 1999 for t in dev)
    for task in train + dev:
        assert task["course_id"] == "work-state-short-fact-v1"
        assert task["memory_paths"] == ["index.md", "handoff.md"]
        assert task["reader_files"] == {}
        assert str(task["truth"]["expected_config"]["capacity"]) not in task["reader_goal"]
        assert score_task(task, oracle_outputs(task))["reward"] == 1
    assert "capacity" in json.loads(next(iter(train[0]["writer_files"].values())))
    assert "limits" in json.loads(next(iter(dev[0]["writer_files"].values())))


def read_case(tmp_path):
    from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result

    memory, output = tmp_path / "memory", tmp_path / "output"
    memory.mkdir()
    output.mkdir()
    (memory / "index.md").write_text("Read handoff.md.\n")
    (memory / "handoff.md").write_text("worker capacity: 123\n")
    fixture = {"unpacked_root": str(memory), "output_root": str(output), "max_bytes": 65536}
    events = []
    for step, (name, command) in enumerate(
        [("index.md", "view"), ("handoff.md", "view"), ("config.json", "create"), ("plan.json", "create")], 1
    ):
        path = (memory if command == "view" else output) / name
        args = {"command": command, "path": str(path)}
        call = _call(str(step), "str_replace_editor", args, seq=1)
        call["data"]["step"] = step
        events.append(
            {
                "type": "assistant/message",
                "data": {
                    "turn": 1,
                    "step": step,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool-call",
                                "id": str(step),
                                "name": "str_replace_editor",
                                "arguments": json.dumps(args),
                            }
                        ],
                    },
                },
            }
        )
        events.extend([call, _result(str(step), path.read_text() if command == "view" else "created")])
    return fixture, events


def test_short_reads_require_actual_generation_and_full_results(tmp_path):
    from examples.dsh.capabilities.work_state.short_read_evidence import verify_reads

    fixture, events = read_case(tmp_path)
    assert all(verify_reads(fixture, events).values())


@pytest.mark.parametrize(
    "mutation", ["no_assistant", "fake_result", "partial", "same_generation", "wrong_step", "missing_index", "no_write"]
)
def test_short_read_counterexamples_are_quality_failure(tmp_path, mutation):
    from examples.dsh.capabilities.work_state.short_read_evidence import verify_reads

    fixture, events = read_case(tmp_path)
    if mutation == "no_assistant":
        events = [e for e in events if e["type"] != "assistant/message"]
    elif mutation == "fake_result":
        events[5]["data"]["message"]["content"][0]["content"][0]["text"] = "guessed"
    elif mutation == "partial":
        args = json.loads(events[4]["data"]["arguments"])
        args["view_range"] = [2, 2]
        events[4]["data"]["arguments"] = json.dumps(args)
        events[3]["data"]["message"]["content"][0]["arguments"] = json.dumps(args)
    elif mutation == "same_generation":
        # Writes dispatched after tool results were already generated before the reads.
        block = copy.deepcopy(events[6]["data"]["message"]["content"][0])
        events[3]["data"]["message"]["content"].append(block)
        events[7]["data"]["step"] = 2
        del events[6]
    elif mutation == "wrong_step":
        events[7]["data"]["step"] = 99
    elif mutation == "missing_index":
        (tmp_path / "memory" / "index.md").unlink()
    elif mutation == "no_write":
        events = events[:6]
    assert not all(verify_reads(fixture, events).values())


def short_trace(fixture, events):
    """CPU-only DSH-shaped messages; actual Task/verifier subprocess still runs."""
    from pathlib import Path

    from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result

    pairs = []
    if fixture["role"] == "reader":
        for name in ["index.md", "handoff.md"]:
            path = Path(fixture["unpacked_root"]) / name
            if path.exists():
                pairs.append(
                    (
                        _call("read-" + name, "str_replace_editor", {"command": "view", "path": str(path)}, seq=1),
                        _result("read-" + name, path.read_text()),
                    )
                )
    pairs.extend(zip(events[::2], events[1::2], strict=True))
    result = []
    for step, (call, answer) in enumerate(pairs, 1):
        call["data"].update(turn=1, step=step)
        data = call["data"]
        result.append(
            {
                "type": "assistant/message",
                "data": {
                    "turn": 1,
                    "step": step,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool-call",
                                "id": data["callId"],
                                "name": data["name"],
                                "arguments": data["arguments"],
                            }
                        ],
                    },
                },
            }
        )
        result.extend([call, answer])
    return result


@pytest.mark.parametrize("empty", [False, True])
def test_short_course_actual_task_freeze_new_session_and_quality(tmp_path, empty):
    import sys
    from pathlib import Path

    from examples.dsh.capabilities.memory_training_stage import GroupContext
    from examples.dsh.capabilities.memory_verifier import canonical, loads, sha
    from examples.dsh.capabilities.work_state.stage import (
        WorkStateOperator,
        freeze_and_prepare_reader,
        prepare_writer_stage,
        validate_stage_execution,
    )
    from tests.uni_agent.examples.test_work_state_stage import execute_synthetic_stage

    task = make_task("WS07", 0, 101)
    manifest = tmp_path / "dataset.json"
    manifest.write_bytes(
        canonical(
            {
                "schema": "dsh.work-state-dataset.v1",
                "tasks": {task["task_id"]: dict(family="WS07", variant=0, seed=101, split="train")},
            }
        )
    )
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"runtime")
    runtime.chmod(0o700)
    op = WorkStateOperator(
        tmp_path,
        Path(sys.executable),
        runtime,
        sha(b"runtime"),
        "base",
        "work-state-v1",
        manifest,
        sha(manifest.read_bytes()),
    )
    context = GroupContext("run", "train", "group", 0, 1)
    fields = {"tools_kwargs": {"task": {"metadata": {"work_state_task_id": task["task_id"]}}}}
    writer = prepare_writer_stage(op, context, chain_id="chain", gateway_session_id="GA", sample_fields=fields)
    a = execute_synthetic_stage(writer, bad_memory=empty, transform_events=short_trace)
    assert a.task_result.reward == 0
    reader = freeze_and_prepare_reader(writer, a, reader_gateway_session_id="GB")
    fixture = loads(reader.fixture_path.read_bytes())
    assert "writer-data" not in str(reader.raw_prompt)
    assert str(task["truth"]["expected_config"]["capacity"]) not in str(reader.raw_prompt)
    assert all("writer-data" not in path for path in fixture["read_files"])
    assert writer.gateway_session_id != reader.gateway_session_id
    assert any(path.endswith("short_tasks.py") for path in reader.file_hashes)
    assert any(path.endswith("short_read_evidence.py") for path in reader.file_hashes)
    # Even correct outputs by a synthetic guess must fail quality if memory is absent.
    b = execute_synthetic_stage(reader, transform_events=short_trace)
    receipt, envelope, rescore, _ = validate_stage_execution(reader, b)
    assert rescore["eligible"]
    assert rescore["reward"] == int(not empty)
    assert b.task_result.reward == int(not empty)


@pytest.mark.parametrize("trailing", [True, False])
@pytest.mark.parametrize("bounds", [None, [1, -1], [1, 2]])
def test_real_numbered_file_view_with_header(tmp_path, trailing, bounds):
    from examples.dsh.capabilities.work_state.short_read_evidence import verify_reads

    fixture, events = read_case(tmp_path)
    path = tmp_path / "memory" / "handoff.md"
    raw = "worker\ncapacity: 123" + ("\n" if trailing else "")
    path.write_text(raw)
    args = json.loads(events[4]["data"]["arguments"])
    if bounds is not None:
        args["view_range"] = bounds
    events[4]["data"]["arguments"] = json.dumps(args)
    events[3]["data"]["message"]["content"][0]["arguments"] = json.dumps(args)
    lines = raw.split("\n")
    if bounds is not None and bounds[1] != -1:
        lines = lines[: bounds[1]]
    text = f"Here's the content of {path} with line numbers (which has a total of {len(raw.split(chr(10)))} lines)\n"
    text += "\n".join(f"{i:6d}  {line}" for i, line in enumerate(lines, 1))
    events[5]["data"]["message"]["content"][0]["content"][0]["text"] = text
    assert all(verify_reads(fixture, events).values())


def test_same_assistant_two_output_writes_after_reads_is_allowed(tmp_path):
    from examples.dsh.capabilities.work_state.short_read_evidence import verify_reads

    fixture, events = read_case(tmp_path)
    events[6]["data"]["message"]["content"].extend(events[9]["data"]["message"]["content"])
    events[10]["data"]["step"] = 3
    del events[9]
    assert all(verify_reads(fixture, events).values())


def test_handoff_prefetched_in_index_generation_is_not_navigation(tmp_path):
    from examples.dsh.capabilities.work_state.short_read_evidence import verify_reads

    fixture, events = read_case(tmp_path)
    events[0]["data"]["message"]["content"].extend(events[3]["data"]["message"]["content"])
    events[4]["data"]["step"] = 1
    del events[3]
    assert not all(verify_reads(fixture, events).values())


def test_original_four_families_are_byte_equivalent_to_pre_course_source():
    import hashlib

    # Captured from pre-course HEAD tasks.py over the complete task objects (including prompts and truth).
    items = [make_task(f, v, s) for f in ("WS01", "WS03", "WS05", "WS06") for v in (0, 1) for s in (101, 303)]
    digest = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    assert digest == "ee13fc76964f4f922cf9f4b7a2b7110b3e571c9afb09910738eb4878965f0e6e"


@pytest.mark.parametrize("reference", ["handoff.md.backup", r"C:\memory\handoff.md", r"..\handoff.md", "../handoff.md"])
def test_short_index_rejects_non_relative_basename(tmp_path, reference):
    from examples.dsh.capabilities.work_state.short_read_evidence import verify_reads

    fixture, events = read_case(tmp_path)
    text = f"Read {reference}.\n"
    (tmp_path / "memory" / "index.md").write_text(text)
    events[2]["data"]["message"]["content"][0]["content"][0]["text"] = text
    assert not all(verify_reads(fixture, events).values())


@pytest.mark.parametrize("reference", ["handoff.md.", "[handoff](handoff.md)", "./handoff.md", "`handoff.md`"])
def test_short_index_accepts_relative_link_and_sentence_punctuation(tmp_path, reference):
    from examples.dsh.capabilities.work_state.short_read_evidence import verify_reads

    fixture, events = read_case(tmp_path)
    text = f"Read {reference}\n"
    (tmp_path / "memory" / "index.md").write_text(text)
    events[2]["data"]["message"]["content"][0]["content"][0]["text"] = text
    assert all(verify_reads(fixture, events).values())
