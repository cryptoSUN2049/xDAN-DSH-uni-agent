"""Observe complete live Session v2 pairs; bound repeated denials without changing rewards."""

import os
import stat
from pathlib import Path

from examples.dsh.capabilities.memory_verifier import canonical, loads, sha
from uni_agent.tasks.dsh.memory_artifacts import _directory


class RepeatedMemoryDenial(RuntimeError):
    pass


def repeated_denials(raw):
    pending, seen = {}, set()
    previous, count = None, 0
    empty = {"count": 0, "action_sha256": None}
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break  # A live append may be between JSON bytes and its terminal newline.
        if not line.strip():
            continue
        try:
            event = loads(line)
        except (ValueError, UnicodeError):
            return empty  # Malformed complete records are not evidence of a denial.
        if not isinstance(event, dict):
            return empty
        data = event.get("data", {})
        if not isinstance(data, dict):
            return empty
        if event.get("type") == "tool/call":
            call_id = data.get("callId")
            if not isinstance(call_id, str) or not call_id or call_id in seen:
                return empty
            seen.add(call_id)
            try:
                args = loads(data["arguments"]) if isinstance(data.get("arguments"), str) else data["arguments"]
                if not isinstance(args, dict) or not isinstance(data.get("name"), str):
                    return empty
                pending[call_id] = sha(canonical({"name": data["name"], "arguments": args}))
            except (KeyError, ValueError, TypeError):
                return empty
        elif event.get("type") == "tool/result":
            message = data.get("message", {})
            if not isinstance(message, dict):
                return empty
            source = message.get("source", {})
            blocks = message.get("content", [])
            call_id = source.get("callId") if isinstance(source, dict) else None
            if (
                not isinstance(call_id, str)
                or call_id not in pending
                or not isinstance(blocks, list)
                or len(blocks) != 1
                or not isinstance(blocks[0], dict)
                or blocks[0].get("toolCallId") != call_id
                or blocks[0].get("type") != "tool-result"
            ):
                return empty
            signature = pending.pop(call_id)
            contents = blocks[0].get("content", [])
            if not isinstance(contents, list) or any(
                not isinstance(block, dict) or (block.get("type") == "text" and not isinstance(block.get("text"), str))
                for block in contents
            ):
                return empty
            text = (
                "".join(
                    block.get("text", "")
                    for block in contents
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                if isinstance(contents, list)
                else ""
            )
            denied = blocks[0].get("isError") is True and text.startswith("Error: MEMORY_POLICY_DENIED")
            if denied:
                count = count + 1 if signature == previous else 1
                previous = signature
            else:
                previous, count = None, 0
    return {"count": count, "action_sha256": previous}


def _live_snapshot(path):
    parent = _directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8_000_000:
            return b""
        return stream.read(8_000_000)


def denial_health(run_root, *, threshold=3):
    """Fresh stage-owned files only; exceptions ask the existing supervisor to stop its group."""
    run_root = Path(run_root)

    def check():
        for path in (run_root / "homes").glob("*/sessions/*/*/session.v2.jsonl"):
            try:
                result = repeated_denials(_live_snapshot(path))
            except (OSError, ValueError):
                continue  # An incompletely created live path is not confirmed evidence.
            if result["count"] < threshold:
                continue
            report = {
                "schema": "dsh.memory-denial-budget.v1",
                "threshold": threshold,
                **result,
                "session_log": str(path.relative_to(run_root)),
                "status": "failed-repeated-policy-denial",
            }
            output = run_root / "repeated-denial.json"
            try:
                fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical(report))
            raise RepeatedMemoryDenial("Confirmed repeated policy denial budget reached")

    return check
