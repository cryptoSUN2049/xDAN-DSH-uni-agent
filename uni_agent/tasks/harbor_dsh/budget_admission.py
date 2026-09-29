"""Trusted Framework storage binding Gateway tokens to independently checked Harbor evidence."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from uni_agent.gateway.session.types import budget_json_sha256, trajectory_token_sha256, validate_gateway_budget_proof

MODE = "budget-terminal-v1"
VERSION_FIELDS = (
    "min_global_steps",
    "max_global_steps",
    "generation_count",
    "versioned_generation_count",
    "version_evidence_complete",
)
DUMP_FIELDS = ("gateway_budget_proof", "budget_admission", "session_exhaustion_reason", *VERSION_FIELDS)


def record_budget_admission(trajectory, *, directory, context, run_id, policy, receipt, receipt_id, online):
    """Online caller must first validate the complete Gateway result before selection.

    Offline callers cannot create or update this private authority record. Hashes
    provide consistency only; agent/runner output never selects the evidence root.
    """
    from .task import _canonical, _write
    from .trajectory_audit import _read_object

    if policy.get("termination_policy") != MODE or receipt.get("termination_policy") != MODE:
        raise ValueError("Budget admission requires matching operator and receipt policy")
    proof = trajectory.extra_fields.get("gateway_budget_proof")
    validate_gateway_budget_proof(
        proof,
        [trajectory],
        session_id=context["gateway_session_id"],
        expected_limits=policy["budget_limits"],
        require_all_chains=False,
    )
    finished, kind = receipt["finished"], receipt["termination_kind"]
    if type(finished) is not bool or trajectory.finished is not finished:
        raise ValueError("Budget admission completion mismatch")
    if finished:
        if kind != "completed" or proof["exhaustion_events"]:
            raise ValueError("Natural completion cannot conceal budget exhaustion")
    elif kind != "budget_exhausted" or proof["exhaustion_reason"] not in {
        "max_generated_tokens",
        "max_trajectory_length",
    }:
        raise ValueError("Unfinished candidate lacks final Gateway budget exhaustion")
    info = trajectory.extra_fields.get("dsh_reward_info", {})
    if info.get("finished") is not finished or info.get("harbor_dsh", {}).get("receipt_sha256") != receipt_id:
        raise ValueError("Budget admission reward receipt mismatch")
    body = dict(
        schema="dsh.harbor-budget-admission.v1",
        run_id=run_id,
        framework_context=dict(context),
        termination_policy=MODE,
        termination_kind=kind,
        finished=finished,
        policy_sha256=budget_json_sha256(policy),
        receipt_sha256=receipt_id,
        gateway_budget_proof=deepcopy(proof),
        chain_id=trajectory.chain_id,
        token_sha256=trajectory_token_sha256(trajectory),
        version_evidence={
            key: deepcopy(trajectory.extra_fields[key]) for key in VERSION_FIELDS if key in trajectory.extra_fields
        },
    )
    body["admission_sha256"] = budget_json_sha256(body)
    name = f"admission-chain-{trajectory.chain_id}.json"
    if online:
        try:
            _write(directory, name, _canonical(body))
        except FileExistsError:
            saved, _ = _read_object(directory, name)
            if _canonical(saved) != _canonical(body):
                raise ValueError("Existing private budget admission differs") from None
    else:
        saved, _ = _read_object(directory, name)
        if _canonical(saved) != _canonical(body):
            raise ValueError("Private budget admission differs from dumped evidence")
    projection = {key: body[key] for key in ("schema", "admission_sha256", "termination_policy", "termination_kind")}
    if not online and trajectory.extra_fields.get("budget_admission") != projection:
        raise ValueError("Budget admission projection mismatch")
    return replace(trajectory, extra_fields={**trajectory.extra_fields, "budget_admission": projection})


def bind_budget_dump(trajectories, *, context, npz_sha256, metadata, artifact_root, online):
    """Bind exact dump bytes/index to private admission; no path from runner metadata."""
    from pydantic import TypeAdapter

    from .protocol import OpaqueId
    from .task import _canonical, _write
    from .trajectory_audit import _private_directory, _read_object

    root = Path(artifact_root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("Budget dump requires trusted absolute artifact root")
    root_fd = _private_directory(root)
    try:
        for trajectory in trajectories:
            info = trajectory.extra_fields["dsh_reward_info"]["harbor_dsh"]
            job_id = TypeAdapter(OpaqueId).validate_python(info["job_id"])
            directory = _private_directory(job_id, dir_fd=root_fd)
            try:
                admission, _ = _read_object(directory, f"admission-chain-{trajectory.chain_id}.json")
                projection = trajectory.extra_fields["budget_admission"]
                if (
                    admission["admission_sha256"] != projection["admission_sha256"]
                    or admission["framework_context"] != context
                ):
                    raise ValueError("Dump differs from private admission")
                if admission["token_sha256"] != trajectory_token_sha256(trajectory):
                    raise ValueError("Dump tokens differ from private admission")
                body = dict(
                    schema="dsh.harbor-budget-dump.v1",
                    framework_context=context,
                    admission_sha256=admission["admission_sha256"],
                    trajectory_npz_sha256=npz_sha256,
                    metadata_sha256=budget_json_sha256(metadata),
                )
                name = f"dump-chain-{trajectory.chain_id}.json"
                if online:
                    try:
                        _write(directory, name, _canonical(body))
                    except FileExistsError:
                        saved, _ = _read_object(directory, name)
                        if _canonical(saved) != _canonical(body):
                            raise ValueError("Existing private dump binding differs") from None
                else:
                    saved, _ = _read_object(directory, name)
                    if _canonical(saved) != _canonical(body):
                        raise ValueError("Private dump binding mismatch")
            finally:
                os.close(directory)
    finally:
        os.close(root_fd)
