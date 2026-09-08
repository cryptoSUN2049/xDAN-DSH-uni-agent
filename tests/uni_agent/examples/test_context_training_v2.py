import json
from collections import Counter
from pathlib import Path

import pytest

from examples.dsh.capabilities.context_tasks_v2 import oracle, prepare
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result


def test_structural_curriculum_and_independent_oracle(tmp_path):
    rows = prepare(tmp_path / "cases")
    assert Counter(r["metadata"]["split"] for r in rows) == {"train": 12, "validation": 4}
    assert len({r["metadata"]["structure_id"] for r in rows}) == 16
    expected = {"train-V1": "4", "train-V2": "5", "train-V3": "6", "dev-V": "8"}
    for row in rows:
        metadata = row["metadata"]
        path = Path(metadata["fixture_path"])
        contract = json.loads(path.read_text())
        result = oracle(contract, path.parent)
        assert result == contract["expected"]
        assert result["citations"]
        assert metadata["task_version"] == metadata["verifier_version"] == "2"
        assert "citations.source" in row["messages"][0]["content"]
        if contract["case_id"] in expected:
            assert result["value"] == expected[contract["case_id"]]
        if contract["family"] == "missing":
            assert result["status"] == "insufficient_evidence" and result["value"] is None


def test_generation_refuses_overwrite_and_changed_sources(tmp_path):
    row = prepare(tmp_path / "cases")[0]
    with pytest.raises(FileExistsError):
        prepare(tmp_path / "cases")
    path = Path(row["metadata"]["fixture_path"])
    contract = json.loads(path.read_text())
    (path.parent / contract["sources"][0]["path"]).write_text("tampered\n")
    with pytest.raises(RuntimeError, match="source hash"):
        oracle(contract, path.parent)


def episode(tmp_path, index=0):
    row = prepare(tmp_path / "cases")[index]
    path = Path(row["metadata"]["fixture_path"])
    contract = json.loads(path.read_text())
    events = []
    for i, source in enumerate(contract["sources"]):
        file = path.parent / source["path"]
        events.extend(
            [
                _call(str(i), "str_replace_editor", {"command": "view", "path": str(file)}, seq=i),
                _result(str(i), file.read_text()),
            ]
        )
    events.append({"type": "turn/end", "data": {"reason": {"kind": "completed"}}})
    return row, contract, path.parent, events, json.loads(json.dumps(contract["expected"]))


@pytest.mark.parametrize("index", range(16))
def test_all_structures_score_full_only_on_complete_evidence(tmp_path, index):
    from examples.dsh.capabilities.context_verifier_v2 import score

    _, contract, root, events, answer = episode(tmp_path, index)
    result = score(contract, root, events, json.dumps(answer), True)
    assert result["reward"] == result["accuracy"] == 1
    assert result["eligible"] is True
    assert result["extra_info"]["context_switch_verified"] is False


@pytest.mark.parametrize(
    "mutation",
    ["wrong", "partial", "extra", "duplicate", "guess", "repeat", "unsafe", "unfinished", "badjson", "partialread"],
)
def test_reward_counterexamples(tmp_path, mutation):
    from examples.dsh.capabilities.context_verifier_v2 import score

    _, contract, root, events, answer = episode(tmp_path)
    if mutation == "wrong":
        answer["value"] = "wrong"
    if mutation == "partial":
        answer["citations"] = answer["citations"][:1]
    if mutation in {"duplicate", "extra"}:
        answer["citations"].append(dict(answer["citations"][0]))
        if mutation == "extra":
            answer["citations"][-1]["quote"] = "invented"
    if mutation == "guess":
        events = events[-1:]
    if mutation == "repeat":
        events[-1:-1] = [
            _call("extra", "str_replace_editor", json.loads(events[0]["data"]["arguments"]), seq=4),
            _result("extra", (root / contract["sources"][0]["path"]).read_text()),
        ]
    if mutation == "unsafe":
        events[0] = _call("0", "str_replace_editor", {"command": "view", "path": str(root / "contract.json")}, seq=0)
    if mutation == "partialread":
        events[1] = _result("0", "max_attempts=30\n")
    response = json.dumps(answer)
    if mutation == "badjson":
        response = response[:-1] + ',"status":"answer"}'
    result = score(contract, root, events, response, mutation != "unfinished")
    if mutation == "repeat":
        assert result["reward"] == 1
    elif mutation == "partial":
        assert 0.65 < result["reward"] < 1
    elif mutation in {"extra", "duplicate"}:
        assert result["reward"] == pytest.approx(0.65)
    elif mutation == "wrong":
        assert result["reward"] == pytest.approx(0.1)
    elif mutation == "partialread":
        assert 0 <= result["reward"] < 0.1
    else:
        assert result["reward"] == 0
    assert result["accuracy"] == int(mutation == "repeat")
    assert result["eligible"] == (mutation not in {"unsafe", "unfinished"})


def test_fresh_verifier_receipt_to_existing_task_and_split_veto(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from examples.dsh.capabilities.context_verifier_v2 import verify
    from examples.dsh.evolution_verifier import _sha256_bytes
    from uni_agent.tasks.dsh.task import _task_result

    row, _, _, events, answer = episode(tmp_path)
    metadata = {**row["metadata"], "environment_digest": _sha256_bytes(b"runtime")}
    trace = "".join(json.dumps(event) + "\n" for event in events).encode()
    (tmp_path / "trace.jsonl").write_bytes(trace)
    envelope = dict(
        schema="dsh.uni-agent.task-result.v1",
        metadata=metadata,
        response=json.dumps(answer),
        finished=True,
        dsh=dict(dsh_session_id="session", trace_sha256=_sha256_bytes(trace)),
    )
    raw = json.dumps(envelope).encode()
    (tmp_path / "result.json").write_bytes(raw)
    env = dict(
        DSH_TASK_RESULT_PATH=str(tmp_path / "result.json"),
        DSH_ARTIFACT_SHA256=_sha256_bytes(raw),
        DSH_TRACE_PATH=str(tmp_path / "trace.jsonl"),
        DSH_TRACE_SHA256=_sha256_bytes(trace),
        DSH_DSH_SESSION_ID="session",
        DSH_TASK_WORKDIR=str(tmp_path),
        DSH_TASK_SPLIT="train",
    )
    for key in (
        "task_id",
        "task_version",
        "environment_digest",
        "verifier_id",
        "verifier_version",
        "verifier_code_digest",
    ):
        env["DSH_" + key.upper()] = metadata[key]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    result = verify()
    task, receipt = _task_result(
        result,
        SimpleNamespace(finished=True, info={**envelope["dsh"], "gateway_session_id": "gateway"}),
        identity=metadata,
        artifact_sha256=_sha256_bytes(raw),
        verifier_command=["python", "-m", "examples.dsh.capabilities.context_verifier_v2"],
        verifier_stdout=json.dumps(result),
    )
    assert result["fresh"] and task.reward == task.verifier_reward == 1
    assert receipt["verifier"]["version"] == "2"
    monkeypatch.setenv("DSH_TASK_SPLIT", "validation")
    with pytest.raises(RuntimeError, match="split"):
        verify()


def test_preparation_parquet_identity_manifests_and_native_launcher(tmp_path, monkeypatch):
    import pyarrow.parquet as pq
    import yaml

    from examples.dsh.capabilities.prepare_context_training_v2 import prepare as prepare_training
    from tests.uni_agent.examples.test_prepare_capability_eval import inputs as base_inputs
    from uni_agent.tasks.dsh.task import DshArchitectureTaskConfig, _task_identity

    args = base_inputs.__wrapped__(tmp_path, monkeypatch)
    args["run_id"] = args.pop("eval_id")
    args["run_root"] = tmp_path / "independent-run"
    manifest = prepare_training(**args)
    output = args["output_dir"]
    assert not args["run_root"].exists()
    assert (output / "manifest.json").exists()
    assert manifest["counts"] == {"train": 12, "validation": 4}
    env = manifest["environment"]
    assert env["VAL_ONLY"] == "True" and env["ROLLOUT_N"] == "4"
    assert env["SAVE_LORA_ONLY"] == "False"
    assert env["CKPTS_DIR"].startswith("/workspace/uni-agent-g1/checkpoint/")
    config = yaml.safe_load((output / "task.yaml").read_text())[0]
    for split, count in manifest["counts"].items():
        rows = pq.read_table(output / f"{split}.parquet").to_pylist()
        assert len(rows) == count
        for row in rows:
            metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            identity = _task_identity(DshArchitectureTaskConfig.model_validate({**config, "metadata": metadata}))
            assert identity["split"] == split
            assert identity["verifier_code_digest"] == manifest["verifier_bundle"]["sha256"]
    assert config["agent"]["model"]["max_total_tokens"] == int(env["MAX_RESPONSE_LENGTH"])
    from examples.dsh.evolution_verifier import _sha256_bytes

    for name, digest in manifest["files"].items():
        assert _sha256_bytes((output / name).read_bytes()) == digest
    with pytest.raises(ValueError, match="new private"):
        prepare_training(**args)
    from examples.inference import parallel_infer_verl as cli

    parsed = cli._parse_args(manifest["inference_arguments"] + ["--max-model-len", "16384"])
    cli._validate_evidence_args(parsed)
    samples = pq.read_table(output / "validation.parquet").to_pylist()
    registered = cli._registered_samples(
        samples, [row["uid"] for row in samples], cli.TaskConfigResolver.from_file(parsed.task_config), strict=True
    )
    assert len(registered) == 4
    assert all(row["metadata"]["split"] == "validation" for row in registered)
    config = cli.init_config(parsed, task_configs=[config], served_model_name="fixed-Qwen3-4B")
    assert config.actor_rollout_ref.rollout.custom.agent_framework.require_verifier_reward is True
    # Exercise the real checked-in shell entry, after removing only the runtime probe mock.
    import os
    import subprocess

    monkeypatch.undo()
    printed = subprocess.run(
        [
            "bash",
            str(args["repository_root"] / "examples/dsh/train_qwen3_4b_online_rl.sh"),
            "trainer.default_local_dir=" + env["CKPTS_DIR"],
        ],
        env={**os.environ, **env, "PRINT_COMMAND": "1", "VAL_ONLY": "False"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(output / "train.parquet") in printed.stdout
    assert "save_lora_only=False" in printed.stdout
    assert env["CKPTS_DIR"] in printed.stdout
