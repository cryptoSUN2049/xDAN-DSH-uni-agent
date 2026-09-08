import copy

import pytest

from examples.dsh.capability_tasks.log_tool.prepare_sft_dataset import associate_decisions, normalize_message


def sample():
    call = {"id": "c1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}
    first = [{"role": "system", "content": "sys"}, {"role": "user", "content": "business"}]
    target = {"role": "assistant", "content": "", "tool_calls": [call]}
    observation = {"role": "tool", "tool_call_id": "c1", "content": "real-result"}
    requests = [
        {
            "messages": first,
            "tools": [{"type": "function", "function": {"name": "inspect", "parameters": {"type": "object"}}}],
        },
        {
            "messages": first + [target, observation],
            "tools": [{"type": "function", "function": {"name": "inspect", "parameters": {"type": "object"}}}],
        },
    ]
    events = [
        {"seq": 0, "type": "user/message", "data": {"role": "user", "content": [{"type": "text", "text": "business"}]}},
        {
            "seq": 1,
            "type": "assistant/message",
            "data": {
                "turn": 1,
                "step": 1,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool-call", "id": "c1", "name": "inspect", "arguments": "{}"}],
                },
                "stream": [{"chunk": {"type": "finish", "reason": {"kind": "tool-calls"}}}],
            },
        },
        {
            "seq": 2,
            "type": "tool/call",
            "data": {"turn": 1, "step": 1, "callId": "c1", "name": "inspect", "arguments": "{}"},
        },
        {
            "seq": 3,
            "type": "tool/result",
            "sourceEventSeqs": [2],
            "data": {
                "turn": 1,
                "step": 1,
                "message": {
                    "role": "user",
                    "source": {"kind": "tool", "callId": "c1"},
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": "c1",
                            "isError": False,
                            "content": [{"type": "text", "text": "real-result"}],
                        }
                    ],
                },
            },
        },
        {
            "seq": 4,
            "type": "assistant/message",
            "data": {
                "turn": 1,
                "step": 2,
                "message": {"role": "assistant", "content": [{"type": "text", "text": "event-only-final"}]},
                "stream": [{"chunk": {"type": "finish", "reason": {"kind": "stop"}}}],
            },
        },
        {"seq": 5, "type": "turn/end", "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]
    return [copy.deepcopy(request) for request in requests], events


def test_targets_from_events_with_history_crosscheck():
    requests, events = sample()
    before = copy.deepcopy(requests)
    rows = associate_decisions(requests, events, "business")
    assert rows[-1]["target"]["content"] == "event-only-final"
    assert rows[0]["target"]["tool_calls"][0]["function"]["arguments"] == {}
    assert requests == before


@pytest.mark.parametrize("mutation", ["history", "target", "result", "finish", "sequence", "retry", "prompt"])
def test_ambiguous_or_modified_evidence_rejected(mutation):
    requests, events = sample()
    if mutation == "history":
        requests[1]["messages"][0]["content"] = "edited"
    if mutation == "target":
        requests[1]["messages"][-2]["tool_calls"][0]["id"] = "wrong"
    if mutation == "result":
        requests[1]["messages"][-1]["content"] = "fake"
    if mutation == "finish":
        events[-2]["data"]["stream"][-1]["chunk"]["reason"]["kind"] = "max-tokens"
    if mutation == "sequence":
        events[2]["seq"] = 1
    if mutation == "retry":
        requests.append(requests[-1])
    if mutation == "prompt":
        events[0]["data"]["content"][0]["text"] = "other"
    with pytest.raises(ValueError):
        associate_decisions(requests, events, "business")


def test_unsupported_content_not_silently_dropped():
    with pytest.raises(ValueError):
        normalize_message({"role": "user", "content": [{"type": "image_url", "image_url": "x"}]})


def sources(tmp_path):
    import json

    from examples.dsh.capability_tasks.log_tool.prepare_sft_dataset import digest, verifier_bundle_digest

    cases = []
    for split in ("train", "dev"):
        folder = tmp_path / split
        folder.mkdir()
        requests, events = sample()
        # This synthetic fixture is only for evidence admission and IO wiring.
        for request in requests:
            request["tools"][0]["function"]["name"] = "cordis_define"
            for message in request["messages"]:
                for call in message.get("tool_calls", []):
                    call["function"].update(
                        name="cordis_define", arguments=json.dumps({"code": {"host": "return {};\n"}})
                    )
        events[1]["data"]["message"]["content"][0].update(
            name="cordis_define", arguments=json.dumps({"code": {"host": "return {};\n"}})
        )
        events[2]["data"].update(name="cordis_define", arguments=json.dumps({"code": {"host": "return {};\n"}}))
        values = {
            "fixture.json": {"case_id": split + "-case", "split": split},
            "requests.json": requests,
        }
        for name, value in values.items():
            (folder / name).write_text(json.dumps(value))
        (folder / "events.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")
        (folder / "prompt.txt").write_text("business")
        case = dict(
            directory=str(folder),
            fixture=str(folder / "fixture.json"),
            prompt_file=str(folder / "prompt.txt"),
            split=split,
            session_id=split + "-session",
        )
        for field, name in [
            ("trace_sha256", "events.jsonl"),
            ("requests_sha256", "requests.json"),
            ("fixture_sha256", "fixture.json"),
            ("initial_prompt_sha256", "prompt.txt"),
        ]:
            case[field] = digest((folder / name).read_bytes())
        report = {key: case[key] for key in ("session_id", "trace_sha256", "fixture_sha256", "initial_prompt_sha256")}
        report.update(
            sdk_version="0.1.3a2",
            runtime_mode="installed-sdk-runtime",
            host_code_sha256=digest(b"return {};\n"),
            initial_prompt="business",
            prompt_source="file",
            policy_origin="scripted",
            finish_reason="completed",
        )
        (folder / "report.json").write_text(json.dumps(report))
        case["report_sha256"] = digest((folder / "report.json").read_bytes())
        cases.append(case)
    return dict(
        schema="dsh.t2-sft-sources.v1",
        collector_commit="a" * 40,
        tokenizer_revision="1cfa9a7208912126459214e8b04321603b3df60c",
        verifier_bundle_sha256=verifier_bundle_digest(),
        runtime_identity=dict(
            source_revision="b2369692ea530007075ebcd18d39fdba0bbd3982",
            version="0.1.3a2",
            **{
                key: "sha256:" + "b" * 64
                for key in ("runtime_binary_sha256", "sdk_wheel_sha256", "runtime_wheel_sha256")
            },
        ),
        cases=cases,
    )


def test_prepare_publishes_separate_cases_without_overwrite(tmp_path, monkeypatch):
    """Synthetic evidence admission test; business verifier is independently tested."""
    import json

    import pyarrow.parquet as pq

    from examples.dsh.capability_tasks.log_tool import prepare_sft_dataset as module

    manifest = sources(tmp_path)
    path = tmp_path / "source.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(module.verifier, "verify_trace", lambda *args, **kwargs: {"passed": True})
    output = tmp_path / "prepared"
    module.prepare(path, module.digest(path.read_bytes()), output)
    train = pq.read_table(output / "train.parquet").to_pylist()
    dev = pq.read_table(output / "dev.parquet").to_pylist()
    assert {row["case_id"] for row in train}.isdisjoint(row["case_id"] for row in dev)
    assert len(train) == len(dev) == 2
    assert json.loads(train[-1]["target_json"])["content"] == "event-only-final"
    with pytest.raises(FileExistsError):
        module.prepare(path, module.digest(path.read_bytes()), output)


@pytest.mark.parametrize(
    "mutation", ["manifest_hash", "artifact_hash", "runtime", "bundle", "collector", "split", "diagnostic"]
)
def test_source_admission_rejects_missing_or_mismatched_identity(tmp_path, monkeypatch, mutation):
    import json

    from examples.dsh.capability_tasks.log_tool import prepare_sft_dataset as module

    manifest = sources(tmp_path)
    if mutation == "runtime":
        del manifest["runtime_identity"]["sdk_wheel_sha256"]
    if mutation == "bundle":
        manifest["verifier_bundle_sha256"] = "sha256:" + "0" * 64
    if mutation == "collector":
        del manifest["collector_commit"]
    if mutation == "split":
        manifest["cases"][1]["split"] = "train"
    if mutation == "artifact_hash":
        manifest["cases"][0]["requests_sha256"] = "sha256:" + "0" * 64
    if mutation == "diagnostic":
        case = manifest["cases"][0]
        from pathlib import Path

        report_path = Path(case["directory"]) / "report.json"
        report = json.loads(report_path.read_text())
        report["prompt_source"] = "default-diagnostic"
        report_path.write_text(json.dumps(report))
        case["report_sha256"] = module.digest(report_path.read_bytes())
    path = tmp_path / "source.json"
    path.write_text(json.dumps(manifest))
    expected = "sha256:" + "0" * 64 if mutation == "manifest_hash" else module.digest(path.read_bytes())
    monkeypatch.setattr(module.verifier, "verify_trace", lambda *args, **kwargs: {"passed": True})
    with pytest.raises(ValueError):
        module.prepare(path, expected, tmp_path / "not-published")
    assert not (tmp_path / "not-published").exists()


def test_target_requires_request_local_tool_schema():
    requests, events = sample()
    requests[0]["tools"] = []
    with pytest.raises(ValueError, match="absent"):
        associate_decisions(requests, events, "business")


@pytest.mark.parametrize("field", ["host_code_sha256", "sdk_version", "runtime_mode"])
def test_report_runtime_and_code_binding_rejects_mismatch(field):
    from examples.dsh.capability_tasks.log_tool.prepare_sft_dataset import digest, verify_report_identity

    report = {
        "host_code_sha256": digest(b"return {};\n"),
        "sdk_version": "0.1.3a2",
        "runtime_mode": "installed-sdk-runtime",
    }
    events = [
        {"type": "tool/call", "data": {"name": "cordis_define", "arguments": '{"code":{"host":"return {};\\n"}}'}}
    ]
    verify_report_identity(report, events, {"version": "0.1.3a2"})
    report[field] = "wrong"
    with pytest.raises(ValueError):
        verify_report_identity(report, events, {"version": "0.1.3a2"})
