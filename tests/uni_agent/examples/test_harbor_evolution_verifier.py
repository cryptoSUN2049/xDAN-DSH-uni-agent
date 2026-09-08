import hashlib
import json
from pathlib import Path

import pytest

from examples.harbor.evolution_verifier import run_verifier
from tests.uni_agent.tasks.test_harbor_evolution_scoring import case as evolution_case

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def case(tmp_path):
    return evolution_case.__wrapped__(tmp_path)


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def evidence(case, tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
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
        trace_path="/tmp/uni-agent-dsh/artifacts/" + hashlib.sha256(b"gateway1").hexdigest()[:24] + "/session.jsonl",
    )
    raw_run = json.dumps(run).encode()
    status = dict(
        schema="dsh.harbor-agent-execution.v1",
        status="completed",
        finished=True,
        finish_reason="completed",
        gateway_session_id="gateway1",
        dsh_session_id="dsh-gateway1",
        trace_sha256=sha(trace),
        run_sha256=sha(raw_run),
        event_count=len(case["events"]),
    )
    binding = case["binding"].model_dump(mode="json")
    binding.update(fixture_path="/tests/fixture.json", metadata_path="/tests/metadata.json")
    for name, raw in {
        "session.jsonl": trace,
        "run.json": raw_run,
        "status.json": json.dumps(status).encode(),
        "evolution-binding.json": json.dumps(binding).encode(),
    }.items():
        (folder / name).write_bytes(raw)
    return dict(
        input_dir=folder,
        output_dir=tmp_path / "output",
        repository_root=ROOT,
        fixture_path=Path(case["binding"].fixture_path),
        metadata_path=Path(case["binding"].metadata_path),
    )


@pytest.mark.parametrize("fractional", [False, True])
def test_preserves_native_reward_and_report(case, tmp_path, fractional):
    if fractional:
        del case["events"][8:10]
    args = evidence(case, tmp_path)
    report = run_verifier(**args)
    assert report["reward"] == (0.25 if fractional else 1.0)
    assert float((args["output_dir"] / "reward.txt").read_text()) == report["reward"]
    assert json.loads((args["output_dir"] / "evolution-report.json").read_text()) == report
    assert len(report["details"]["components"]) == 7
    with pytest.raises((ValueError, FileExistsError)):
        run_verifier(**args)


@pytest.mark.parametrize("bad", ["trace", "status", "binding_path", "metadata", "source", "symlink", "oversize"])
def test_invalid_evidence_never_publishes_reward(case, tmp_path, bad):
    args = evidence(case, tmp_path)
    source = args["input_dir"]
    if bad == "trace":
        (source / "session.jsonl").write_bytes(b"tampered")
    elif bad == "metadata":
        args["metadata_path"].write_bytes(b"changed")
    elif bad == "status":
        path = source / "status.json"
        data = json.loads(path.read_text())
        data["finished"] = False
        path.write_text(json.dumps(data))
    elif bad in ("binding_path", "source"):
        path = source / "evolution-binding.json"
        data = json.loads(path.read_text())
        if bad == "binding_path":
            data["fixture_path"] = "/tmp/student.json"
        else:
            data["source_sha256s"]["examples/dsh/evolution_verifier.py"] = sha(b"wrong")
        path.write_text(json.dumps(data))
    elif bad == "symlink":
        path = source / "run.json"
        path.rename(source / "real.json")
        path.symlink_to("real.json")
    else:
        (source / "evolution-binding.json").write_bytes(b" " * 65537)
    with pytest.raises((ValueError, OSError)):
        run_verifier(**args)
    assert not (args["output_dir"] / "reward.txt").exists()


def test_native_hard_veto_is_not_a_trainable_zero(case, tmp_path):
    del case["events"][2:4]
    args = evidence(case, tmp_path)
    with pytest.raises(ValueError):
        run_verifier(**args)
    assert not (args["output_dir"] / "reward.txt").exists()
