"""Controller-owned persistent profile selection, not runtime deployment or RL admission.

External receipt hashes fix bytes; they are NOT signatures or authorization.
Only a trusted controller may provide them after authenticating evaluation evidence.
Registry ownership assumes no hostile same-user processes. Use private local disk.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from .memory_artifacts import _digest, _directory, _identity, _read, _sha, _write

TOOLS = frozenset(
    {
        "str_replace_editor",
        "cordis_inspect_list",
        "cordis_inspect_query",
        "cordis_inspect_self",
        "cordis_define",
        "cordis_run",
        "cordis_stop",
        "cordis_undefine",
    }
)
PIN_HASHES = {"model_sha256", "runtime_sha256", "base_harness_sha256", "devset_sha256", "verifier_sha256"}
LIMIT = 1024 * 1024


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _parse(raw):
    def invalid(_):
        raise ValueError("Nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unexpected schema fields")


def _spec(value):
    _fields(value, {"schema", "profile", "allowed_tools"})
    tools = value["allowed_tools"]
    if value["schema"] != "dsh.rsi-profile.v1" or value["profile"] != "sdk-minimal":
        raise ValueError("Unsupported declarative profile")
    if not isinstance(tools, list) or not tools or any(not isinstance(t, str) or t not in TOOLS for t in tools):
        raise ValueError("Tool not allowlisted")
    if len(set(tools)) != len(tools):
        raise ValueError("Duplicate allowed tool")
    return {**value, "allowed_tools": sorted(tools)}


def _pins(value):
    _fields(value, PIN_HASHES | {"case_ids", "max_tokens", "evolution_run_id"})
    _identity(value["evolution_run_id"])
    for key in PIN_HASHES:
        _digest(value[key])
    cases = value["case_ids"]
    if not isinstance(cases, list) or len(cases) < 2 or len(cases) != len(set(cases)):
        raise ValueError("Require distinct development case identities")
    for case in cases:
        _identity(case)
    if type(value["max_tokens"]) is not int or value["max_tokens"] < 1:
        raise ValueError("Invalid development token budget")
    return {**value, "case_ids": sorted(cases)}


def _private(fd):
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Registry requires private owner directory permissions")


def _put(fd, value):
    raw = _canonical(value)
    digest = _sha(raw)
    name = digest[7:] + ".json"
    try:
        _write(fd, name, raw)
    except FileExistsError:
        if _read(fd, name, LIMIT, private=True) != raw:
            raise ValueError("Immutable object changed") from None
    return digest


def initialize(root, parent_spec, pins):
    root = Path(root).absolute()
    spec, pins = _spec(parent_spec), _pins(pins)
    parent = _directory(root.parent)
    try:
        os.mkdir(root.name, mode=0o700, dir_fd=parent)
    finally:
        os.close(parent)
    fd = _directory(root)
    try:
        _private(fd)
        _write(fd, "lock", b"")
        _write(fd, "pins.json", _canonical(pins))
        pins_sha = _sha(_canonical(pins))
        candidate = _put(
            fd,
            {
                "schema": "dsh.rsi-candidate.v1",
                "pins_sha256": pins_sha,
                "parent_sha256": None,
                "spec": spec,
                "content_sha256": _sha(_canonical(spec)),
            },
        )
        active = {
            "schema": "dsh.rsi-selection.v1",
            "sequence": 0,
            "action": "initialize",
            "candidate_sha256": candidate,
            "previous_sha256": None,
            "comparison_sha256": None,
        }
        active_sha = _put(fd, active)
        _write(fd, "active.json", _canonical(active))
        os.fsync(fd)
        return {"pins_sha256": pins_sha, "candidate_sha256": candidate, "active_sha256": active_sha}
    finally:
        os.close(fd)


class Registry:
    def __init__(self, root, expected_pins_sha256):
        self.root = Path(root).absolute()
        _digest(expected_pins_sha256)
        self.pins_sha256 = expected_pins_sha256

    @contextmanager
    def _locked(self):
        fd = _directory(self.root)
        lock = None
        try:
            _private(fd)
            # Validate inode/ownership before acquiring the existing lock; never recreate it.
            _read(fd, "lock", 0, private=True)
            lock = os.open("lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            info = os.fstat(lock)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                raise ValueError("Invalid registry lock")
            fcntl.flock(lock, fcntl.LOCK_EX)
            raw = _read(fd, "pins.json", LIMIT, private=True)
            if _sha(raw) != self.pins_sha256:
                raise ValueError("Registry pins hash mismatch")
            pins = _pins(_parse(raw))
            yield fd, pins
        finally:
            if lock is not None:
                os.close(lock)
            os.close(fd)

    def _object(self, fd, digest):
        _digest(digest)
        raw = _read(fd, digest[7:] + ".json", LIMIT, private=True)
        if _sha(raw) != digest:
            raise ValueError("Immutable object hash mismatch")
        return _parse(raw)

    def _candidate(self, fd, digest):
        value = self._object(fd, digest)
        _fields(value, {"schema", "pins_sha256", "parent_sha256", "spec", "content_sha256"})
        if value["schema"] != "dsh.rsi-candidate.v1" or value["pins_sha256"] != self.pins_sha256:
            raise ValueError("Candidate identity mismatch")
        if value["parent_sha256"] is not None:
            _digest(value["parent_sha256"])
        if _sha(_canonical(_spec(value["spec"]))) != value["content_sha256"]:
            raise ValueError("Candidate content hash mismatch")
        return value

    def _active(self, fd, expected):
        _digest(expected)
        raw = _read(fd, "active.json", LIMIT, private=True)
        if _sha(raw) != expected:
            raise ValueError("Active selection changed: compare-and-swap refused")
        value = _parse(raw)
        _fields(value, {"schema", "sequence", "action", "candidate_sha256", "previous_sha256", "comparison_sha256"})
        if value["schema"] != "dsh.rsi-selection.v1" or type(value["sequence"]) is not int or value["sequence"] < 0:
            raise ValueError("Invalid active selection")
        if self._object(fd, expected) != value:
            raise ValueError("Selection history mismatch")
        self._candidate(fd, value["candidate_sha256"])
        return value

    def register(self, spec, parent_sha256):
        spec = _spec(spec)
        with self._locked() as (fd, _):
            parent = self._candidate(fd, parent_sha256)
            if parent["content_sha256"] == _sha(_canonical(spec)):
                raise ValueError("Candidate must differ from parent")
            value = {
                "schema": "dsh.rsi-candidate.v1",
                "pins_sha256": self.pins_sha256,
                "parent_sha256": parent_sha256,
                "spec": spec,
                "content_sha256": _sha(_canonical(spec)),
            }
            digest = _put(fd, value)
            os.fsync(fd)
            return digest

    def load_active(self, expected_active_sha256):
        with self._locked() as (fd, _):
            active = self._active(fd, expected_active_sha256)
            candidate = self._candidate(fd, active["candidate_sha256"])
            return {
                "active_sha256": expected_active_sha256,
                "candidate_sha256": active["candidate_sha256"],
                "content_sha256": candidate["content_sha256"],
                "spec": candidate["spec"],
                "selection": active,
                "runtime_deployed": False,
            }

    def _switch(self, fd, active, previous_sha, candidate_sha, action, receipt_sha):
        value = {
            "schema": "dsh.rsi-selection.v1",
            "sequence": active["sequence"] + 1,
            "action": action,
            "candidate_sha256": candidate_sha,
            "previous_sha256": previous_sha,
            "comparison_sha256": receipt_sha,
        }
        digest = _put(fd, value)
        temp = "active-" + uuid.uuid4().hex + ".tmp"
        _write(fd, temp, _canonical(value))
        try:
            os.replace(temp, "active.json", src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(temp, dir_fd=fd)
            except FileNotFoundError:
                pass
        return {"active_sha256": digest, "candidate_sha256": candidate_sha}

    def _check_fresh_comparison(self, fd, active, receipt, expected_sha):
        new_ids = {case[side]["receipt_sha256"] for case in receipt["cases"] for side in ("parent", "candidate")}
        cursor = active
        for _ in range(10000):
            previous_receipt = cursor["comparison_sha256"]
            if previous_receipt is not None:
                _digest(previous_receipt)
                if previous_receipt == expected_sha:
                    raise ValueError("Development comparison reused after transition")
                raw = _read(fd, "comparison-" + previous_receipt[7:] + ".json", LIMIT, private=True)
                if _sha(raw) != previous_receipt:
                    raise ValueError("Archived comparison hash mismatch")
                previous = _parse(raw)
                old_ids = {
                    case[side]["receipt_sha256"] for case in previous["cases"] for side in ("parent", "candidate")
                }
                if new_ids & old_ids:
                    raise ValueError("Development episode receipt reused after transition")
            if cursor["previous_sha256"] is None:
                return
            cursor = self._object(fd, cursor["previous_sha256"])
        raise ValueError("Selection history exceeds bounded audit limit")

    def promote(self, candidate_sha256, receipt_path, expected_receipt_sha256, expected_active_sha256):
        _digest(expected_receipt_sha256)
        path = Path(receipt_path).absolute()
        source = _directory(path.parent)
        try:
            raw = _read(source, path.name, LIMIT, private=True)
        finally:
            os.close(source)
        if _sha(raw) != expected_receipt_sha256:
            raise ValueError("Development comparison hash mismatch")
        receipt = _parse(raw)
        with self._locked() as (fd, pins):
            active = self._active(fd, expected_active_sha256)
            candidate = self._candidate(fd, candidate_sha256)
            parent = active["candidate_sha256"]
            if candidate["parent_sha256"] != parent:
                raise ValueError("Candidate parent is not active")
            _comparison(receipt, self.pins_sha256, candidate_sha256, parent, pins)
            self._check_fresh_comparison(fd, active, receipt, expected_receipt_sha256)
            archive = "comparison-" + expected_receipt_sha256[7:] + ".json"
            try:
                _write(fd, archive, raw)
            except FileExistsError:
                if _read(fd, archive, LIMIT, private=True) != raw:
                    raise ValueError("Immutable comparison archive changed") from None
            return self._switch(
                fd, active, expected_active_sha256, candidate_sha256, "promote", expected_receipt_sha256
            )

    def rollback(self, expected_active_sha256):
        with self._locked() as (fd, _):
            active = self._active(fd, expected_active_sha256)
            parent = self._candidate(fd, active["candidate_sha256"])["parent_sha256"]
            if parent is None:
                raise ValueError("Initial candidate has no rollback parent")
            self._candidate(fd, parent)
            return self._switch(fd, active, expected_active_sha256, parent, "rollback", None)


def _comparison(value, pins_sha, candidate_sha, parent_sha, pins):
    _fields(value, {"schema", "pins_sha256", "parent_sha256", "candidate_sha256", "cases"})
    if (value["schema"], value["pins_sha256"], value["parent_sha256"], value["candidate_sha256"]) != (
        "dsh.rsi-development-comparison.v1",
        pins_sha,
        parent_sha,
        candidate_sha,
    ):
        raise ValueError("Development comparison identity mismatch")
    cases = value["cases"]
    if not isinstance(cases, list) or len(cases) != len(pins["case_ids"]):
        raise ValueError("Development cases incomplete")
    seen, receipts, gains = set(), set(), []
    for case in cases:
        _fields(case, {"case_id", "parent", "candidate"})
        if case["case_id"] not in pins["case_ids"] or case["case_id"] in seen:
            raise ValueError("Development case identity mismatch")
        seen.add(case["case_id"])
        for result in (case["parent"], case["candidate"]):
            _fields(result, {"finished", "eligible", "reward", "tokens", "receipt_sha256"})
            reward = result["reward"]
            if result["finished"] is not True or result["eligible"] is not True:
                raise ValueError("Development episode not completed and eligible")
            if type(reward) not in (int, float) or not math.isfinite(reward) or not 0 <= reward <= 1:
                raise ValueError("Invalid development reward")
            if type(result["tokens"]) is not int or not 0 < result["tokens"] <= pins["max_tokens"]:
                raise ValueError("Development token budget exceeded")
            _digest(result["receipt_sha256"])
            if result["receipt_sha256"] in receipts:
                raise ValueError("Development receipt reused")
            receipts.add(result["receipt_sha256"])
        gain = case["candidate"]["reward"] - case["parent"]["reward"]
        if gain < 0:
            raise ValueError("Candidate regresses on development case")
        gains.append(gain)
    if sum(gains) <= 0:
        raise ValueError("Candidate has no development gain")
