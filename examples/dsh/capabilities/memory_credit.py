"""In-process credit contracts for already audited stages; no execution or TQ writes.

Inputs belong to the trusted controller, never a model/tool result deserializer.
This validates relationships, not the authenticity of a claimed receipt/hash.
Caller must verify original receipts/files and revalidate immediately before use.
"""

import math
import re
from dataclasses import dataclass

from uni_agent.framework.trajectory_identity import trajectory_tq_key
from uni_agent.gateway.session import Trajectory


@dataclass
class StageOutcome:
    run_id: str
    partition: str
    group_uid: str
    sibling: int
    memory_chain_id: str
    role: str
    gateway_session_id: str
    dsh_session_id: str
    source_version: str
    checkpoint_identity: str
    receipt_sha256: str
    finished: bool
    eligible: bool
    reward: float
    trajectories: tuple[Trajectory, ...]
    parent_receipt_sha256: str | None = None
    frozen_manifest_sha256: str | None = None
    frozen_content_sha256: str | None = None


@dataclass(frozen=True)
class FrozenBinding:
    memory_chain_id: str
    writer_session_id: str
    reader_session_id: str
    source_version: str
    parent_receipt_sha256: str
    manifest_sha256: str
    content_sha256: str


@dataclass(frozen=True)
class ChainOutcome:
    writer: StageOutcome
    reader: StageOutcome
    frozen: FrozenBinding


@dataclass(frozen=True)
class CreditAssignment:
    memory_chain_id: str
    sibling: int
    reward: float
    weight_version: int
    trajectories: tuple[Trajectory, ...]
    tq_keys: tuple[str, ...]
    writer_receipt_sha256: str
    reader_receipt_sha256: str
    frozen: FrozenBinding
    run_id: str
    partition: str
    checkpoint_identity: str
    credit_rule: str = "terminal-reader-grpo-v1"


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _digest(value):
    _require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value), "Invalid digest")


def _trajectory(trajectory, stage, version):
    _require(isinstance(trajectory, Trajectory), "Expected actual Trajectory")
    _require(trajectory.finished is True and trajectory.reward_score == stage.reward, "Stage result mismatch")
    ids, mask, logprobs = trajectory.response_ids, trajectory.response_mask, trajectory.response_logprobs
    _require(bool(trajectory.prompt_ids) and bool(ids), "Empty token sequence")
    _require(all(type(x) is int and x >= 0 for x in trajectory.prompt_ids + ids), "Invalid token IDs")
    _require(len(mask) == len(ids) and all(type(x) is int and x in (0, 1) for x in mask), "Invalid response mask")
    _require(any(mask), "No generated tokens")
    _require(logprobs is not None and len(logprobs) == len(ids), "Missing or misaligned logprobs")
    _require(
        all(isinstance(x, float | int) and not isinstance(x, bool) and math.isfinite(x) for x in logprobs),
        "Invalid logprobs",
    )
    _require(all(m or p == 0 for m, p in zip(mask, logprobs, strict=True)), "Context logprob must be zero")
    for field in ("min_global_steps", "max_global_steps"):
        actual = trajectory.extra_fields.get(field)
        _require(type(actual) is int and actual == version, "Missing or different actual weight version")


def validate_credit_group(chains, *, expected_version, expected_group_uid, expected_run_id, expected_partition):
    """Validate exactly four independent A/B chains and return annotations only.

    Original trajectories (including their stage rewards) remain untouched.
    The later Framework integration must explicitly bind these annotations to
    a new chain receipt before assigning training rewards or writing TQ.
    """
    _require(type(expected_version) is int and expected_version >= 0, "Invalid expected version")
    _require(len(chains) == 4, "Expected four real siblings")
    _require(sorted(c.writer.sibling for c in chains) == list(range(4)), "Invalid or duplicate sibling indices")
    first = chains[0].writer
    seen_sessions, seen_chains, seen_receipts, seen_manifests, seen_trajectories = set(), set(), set(), set(), set()
    assignments = []
    for chain in sorted(chains, key=lambda c: c.writer.sibling):
        a, b, frozen = chain.writer, chain.reader, chain.frozen
        _require(a.memory_chain_id not in seen_chains, "Repeated memory chain")
        seen_chains.add(a.memory_chain_id)
        for stage, role in ((a, "A"), (b, "B")):
            for name in (
                "run_id",
                "partition",
                "group_uid",
                "memory_chain_id",
                "gateway_session_id",
                "dsh_session_id",
                "checkpoint_identity",
            ):
                _require(isinstance(getattr(stage, name), str) and bool(getattr(stage, name)), "Empty identity")
            _require(
                stage.run_id == expected_run_id
                and stage.partition == expected_partition
                and stage.group_uid == expected_group_uid,
                "Wrong group scope",
            )
            _require(type(stage.sibling) is int and stage.sibling == a.sibling and stage.role == role, "Wrong stage")
            _require(
                stage.memory_chain_id == a.memory_chain_id
                and stage.source_version == first.source_version
                and stage.checkpoint_identity == first.checkpoint_identity,
                "Source or checkpoint mismatch",
            )
            _digest(stage.source_version)
            _digest(stage.receipt_sha256)
            _require(stage.gateway_session_id not in seen_sessions, "Session reused across stages/chains")
            seen_sessions.add(stage.gateway_session_id)
            _require(stage.dsh_session_id == "dsh-" + stage.gateway_session_id, "DSH/Gateway mismatch")
            _require(stage.receipt_sha256 not in seen_receipts, "Repeated receipt")
            seen_receipts.add(stage.receipt_sha256)
            _require(stage.finished is True and stage.eligible is True, "Stage not admitted")
            _require(type(stage.reward) in (float, int) and stage.reward in (0, 1), "Invalid binary reward")
            _require(bool(stage.trajectories), "Empty stage trajectories")
            for trajectory in stage.trajectories:
                _require(id(trajectory) not in seen_trajectories, "Trajectory object reused")
                seen_trajectories.add(id(trajectory))
                _trajectory(trajectory, stage, expected_version)
        _require(a.reward == 1 and a.parent_receipt_sha256 is None, "Writer must pass existing freeze gate")
        _require(
            a.frozen_manifest_sha256 is None and a.frozen_content_sha256 is None, "Writer cannot claim reader binding"
        )
        _digest(frozen.manifest_sha256)
        _digest(frozen.content_sha256)
        _require(frozen.manifest_sha256 not in seen_manifests, "Frozen manifest reused across siblings")
        seen_manifests.add(frozen.manifest_sha256)
        _require(
            frozen
            == FrozenBinding(
                a.memory_chain_id,
                a.dsh_session_id,
                b.dsh_session_id,
                a.source_version,
                a.receipt_sha256,
                b.frozen_manifest_sha256,
                b.frozen_content_sha256,
            ),
            "Frozen A/B binding mismatch",
        )
        _require(b.parent_receipt_sha256 == a.receipt_sha256, "Reader parent mismatch")
        _require(b.trajectories[-1].response_mask[-1] == 1, "Final B output must end in generated tokens")
        trajectories = a.trajectories + b.trajectories
        assignments.append(
            CreditAssignment(
                a.memory_chain_id,
                a.sibling,
                float(b.reward),
                expected_version,
                trajectories,
                tuple(trajectory_tq_key(expected_group_uid, a.sibling, i) for i in range(len(trajectories))),
                a.receipt_sha256,
                b.receipt_sha256,
                frozen,
                expected_run_id,
                expected_partition,
                a.checkpoint_identity,
            )
        )
    return tuple(assignments)
