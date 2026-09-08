from dataclasses import replace

import pytest

from examples.dsh.capabilities.memory_credit import (
    ChainOutcome,
    FrozenBinding,
    StageOutcome,
    validate_credit_group,
)
from uni_agent.gateway.session import Trajectory


def digest(n):
    return "sha256:" + f"{n:064x}"


def stage(j, role, reward):
    gateway = f"{role}-{j}"
    trajectory = Trajectory(
        prompt_ids=[1],
        response_ids=[2, 3, 4],
        response_mask=[1, 0, 1],
        response_logprobs=[-0.5, 0.0, -0.6],
        finished=True,
        reward_score=reward,
        extra_fields={
            "min_global_steps": 7,
            "max_global_steps": 7,
            "generation_count": 1,
            "versioned_generation_count": 1,
            "version_evidence_complete": True,
        },
    )
    return StageOutcome(
        run_id="run",
        partition="train",
        group_uid="group",
        sibling=j,
        memory_chain_id=f"chain-{j}",
        role=role,
        gateway_session_id=gateway,
        dsh_session_id=f"dsh-{gateway}",
        source_version=digest(1),
        checkpoint_identity="base-adapter",
        receipt_sha256=digest(20 + j * 2 + (role == "B")),
        finished=True,
        eligible=True,
        reward=reward,
        trajectories=(trajectory,),
    )


def group():
    result = []
    for j in range(4):
        a, b = stage(j, "A", 1.0), stage(j, "B", float(j % 2))
        frozen = FrozenBinding(
            f"chain-{j}",
            a.dsh_session_id,
            b.dsh_session_id,
            digest(1),
            a.receipt_sha256,
            digest(40 + j),
            digest(50 + j),
        )
        b = replace(
            b,
            parent_receipt_sha256=a.receipt_sha256,
            frozen_manifest_sha256=frozen.manifest_sha256,
            frozen_content_sha256=frozen.content_sha256,
        )
        result.append(ChainOutcome(a, b, frozen))
    return result


def validate(chains):
    return validate_credit_group(
        chains, expected_version=7, expected_group_uid="group", expected_run_id="run", expected_partition="train"
    )


def test_assignments_keep_original_tokens_and_rewards():
    chains = group()
    assignments = validate(chains)
    assert [x.reward for x in assignments] == [0, 1, 0, 1]
    for j, item in enumerate(assignments):
        assert item.trajectories[0] is chains[j].writer.trajectories[0]
        assert item.trajectories[1] is chains[j].reader.trajectories[0]
        assert item.tq_keys == (f"group_{j}_0", f"group_{j}_1")
        assert chains[j].writer.trajectories[0].reward_score == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_version", digest(2)),
        ("parent_receipt_sha256", digest(999)),
        ("frozen_manifest_sha256", digest(999)),
        ("frozen_content_sha256", digest(999)),
        ("finished", False),
        ("eligible", False),
        ("reward", float("nan")),
        ("group_uid", "other"),
        ("checkpoint_identity", "other"),
        ("memory_chain_id", "other"),
        ("dsh_session_id", "wrong"),
        ("partition", "val"),
        ("run_id", "other"),
    ],
)
def test_reader_binding_rejected(field, value):
    chains = group()
    chains[0] = replace(chains[0], reader=replace(chains[0].reader, **{field: value}))
    with pytest.raises(ValueError):
        validate(chains)


@pytest.mark.parametrize(
    "extra", [{}, {"min_global_steps": 7, "max_global_steps": 8}, {"min_global_steps": 6, "max_global_steps": 6}]
)
def test_actual_versions_required(extra):
    chains = group()
    chains[0].writer.trajectories[0].extra_fields = extra
    with pytest.raises(ValueError):
        validate(chains)


def test_incomplete_duplicate_group_and_cross_chain_reuse():
    chains = group()
    for bad in (chains[:3], chains[:3] + [chains[0]]):
        with pytest.raises(ValueError):
            validate(bad)
    chains[1].reader.trajectories = chains[0].reader.trajectories
    with pytest.raises(ValueError):
        validate(chains)


@pytest.mark.parametrize(
    "field,value",
    [
        ("response_mask", [1, 2, 1]),
        ("response_logprobs", [-1.0]),
        ("response_ids", []),
        ("finished", False),
        ("reward_score", 9.0),
    ],
)
def test_bad_trajectory_rejected(field, value):
    chains = group()
    setattr(chains[0].reader.trajectories[0], field, value)
    with pytest.raises(ValueError):
        validate(chains)


@pytest.mark.parametrize("which", ["writer-zero", "same-session", "shared-manifest", "last-context", "reader-reward"])
def test_admission_and_independence_boundaries(which):
    chains = group()
    if which == "writer-zero":
        chains[0].writer.reward = 0
        chains[0].writer.trajectories[0].reward_score = 0
    elif which == "same-session":
        chains[0].reader.gateway_session_id = chains[0].writer.gateway_session_id
        chains[0].reader.dsh_session_id = chains[0].writer.dsh_session_id
    elif which == "shared-manifest":
        chains[1] = replace(
            chains[1], frozen=replace(chains[1].frozen, manifest_sha256=chains[0].frozen.manifest_sha256)
        )
        chains[1].reader.frozen_manifest_sha256 = chains[0].frozen.manifest_sha256
    elif which == "last-context":
        chains[0].reader.trajectories[0].response_mask[-1] = 0
        chains[0].reader.trajectories[0].response_logprobs[-1] = 0
    else:
        chains[0].reader.reward = 1
    with pytest.raises(ValueError):
        validate(chains)


@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"generation_count": 2, "versioned_generation_count": 1, "version_evidence_complete": False},
        {"generation_count": 2, "versioned_generation_count": 1, "version_evidence_complete": True},
    ],
)
def test_incomplete_per_generation_evidence_rejected_even_when_span_matches(evidence):
    chains = group()
    chains[0].writer.trajectories[0].extra_fields = {"min_global_steps": 7, "max_global_steps": 7, **evidence}
    with pytest.raises(ValueError):
        validate(chains)
