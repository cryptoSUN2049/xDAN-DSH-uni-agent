import json
from pathlib import Path

import pytest

from examples.dsh import evolution_verifier_v2 as native
from examples.dsh.verifier import _sha256_bytes as sha
from tests.uni_agent.tasks.test_harbor_evolution_scoring import case as original_case
from uni_agent.tasks.harbor_dsh.evolution_scoring_v2 import (
    EvolutionV2Binding,
    load_evolution_v2_binding,
    require_evolution_v2_admission,
    score_evolution_v2,
)
from uni_agent.tasks.harbor_dsh.protocol import TaskRef

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def case(tmp_path):
    value = original_case.__wrapped__(tmp_path)
    metadata = value["envelope"]["metadata"]
    metadata.update(task_version="2", verifier_version="2", verifier_code_digest=native.bundle_digest())
    path = Path(value["binding"].metadata_path)
    path.write_text(json.dumps(metadata))
    ref = TaskRef(id=value["ref"].id, version="v2", sha256=sha(b"newtask"))
    binding = EvolutionV2Binding(
        task_ref=ref,
        fixture_path=value["binding"].fixture_path,
        fixture_sha256=value["binding"].fixture_sha256,
        metadata_path=str(path),
        metadata_sha256=sha(path.read_bytes()),
        source_sha256s={"examples/dsh/" + k: "sha256:" + v for k, v in native.source_hashes().items()},
        verifier_bundle_sha256=native.bundle_digest(),
    )
    value.update(ref=ref, binding=binding, frozen=load_evolution_v2_binding(binding, ref, repository_root=ROOT))
    return value


def artifacts(case):
    trace = b"".join((json.dumps(event) + "\n").encode() for event in case["events"])
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
    return dict(
        frozen=case["frozen"],
        task_ref=case["ref"],
        trace=trace,
        trace_sha256=sha(trace),
        run_raw=raw,
        run_sha256=sha(raw),
        gateway_session_id="gateway1",
    )


@pytest.mark.parametrize("variant", ["correct", "partial", "policy_failure", "unsafe", "incomplete_pairs"])
def test_original_v2_cli_semantics_preserved(case, tmp_path, monkeypatch, variant):
    if variant == "partial":
        del case["events"][8:10]
    if variant in ("policy_failure", "incomplete_pairs"):
        del case["events"][2:4]
    if variant == "incomplete_pairs":
        del case["events"][1]
    if variant == "unsafe":
        case["events"][0]["data"]["arguments"] = json.dumps({"command": "edit"})
    args = artifacts(case)
    (tmp_path / "session.jsonl").write_bytes(args["trace"])
    envelope = {**case["envelope"], "dsh": json.loads(args["run_raw"])}
    raw = json.dumps(envelope).encode()
    (tmp_path / "envelope.json").write_bytes(raw)
    env = dict(
        DSH_TASK_RESULT_PATH=str(tmp_path / "envelope.json"),
        DSH_ARTIFACT_SHA256=sha(raw),
        DSH_TRACE_PATH=str(tmp_path / "session.jsonl"),
        DSH_TRACE_SHA256=args["trace_sha256"],
        DSH_DSH_SESSION_ID="dsh-gateway1",
        DSH_TASK_WORKDIR=str(tmp_path),
    )
    for envkey, key in [
        ("TASK_ID", "task_id"),
        ("TASK_VERSION", "task_version"),
        ("ENVIRONMENT_DIGEST", "environment_digest"),
        ("VERIFIER_ID", "verifier_id"),
        ("VERIFIER_VERSION", "verifier_version"),
        ("VERIFIER_CODE_DIGEST", "verifier_code_digest"),
    ]:
        env["DSH_" + envkey] = case["envelope"]["metadata"][key]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if variant == "incomplete_pairs":
        with pytest.raises(RuntimeError):
            native.verify()
        with pytest.raises(ValueError):
            score_evolution_v2(**args)
        return
    expected = native.verify()
    result = score_evolution_v2(**args)
    for key in ("reward", "accuracy", "eligible", "finished", "evidence"):
        assert result[key] == expected[key]
    assert result["details"] == expected["extra_info"]
    assert "fresh" not in result and "issued_at" not in result
    if variant == "policy_failure":
        assert result["reward"] == 0 and result["eligible"] is True
        assert result["details"]["admission_kind"] == "completed-policy-failure"
        require_evolution_v2_admission(result, 0.0)
    if variant == "unsafe":
        with pytest.raises(ValueError):
            require_evolution_v2_admission(result, 0.0)


@pytest.mark.parametrize(
    "field", ["fixture_sha256", "metadata_sha256", "verifier_bundle_sha256", "source_sha256s", "task_ref"]
)
def test_binding_identity_rejected(case, field):
    values = case["binding"].model_dump()
    if field == "source_sha256s":
        values[field]["examples/dsh/evolution_verifier_v2.py"] = sha(b"wrong")
    elif field == "task_ref":
        values[field]["version"] = "v1"
    else:
        values[field] = sha(b"wrong")
    with pytest.raises(ValueError):
        load_evolution_v2_binding(EvolutionV2Binding.model_validate(values), case["ref"], repository_root=ROOT)


@pytest.mark.parametrize("field", ["trace_sha256", "run_sha256", "gateway_session_id"])
def test_artifact_identity_rejected(case, field):
    values = artifacts(case)
    values[field] = "wrong"
    with pytest.raises(ValueError):
        score_evolution_v2(**values)


@pytest.mark.parametrize("failure", ["timeout", "nonzero", "malformed", "nan", "bool", "large"])
def test_subprocess_boundaries_and_private_cleanup(case, monkeypatch, failure):
    import subprocess
    from types import SimpleNamespace

    from uni_agent.tasks.harbor_dsh import evolution_scoring_v2 as module

    roots = []

    def run(command, **kwargs):
        folder = kwargs["cwd"]
        roots.append(folder)
        assert folder.stat().st_mode & 0o777 == 0o700
        assert kwargs["timeout"] == 10
        assert "-I" in command and command[0]
        assert set(kwargs["env"]) == {
            "DSH_TASK_RESULT_PATH",
            "DSH_ARTIFACT_SHA256",
            "DSH_TRACE_PATH",
            "DSH_TRACE_SHA256",
            "DSH_DSH_SESSION_ID",
            "DSH_TASK_WORKDIR",
            "DSH_TASK_ID",
            "DSH_TASK_VERSION",
            "DSH_ENVIRONMENT_DIGEST",
            "DSH_VERIFIER_ID",
            "DSH_VERIFIER_VERSION",
            "DSH_VERIFIER_CODE_DIGEST",
        }
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        value = {"finished": True, "eligible": True, "reward": 0.0, "accuracy": 0.0, "evidence": [], "extra_info": {}}
        if failure == "nan":
            value["reward"] = float("nan")
        if failure == "bool":
            value["reward"] = True
        output = (
            b"bad json"
            if failure == "malformed"
            else b"x" * 262145
            if failure == "large"
            else json.dumps(value).encode()
        )
        kwargs["stdout"].write(output)
        return SimpleNamespace(returncode=2 if failure == "nonzero" else 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(ValueError):
        score_evolution_v2(**artifacts(case))
    assert roots and all(not root.exists() for root in roots)


def test_frozen_files_are_not_reread(case):
    before = score_evolution_v2(**artifacts(case))
    Path(case["binding"].fixture_path).write_bytes(b"changed")
    Path(case["binding"].metadata_path).write_bytes(b"changed")
    assert score_evolution_v2(**artifacts(case)) == before
