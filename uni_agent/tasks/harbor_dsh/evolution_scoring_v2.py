"""Hermetic adapter to the unchanged, pinned native evolution admission-v2 CLI.

Only byte/identity validation lives here; business/admission rules remain in the
original CLI. Its fresh/issued_at fields are not Harbor trust evidence.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .evolution_scoring import EvolutionBinding, _json, _read, _sha
from .protocol import Sha256, TaskRef

EVOLUTION_V2_KIND = "evolution-v2-lifecycle-admission-v2"
VERIFIER_BUNDLE_SHA256 = "sha256:60f49dcb519576bbe09839371ec3220775aa42aaf5e780a7f5d843c71552ea82"
SOURCE_HASHES = {
    "evolution_verifier.py": "067668803e5f6fdb5f64cd44a17e2f4baef8835e4681a02cdf35d9f6bb4e3748",
    "verifier.py": "eb5e0d68779739d04e1038534e5f2799a44cf299e7325ba2f6bef5c793ecf2cd",
    "evolution_verifier_v2.py": "310460e0ef7a7f9876a5b7069f351f080d990d05fef526c71b3af03975ac0934",
}
BOOTSTRAP = "import sys; sys.path.insert(0,sys.argv[1]); from examples.dsh.evolution_verifier_v2 import main; main()"


class EvolutionV2Binding(EvolutionBinding):
    kind: Literal["evolution-v2-lifecycle-admission-v2"] = EVOLUTION_V2_KIND
    verifier_bundle_sha256: Sha256


@dataclass(frozen=True)
class FrozenEvolutionV2:
    task_ref: TaskRef
    fixture_raw: bytes
    fixture_sha256: str
    metadata_raw: bytes
    metadata_sha256: str
    source_sha256s: tuple[tuple[str, str], ...]
    source_raw: tuple[tuple[str, bytes], ...]
    verifier_bundle_sha256: str
    kind: str = EVOLUTION_V2_KIND


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def load_evolution_v2_binding(binding, task_ref, *, repository_root):
    if binding.kind != EVOLUTION_V2_KIND or binding.task_ref != task_ref or task_ref.version != "v2":
        raise ValueError("Evolution v2 TaskRef/kind/version mismatch")
    expected = {"examples/dsh/" + name: "sha256:" + digest for name, digest in SOURCE_HASHES.items()}
    if binding.source_sha256s != expected or binding.verifier_bundle_sha256 != VERIFIER_BUNDLE_SHA256:
        raise ValueError("Evolution v2 source bundle identity mismatch")
    root = Path(repository_root).resolve()
    if root != Path(__file__).resolve().parents[3]:
        raise ValueError("Evolution v2 must use its own frozen source checkout")
    sources = tuple((name, _read(root / name)) for name in sorted(expected))
    if any(_sha(raw) != expected[name] for name, raw in sources):
        raise ValueError("Evolution v2 source bytes mismatch")
    fixture_raw, metadata_raw = _read(Path(binding.fixture_path)), _read(Path(binding.metadata_path))
    if _sha(fixture_raw) != binding.fixture_sha256 or _sha(metadata_raw) != binding.metadata_sha256:
        raise ValueError("Evolution v2 fixture/metadata hash mismatch")
    fixture, metadata = _json(fixture_raw), _json(metadata_raw)
    if not isinstance(fixture, dict) or not isinstance(metadata, dict):
        raise ValueError("Evolution v2 frozen inputs must be objects")
    required = ("task_id", "scenario_id", "candidate_tool_name", "fixture_path", "environment_digest", "patches_sha256")
    if any(not isinstance(metadata.get(k), str) or not metadata[k] for k in required):
        raise ValueError("Evolution v2 missing metadata identity")
    if (
        fixture.get("schema") != "dsh.evolution.fixture.v1"
        or fixture.get("operation") != "redact_email"
        or not isinstance(fixture.get("input"), str)
        or metadata.get("operation") != "redact_email"
        or metadata.get("fixture_digest") != binding.fixture_sha256
        or metadata.get("profile") != "sdk-minimal"
        or metadata.get("task_version") != "2"
        or metadata.get("verifier_version") != "2"
        or metadata.get("verifier_id") != "dsh-harness-evolution-verifier"
        or metadata.get("verifier_code_digest") != VERIFIER_BUNDLE_SHA256
    ):
        raise ValueError("Evolution v2 metadata version/bundle/fixture mismatch")
    return FrozenEvolutionV2(
        task_ref,
        fixture_raw,
        binding.fixture_sha256,
        metadata_raw,
        binding.metadata_sha256,
        tuple(sorted(expected.items())),
        sources,
        VERIFIER_BUNDLE_SHA256,
    )


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(raw)


def _invoke_cli(folder, envelope, frozen, trace):
    source = folder / "src"
    for name, raw in frozen.source_raw:
        _write(source / name, raw)
    _write(source / "examples/__init__.py", b"")
    _write(source / "examples/dsh/__init__.py", b"")
    _write(folder / "fixture.json", frozen.fixture_raw)
    _write(folder / "session.jsonl", trace)
    envelope_raw = _canonical(envelope)
    _write(folder / "envelope.json", envelope_raw)
    env = {
        "DSH_TASK_RESULT_PATH": str(folder / "envelope.json"),
        "DSH_ARTIFACT_SHA256": _sha(envelope_raw),
        "DSH_TRACE_PATH": str(folder / "session.jsonl"),
        "DSH_TRACE_SHA256": _sha(trace),
        "DSH_DSH_SESSION_ID": envelope["dsh"]["dsh_session_id"],
        "DSH_TASK_WORKDIR": str(folder),
    }
    for name, key in [
        ("TASK_ID", "task_id"),
        ("TASK_VERSION", "task_version"),
        ("ENVIRONMENT_DIGEST", "environment_digest"),
        ("VERIFIER_ID", "verifier_id"),
        ("VERIFIER_VERSION", "verifier_version"),
        ("VERIFIER_CODE_DIGEST", "verifier_code_digest"),
    ]:
        env["DSH_" + name] = envelope["metadata"][key]
    with (folder / "stdout").open("xb") as stdout, (folder / "stderr").open("xb") as stderr:
        (folder / "stdout").chmod(0o600)
        (folder / "stderr").chmod(0o600)
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", BOOTSTRAP, str(source)],
                cwd=folder,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Evolution v2 verifier exceeded 10s deadline") from exc
    if result.returncode != 0:
        raise ValueError("Evolution v2 verifier subprocess rejected evidence")
    with (folder / "stdout").open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144 or (folder / "stderr").stat().st_size > 262144:
        raise ValueError("Evolution v2 verifier output exceeds byte budget")
    return _json(raw)


def score_evolution_v2(*, frozen, task_ref, trace, trace_sha256, run_raw, run_sha256, gateway_session_id):
    if (
        frozen.kind != EVOLUTION_V2_KIND
        or frozen.task_ref != task_ref
        or task_ref.version != "v2"
        or _sha(frozen.fixture_raw) != frozen.fixture_sha256
        or _sha(frozen.metadata_raw) != frozen.metadata_sha256
        or frozen.verifier_bundle_sha256 != VERIFIER_BUNDLE_SHA256
    ):
        raise ValueError("Frozen evolution v2 identity mismatch")
    expected = {"examples/dsh/" + name: "sha256:" + digest for name, digest in SOURCE_HASHES.items()}
    if (
        dict(frozen.source_sha256s) != expected
        or len(frozen.source_raw) != 3
        or {name: _sha(raw) for name, raw in frozen.source_raw} != expected
    ):
        raise ValueError("Frozen evolution v2 source snapshot mismatch")
    if (
        len(trace) > 16 * 1024 * 1024
        or len(run_raw) > 1048576
        or _sha(trace) != trace_sha256
        or _sha(run_raw) != run_sha256
    ):
        raise ValueError("Evolution v2 trace/run byte identity mismatch")
    run, metadata = _json(run_raw), _json(frozen.metadata_raw)
    events = [_json(line) for line in trace.splitlines() if line.strip()]
    if (
        not isinstance(run, dict)
        or not gateway_session_id
        or run.get("schema") != "dsh.uni-agent.dsh-run.v1"
        or run.get("dsh_session_id") != "dsh-" + gateway_session_id
        or run.get("trace_sha256") != trace_sha256
        or run.get("trace_persisted") is not True
        or run.get("finish_reason") != "completed"
        or not isinstance(run.get("final_response"), str)
        or run.get("profile") != metadata["profile"]
        or run.get("patches_sha256") != metadata["patches_sha256"]
        or type(run.get("event_count")) is not int
        or run["event_count"] != len(events)
        or not events
        or any(not isinstance(e, dict) for e in events)
        or events[-1].get("type") != "turn/end"
    ):
        raise ValueError("Evolution v2 run/session/finished identity mismatch")
    envelope = {
        "schema": "dsh.uni-agent.task-result.v1",
        "metadata": {**metadata, "fixture_path": "fixture.json"},
        "dsh": run,
        "response": run["final_response"],
        "finished": True,
    }
    with tempfile.TemporaryDirectory(prefix="harbor-evolution-v2-") as folder:
        value = _invoke_cli(Path(folder), envelope, frozen, trace)
    if (
        not isinstance(value, dict)
        or value.get("finished") is not True
        or type(value.get("eligible")) is not bool
        or any(type(value.get(k)) not in (int, float) or not math.isfinite(value[k]) for k in ("reward", "accuracy"))
        or not isinstance(value.get("extra_info"), dict)
        or not isinstance(value.get("evidence"), list)
    ):
        raise ValueError("Evolution v2 CLI returned malformed semantic result")
    return {
        "schema": "dsh.harbor-evolution-score.v2",
        "kind": EVOLUTION_V2_KIND,
        **{k: value[k] for k in ("reward", "accuracy", "eligible", "finished", "evidence")},
        "details": value["extra_info"],
        "task_ref": task_ref.model_dump(),
        "fixture_sha256": frozen.fixture_sha256,
        "metadata_sha256": frozen.metadata_sha256,
        "verifier_bundle_sha256": VERIFIER_BUNDLE_SHA256,
        "trace_sha256": trace_sha256,
        "run_sha256": run_sha256,
        "gateway_session_id": gateway_session_id,
        "hidden_inputs_verified": False,
        "adapter_input_kind": "derived-private-cli-envelope",
        "fixture_path_mapping": {"original": metadata["fixture_path"], "private": "fixture.json"},
    }


def require_evolution_v2_admission(evaluation, reward):
    if (
        evaluation.get("kind") != EVOLUTION_V2_KIND
        or evaluation.get("eligible") is not True
        or evaluation.get("finished") is not True
    ):
        raise ValueError("Evolution v2 evidence is not eligible for training")
    if type(reward) not in (int, float) or not math.isfinite(reward) or reward != evaluation["reward"]:
        raise ValueError("Evolution v2 recomputed fractional reward differs from Harbor reward")
