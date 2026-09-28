"""Explicit operator-owned MiMo Code contracts, separate from historical lanes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator

from .protocol import Contract, OpaqueId, Sha256, TaskRef

MIMO_STRATEGY = "mimo-code"


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate MiMo JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite MiMo JSON value: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class MimoImages(Contract):
    original_image: str
    dsh_image: str
    verifier_image: str | None = None

    @field_validator("original_image", "dsh_image", "verifier_image")
    @classmethod
    def _immutable(cls, value):
        if value is None:
            return value
        if not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}", value):
            raise ValueError("MiMo image requires an immutable registry digest")
        return value

    @property
    def resolved_verifier(self):
        return self.verifier_image or self.original_image


class MimoBinding(Contract):
    schema_: Literal["dsh.mimo-code-binding.v1"] = Field(alias="schema")
    task_id: OpaqueId
    cwd: str
    runner_python: Literal["/opt/dsh/bin/python"]
    image_binding: MimoImages
    artifact_contract: Literal["mimo-code-workspace-v1"]
    base_ref_capture: Literal["before_agent"]
    history_policy: Literal["reject", "strip"] = "reject"
    max_workspace_bytes: Annotated[int, Field(gt=0, le=2147483648)] = 536870912
    max_workspace_files: Annotated[int, Field(gt=0, le=1000000)] = 100000

    @field_validator("cwd")
    @classmethod
    def _cwd(cls, value):
        path = PurePosixPath(value)
        if (
            not path.is_absolute()
            or path.as_posix() != value
            or ".." in path.parts
            or len(path.parts) < 2
            or path.parts[1] in {"proc", "sys", "dev", "opt", "etc", "audit-input", "logs", "tests"}
        ):
            raise ValueError("MiMo cwd requires a dedicated absolute repository path")
        return value


class MimoBindingRef(Contract):
    task_ref: TaskRef
    path: str
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def _path(cls, value):
        if not Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("MiMo binding path must be absolute")
        return value


def load_mimo_binding(path: Path, *, expected_sha256: str | None = None) -> MimoBinding:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
            raise ValueError("MiMo binding must be a bounded regular file")
        raw = source.read(65537)
    if len(raw) > 65536 or (expected_sha256 is not None and digest(raw) != expected_sha256):
        raise ValueError("MiMo binding hash or size mismatch")
    return MimoBinding.model_validate(decode(raw))


def validate_mimo_release(binding: MimoBinding, release, task_ref: TaskRef) -> None:
    if (
        task_ref.id not in {binding.task_id, "mimo-code-" + binding.task_id}
        or binding.image_binding.dsh_image.rsplit("@", 1)[-1] != release.image_digest
        or release.profile != "sdk-minimal"
        or release.patch_sha256s
    ):
        raise ValueError("MiMo task/DSH image/profile binding mismatch")


def validate_mimo_receipt(state: dict, receipt: dict, *, binding: MimoBinding, session: str, reward: float) -> None:
    if (
        state.get("schema") != "dsh.mimo-workspace-state.v1"
        or state.get("cwd") != binding.cwd
        or state.get("gateway_session_id") != session
        or state.get("binding_sha256") != digest(canonical(binding.model_dump(mode="json", by_alias=True)))
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(state.get("base_ref"))) is None
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(state.get("base_tree"))) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(state.get("snapshot_sha256"))) is None
    ):
        raise ValueError("MiMo workspace state identity mismatch")
    if (
        receipt.get("schema") != "dsh.mimo-verifier-receipt.v1"
        or receipt.get("status") != "graded"
        or receipt.get("base_ref") != state["base_ref"]
        or receipt.get("snapshot_sha256") != state["snapshot_sha256"]
        or receipt.get("gateway_session_id") != session
        or type(receipt.get("reward")) not in (int, float)
        or receipt.get("reward") != reward
        or reward not in (0.0, 1.0)
        or type(receipt.get("verifier_returncode")) is not int
        or (receipt["verifier_returncode"] == 0) != (reward == 1.0)
    ):
        raise ValueError("MiMo independent verifier receipt mismatch")
