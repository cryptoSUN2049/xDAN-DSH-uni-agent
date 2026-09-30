"""Opt-in private evidence; never used to construct training data."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path

MAX_BYTES = 512 * 1024 * 1024
MAX_EVENTS = 10000


def snapshot(value):
    return {
        name: list(getattr(value, name) or [])
        for name in ("prompt_ids", "response_ids", "response_mask", "response_logprobs")
    }


class TokenJournal:
    """One session file, with a locked directory-wide byte/event budget."""

    @classmethod
    def from_env(cls, session_id):
        root = os.environ.get("UNI_AGENT_TOKEN_JOURNAL_DIR")
        return cls(Path(root), session_id) if root else None

    def __init__(self, root, session_id):
        if not root.is_absolute() or root.resolve() != root:
            raise ValueError("token journal needs an absolute path without symlinks")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.stat().st_mode & 0o077:
            raise ValueError("token journal directory must be private (0700)")
        self.session_id = session_id
        self.seq = 0
        self.requests = 0
        self.root = root
        self.path = root / (hashlib.sha256(session_id.encode()).hexdigest() + ".jsonl")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)

    def write(self, kind, **payload):
        event = {
            "schema": "uni-agent.token-journal.v1",
            "session_id": self.session_id,
            "seq": self.seq,
            "kind": kind,
            **payload,
        }
        data = (json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n").encode()
        fd = os.open(self.root / ".budget", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+b") as budget:
            fcntl.flock(budget, fcntl.LOCK_EX)
            state = json.loads(budget.read() or b'{"bytes":0,"events":0}')
            state["bytes"] += len(data)
            state["events"] += 1
            if state["bytes"] > MAX_BYTES or state["events"] > MAX_EVENTS:
                raise RuntimeError("token journal run budget exceeded")
            out = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
            with os.fdopen(out, "ab") as stream:
                stream.write(data)
                stream.flush()
            budget.seek(0)
            budget.write(json.dumps(state).encode())
            budget.truncate()
            budget.flush()
        self.seq += 1

    def prepare(self, encoded, previous, assistant_prefix):
        request = self.requests
        self.requests += 1
        self.write(
            "prepare",
            request=request,
            chain_id=encoded.chain_id,
            prepared=snapshot(encoded.buffer),
            context_ids=list(encoded.context_ids),
            previous=snapshot(previous.buffer) if previous else None,
            rollback=encoded.rollback_applied,
            assistant_prefix=list(assistant_prefix),
            rollback_keep=(previous.last_assistant_start.response_ids_len - len(assistant_prefix))
            if previous and encoded.rollback_applied
            else None,
            message_roles=[m.get("role") for m in encoded.messages],
        )
        return request
