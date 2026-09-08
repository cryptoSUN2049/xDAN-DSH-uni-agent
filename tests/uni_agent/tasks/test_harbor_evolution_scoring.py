import json
from pathlib import Path

import pytest

from examples.dsh.evolution_verifier import _score_episode
from examples.dsh.verifier import _sha256_bytes as sha
from tests.uni_agent.tasks.test_dsh_evolution_verifier import _episode
from uni_agent.tasks.harbor_dsh.evolution_scoring import (
    EvolutionBinding,
    load_evolution_binding,
    require_evolution_admission,
    score_evolution,
)
from uni_agent.tasks.harbor_dsh.protocol import TaskRef

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def case(tmp_path):
    envelope, _, _ = _episode(tmp_path, candidate_output="a b")
    fixture = {"schema": "dsh.evolution.fixture.v1", "operation": "redact_email", "input": "a@b.com"}
    raw = json.dumps(fixture).encode()
    (tmp_path / "fixture.json").write_bytes(raw)
    metadata = envelope["metadata"]
    metadata.update(
        operation="redact_email",
        fixture_digest=sha(raw),
        verifier_code_digest=sha((ROOT / "examples/dsh/evolution_verifier.py").read_bytes()),
    )
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    events = [json.loads(line) for line in (tmp_path / "session.jsonl").read_text().splitlines()]
    for event in events:
        data = event["data"]
        if event["type"] == "tool/call" and data["name"] == "normalize_payload":
            data["arguments"] = json.dumps({"text": "a@b.com"})
        if event["type"] == "tool/result" and data["message"]["source"]["callId"] == "c5":
            data["message"]["content"][0]["content"][0]["text"] = "<EMAIL>"
    envelope["response"] = json.dumps(
        {"status": "promote", "plugin_id": "evo-1", "package_id": "pkg-1", "evidence": ["done"]}
    )
    ref = TaskRef(id="evolution-redact-01", version="v1", sha256=sha(b"task"))
    binding = EvolutionBinding(
        task_ref=ref,
        fixture_path=str(tmp_path / "fixture.json"),
        fixture_sha256=sha(raw),
        metadata_path=str(tmp_path / "metadata.json"),
        metadata_sha256=sha((tmp_path / "metadata.json").read_bytes()),
        source_sha256s={
            p: sha((ROOT / p).read_bytes()) for p in ["examples/dsh/evolution_verifier.py", "examples/dsh/verifier.py"]
        },
    )
    frozen = load_evolution_binding(binding, ref, repository_root=ROOT)
    return dict(frozen=frozen, ref=ref, events=events, envelope=envelope, fixture=fixture, binding=binding)


def invoke(case):
    trace = b"".join((json.dumps(e) + "\n").encode() for e in case["events"])
    run = dict(
        schema="dsh.uni-agent.dsh-run.v1",
        dsh_session_id="dsh-gateway1",
        finish_reason="completed",
        trace_persisted=True,
        trace_sha256=sha(trace),
        event_count=len(case["events"]),
        profile="sdk-minimal",
        patches_sha256=case["envelope"]["metadata"]["patches_sha256"],
        final_response=case["envelope"]["response"],
    )
    raw = json.dumps(run).encode()
    return score_evolution(
        frozen=case["frozen"],
        task_ref=case["ref"],
        trace=trace,
        trace_sha256=sha(trace),
        run_raw=raw,
        run_sha256=sha(raw),
        gateway_session_id="gateway1",
    )


@pytest.mark.parametrize("variant", ["correct", "wrong", "no_candidate", "no_cleanup", "veto", "report"])
def test_native_scores_exactly_preserved(case, variant):
    if variant == "wrong":
        case["events"][9]["data"]["message"]["content"][0]["content"][0]["text"] = "wrong"
    if variant == "no_candidate":
        del case["events"][8:10]
    if variant == "no_cleanup":
        del case["events"][10:14]
    if variant == "veto":
        del case["events"][2:4]
    if variant == "report":
        case["envelope"]["response"] = "bad report"
    expected = _score_episode(case["envelope"], case["events"], case["fixture"])
    result = invoke(case)
    assert (result["reward"], result["accuracy"], result["details"], result["evidence"]) == expected
    if variant == "veto":
        with pytest.raises(ValueError):
            require_evolution_admission(result, 0.0)
    else:
        require_evolution_admission(result, expected[0])
    if variant == "no_candidate":
        assert result["reward"] == 0.25


@pytest.mark.parametrize("field", ["fixture_sha256", "metadata_sha256", "source_sha256s", "task_ref"])
def test_binding_identity_rejected(case, field):
    data = case["binding"].model_dump()
    if field == "source_sha256s":
        data[field]["examples/dsh/evolution_verifier.py"] = sha(b"wrong")
    elif field == "task_ref":
        data[field]["id"] = "other-task"
    else:
        data[field] = sha(b"wrong")
    with pytest.raises(ValueError):
        load_evolution_binding(EvolutionBinding.model_validate(data), case["ref"], repository_root=ROOT)


def test_kind_is_fixed(case):
    with pytest.raises(ValueError):
        EvolutionBinding.model_validate({**case["binding"].model_dump(), "kind": "t2-log-tool-strict-v1"})


def test_loaded_input_does_not_reread_mutable_files(case):
    expected = invoke(case)
    Path(case["binding"].fixture_path).write_bytes(b"changed")
    Path(case["binding"].metadata_path).write_bytes(b"changed")
    assert invoke(case) == expected


def test_duplicate_call_rejected(case):
    case["events"].insert(1, case["events"][0])
    with pytest.raises(ValueError, match="duplicate"):
        invoke(case)


def test_fractional_score_not_coerced_to_boolean(case):
    del case["events"][8:10]
    result = invoke(case)
    assert result["reward"] == 0.25
    for wrong in (True, 1.0, 0.0, float("nan")):
        with pytest.raises(ValueError):
            require_evolution_admission(result, wrong)


@pytest.mark.parametrize("field", ["trace_sha256", "run_sha256", "gateway_session_id", "task_ref"])
def test_evidence_identity_rejected(case, monkeypatch, field):
    original = score_evolution

    def corrupt(**kwargs):
        kwargs[field] = TaskRef(id="wrong", version="v1", sha256=sha(b"wrong")) if field == "task_ref" else "wrong"
        return original(**kwargs)

    monkeypatch.setitem(invoke.__globals__, "score_evolution", corrupt)
    with pytest.raises(ValueError):
        invoke(case)
