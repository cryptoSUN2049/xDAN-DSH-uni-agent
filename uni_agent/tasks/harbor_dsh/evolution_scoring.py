"""Frozen inputs for original evolution scoring, independent of Harbor execution.

Callers must bind artifact origin before invoking this byte-consistency checker.
This is not a T2 strict verifier or a substitute for Gateway trajectory admission.
"""

from __future__ import annotations

import json
import math
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import field_validator

from examples.dsh.evolution_verifier import _load_trace, _score_episode
from examples.dsh.verifier import _sha256_bytes as _sha

from .protocol import Contract, Sha256, TaskRef

EVOLUTION_KIND = "evolution-v2-lifecycle-v1"
SOURCES = ("examples/dsh/evolution_verifier.py", "examples/dsh/verifier.py")


def _json(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


class EvolutionBinding(Contract):
    kind: Literal["evolution-v2-lifecycle-v1"] = EVOLUTION_KIND
    task_ref: TaskRef
    fixture_path: str
    fixture_sha256: Sha256
    metadata_path: str
    metadata_sha256: Sha256
    source_sha256s: dict[str, Sha256]

    @field_validator("fixture_path", "metadata_path")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("Evolution binding path must be absolute and traversal-free")
        return value


@dataclass(frozen=True)
class FrozenEvolution:
    task_ref: TaskRef
    fixture_raw: bytes
    fixture_sha256: str
    metadata_raw: bytes
    metadata_sha256: str
    source_sha256s: tuple[tuple[str, str], ...]
    kind: str = EVOLUTION_KIND


def _read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1048576:
            raise ValueError("Evolution input must be a bounded regular file")
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("Evolution input exceeds byte bound")
    return raw


def load_evolution_binding(binding: EvolutionBinding, task_ref: TaskRef, *, repository_root: Path) -> FrozenEvolution:
    if binding.task_ref != task_ref or binding.kind != EVOLUTION_KIND:
        raise ValueError("Evolution TaskRef/kind mismatch")
    if set(binding.source_sha256s) != set(SOURCES):
        raise ValueError("Evolution scorer source manifest mismatch")
    for name in SOURCES:
        path = repository_root / name
        # Ensure the checked source is the imported scorer, not an unrelated checkout.
        imported_root = Path(__file__).resolve().parents[3]
        if path.resolve() != imported_root / name or _sha(_read(path)) != binding.source_sha256s[name]:
            raise ValueError("Evolution scorer source hash/location mismatch")
    fixture_raw = _read(Path(binding.fixture_path))
    metadata_raw = _read(Path(binding.metadata_path))
    if _sha(fixture_raw) != binding.fixture_sha256 or _sha(metadata_raw) != binding.metadata_sha256:
        raise ValueError("Evolution fixture/metadata hash mismatch")
    fixture, metadata = _json(fixture_raw), _json(metadata_raw)
    if not isinstance(fixture, dict) or not isinstance(metadata, dict):
        raise ValueError("Evolution frozen inputs must be objects")
    required = (
        "operation",
        "candidate_tool_name",
        "scenario_id",
        "task_id",
        "task_version",
        "fixture_digest",
        "fixture_path",
        "profile",
        "patches_sha256",
        "environment_digest",
        "verifier_id",
        "verifier_version",
        "verifier_code_digest",
    )
    if any(not isinstance(metadata.get(key), str) or not metadata[key] for key in required):
        raise ValueError("Evolution metadata lacks fixed scoring identity")
    if (
        fixture.get("schema") != "dsh.evolution.fixture.v1"
        or fixture.get("operation") != "redact_email"
        or not isinstance(fixture.get("input"), str)
        or metadata["operation"] != "redact_email"
        or metadata["fixture_digest"] != binding.fixture_sha256
        or metadata["profile"] != "sdk-minimal"
        or metadata["verifier_id"] != "dsh-harness-evolution-verifier"
        or metadata["verifier_version"] != "1"
        or metadata["verifier_code_digest"] != binding.source_sha256s[SOURCES[0]]
    ):
        raise ValueError("Unsupported or inconsistent evolution scoring metadata")
    return FrozenEvolution(
        task_ref,
        fixture_raw,
        binding.fixture_sha256,
        metadata_raw,
        binding.metadata_sha256,
        tuple(sorted(binding.source_sha256s.items())),
    )


def score_evolution(
    *,
    frozen: FrozenEvolution,
    task_ref: TaskRef,
    trace: bytes,
    trace_sha256: str,
    run_raw: bytes,
    run_sha256: str,
    gateway_session_id: str,
) -> dict:
    if (
        frozen.kind != EVOLUTION_KIND
        or frozen.task_ref != task_ref
        or _sha(frozen.fixture_raw) != frozen.fixture_sha256
        or _sha(frozen.metadata_raw) != frozen.metadata_sha256
    ):
        raise ValueError("Frozen evolution identity mismatch")
    if len(trace) > 16 * 1024 * 1024 or len(run_raw) > 1048576:
        raise ValueError("Evolution evidence exceeds byte bound")
    if _sha(trace) != trace_sha256 or _sha(run_raw) != run_sha256:
        raise ValueError("Evolution trace/run hash mismatch")
    run = _json(run_raw)
    metadata, fixture = _json(frozen.metadata_raw), _json(frozen.fixture_raw)
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
    ):
        raise ValueError("Evolution run/session/finished/deployment identity mismatch")
    with tempfile.TemporaryDirectory(prefix="harbor-evolution-score-") as folder:
        path = Path(folder) / "session.jsonl"
        path.write_bytes(trace)
        path.chmod(0o600)
        events = _load_trace(path, trace_sha256)
    if type(run.get("event_count")) is not int or run["event_count"] != len(events):
        raise ValueError("Evolution event count mismatch")
    calls, results = set(), set()
    for line, event in zip((line for line in trace.splitlines() if line.strip()), events, strict=True):
        _json(line)  # Reject ambiguous duplicate object keys before interpreting legacy events.
        data = event.get("data")
        if event["type"] not in ("tool/call", "tool/result"):
            continue
        if not isinstance(data, dict):
            raise ValueError("Malformed evolution tool event")
        if event["type"] == "tool/call":
            identity = data.get("callId")
            if not isinstance(identity, str) or not identity or identity in calls:
                raise ValueError("Missing/duplicate evolution call ID")
            calls.add(identity)
        else:
            message = data.get("message", {})
            identity = message.get("source", {}).get("callId") if isinstance(message, dict) else None
            if not isinstance(identity, str) or identity not in calls or identity in results:
                raise ValueError("Unmatched/duplicate evolution result ID")
            results.add(identity)
    envelope = {"metadata": metadata, "response": run["final_response"], "dsh": run, "finished": True}
    reward, accuracy, details, evidence = _score_episode(envelope, events, fixture)
    return {
        "schema": "dsh.harbor-evolution-score.v1",
        "kind": EVOLUTION_KIND,
        "reward": reward,
        "accuracy": accuracy,
        "eligible": details["eligible"],
        "details": details,
        "evidence": evidence,
        "fixture_sha256": frozen.fixture_sha256,
        "metadata_sha256": frozen.metadata_sha256,
        "task_ref": task_ref.model_dump(),
        "trace_sha256": trace_sha256,
        "run_sha256": run_sha256,
        "gateway_session_id": gateway_session_id,
        "hidden_inputs_verified": False,
    }


def require_evolution_admission(evaluation: dict, reward: float) -> None:
    if evaluation.get("kind") != EVOLUTION_KIND or evaluation.get("eligible") is not True:
        raise ValueError("Evolution hard-veto evidence is not eligible for training")
    if type(reward) not in (int, float) or not math.isfinite(reward) or evaluation["reward"] != reward:
        raise ValueError("Evolution recomputed fractional reward differs from Harbor reward")
