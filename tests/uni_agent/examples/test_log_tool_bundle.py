"""T2 dataset identity, split and admission contracts."""

import copy
import json
from pathlib import Path

import pytest

from examples.dsh.capability_tasks.log_tool import task_bundle as bundle

ROOT = Path(__file__).resolve().parents[3]


def test_public_split_and_bound_code(monkeypatch):
    monkeypatch.setattr(bundle, "_bundle_identity", lambda *a, **k: {"sha256": "sha256:" + "b" * 64})
    rows, identity = bundle.build_rows(ROOT, environment_digest="sha256:" + "a" * 64, patches=[])
    metadata = [row["extra_info"]["tools_kwargs"]["task"]["metadata"] for row in rows]
    assert len(rows) == 6
    assert sum(m["split"] == "train" for m in metadata) == 4
    assert sum(m["split"] == "validation" for m in metadata) == 2
    assert all(m["evaluation_visibility"] == "public" for m in metadata)
    assert all(m["verifier_code_digest"] == identity["sha256"] for m in metadata)
    assert len({m["fixture_digest"] for m in metadata}) == 6
    assert all("oracle.py" not in row["prompt"][0]["content"] for row in rows)


@pytest.mark.parametrize("corruption", ["duplicate-inputs", "missing-field", "hidden-split", "bad-filter"])
def test_reject_corrupt_public_case(tmp_path, corruption):
    case, _ = bundle.load_case(ROOT / bundle.DIRECTORY / "fixtures/train-01.json")
    if corruption == "duplicate-inputs":
        case["calls"] = [copy.deepcopy(case["calls"][0])] * 2
    elif corruption == "missing-field":
        del case["calls"][0]["service"]
    elif corruption == "hidden-split":
        case["split"] = "holdout"
    else:
        case["calls"][0]["severity"] = 3
    path = tmp_path / "case.json"
    path.write_text(json.dumps(case))
    with pytest.raises(ValueError):
        bundle.load_case(path)


def test_bad_environment_pin():
    with pytest.raises(RuntimeError):
        bundle.build_rows(ROOT, environment_digest="latest", patches=[])


def test_cli_rejects_envelope_tampering_before_scoring(tmp_path, monkeypatch):
    import sys
    import types

    from examples.dsh.capability_tasks.log_tool import verifier_cli

    def forbidden(*args, **kwargs):
        raise AssertionError("Untrusted envelope must never reach scoring")

    monkeypatch.setitem(
        sys.modules,
        "examples.dsh.capability_tasks.log_tool.verifier",
        types.SimpleNamespace(verify_trace=forbidden),
    )
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"schema": "dsh.uni-agent.task-result.v1"}))
    monkeypatch.setenv("DSH_TASK_RESULT_PATH", str(path))
    monkeypatch.setenv("DSH_ARTIFACT_SHA256", "sha256:" + "a" * 64)
    with pytest.raises(RuntimeError, match="envelope hash mismatch"):
        verifier_cli.verify()


@pytest.mark.parametrize("tamper", [None, "profile", "code-pin", "split"])
def test_cli_identity_gates_and_real_zero_reward(tmp_path, monkeypatch, tamper):
    import sys
    import types

    from examples.dsh.capability_tasks.log_tool import verifier_cli
    from examples.dsh.verifier import _sha256_bytes

    def score(*args, **kwargs):
        return dict(passed=False, eligible=True, reasons=["business-output-mismatch"])

    monkeypatch.setitem(
        sys.modules, "examples.dsh.capability_tasks.log_tool.verifier", types.SimpleNamespace(verify_trace=score)
    )
    rows, _ = bundle.build_rows(
        ROOT, environment_digest="sha256:" + "e" * 64, patches=[str(ROOT / "examples/dsh/evolution.patch.yml")]
    )
    meta = rows[0]["extra_info"]["tools_kwargs"]["task"]["metadata"]
    if tamper == "code-pin":
        meta["verifier_code_digest"] = "sha256:" + "f" * 64
    if tamper == "split":
        meta["split"] = "train" if meta["split"] == "validation" else "validation"
    dsh = dict(
        dsh_session_id="test-session",
        trace_sha256="sha256:" + "c" * 64,
        profile="other" if tamper == "profile" else "sdk-minimal",
        patches_sha256=meta["patches_sha256"],
    )
    envelope = dict(schema="dsh.uni-agent.task-result.v1", metadata=meta, dsh=dsh, finished=True)
    path = tmp_path / "envelope.json"
    raw = json.dumps(envelope).encode()
    path.write_bytes(raw)
    env = dict(
        DSH_TASK_RESULT_PATH=str(path),
        DSH_ARTIFACT_SHA256=_sha256_bytes(raw),
        DSH_DSH_SESSION_ID=dsh["dsh_session_id"],
        DSH_TRACE_SHA256=dsh["trace_sha256"],
        DSH_TRACE_PATH=str(tmp_path / "trace.jsonl"),
        DSH_TASK_WORKDIR=str(ROOT),
        DSH_TASK_ID=meta["task_id"],
        DSH_TASK_VERSION=meta["task_version"],
        DSH_TASK_SPLIT=meta["split"],
        DSH_ENVIRONMENT_DIGEST=meta["environment_digest"],
        DSH_VERIFIER_ID=meta["verifier_id"],
        DSH_VERIFIER_VERSION=meta["verifier_version"],
        DSH_VERIFIER_CODE_DIGEST=meta["verifier_code_digest"],
    )
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if tamper:
        with pytest.raises(RuntimeError, match="mismatch|differs"):
            verifier_cli.verify()
    else:
        result = verifier_cli.verify()
        assert result["reward"] == 0.0 and result["eligible"] is True and result["finished"] is True
