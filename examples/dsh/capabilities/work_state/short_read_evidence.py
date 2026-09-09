"""Quality-only evidence for WS07. Read results must precede the generating assistant message."""

import json
import re
from pathlib import Path

from examples.dsh import evolution_verifier as parent
from examples.dsh.capabilities.memory_verifier import read_regular


def _generation(events, call):
    """Bind an executed call to its unique settled model message, not execution order alone."""
    found = []
    data = events[call["index"]]["data"]
    for index, event in enumerate(events[: call["index"]]):
        if event.get("type") != "assistant/message":
            continue
        info = event.get("data", {})
        message = info.get("message", {})
        if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool-call" or block.get("id") != call["call_id"]:
                continue
            try:
                args = (
                    json.loads(block["arguments"])
                    if isinstance(block.get("arguments"), str)
                    else block.get("arguments")
                )
            except ValueError:
                continue
            if (
                block.get("name") == call["name"]
                and args == call["parsed_arguments"]
                and type(info.get("turn")) is int
                and type(info.get("step")) is int
                and (info["turn"], info["step"]) == (data.get("turn"), data.get("step"))
            ):
                found.append(index)
    return found[0] if len(found) == 1 else None


def _result_index(events, call_id):
    found = []
    for index, event in enumerate(events):
        if event.get("type") == "tool/result" and call_id in parent._tool_results([event]):
            found.append(index)
    return found[0] if len(found) == 1 else None


def _full_view(args, raw, result):
    if set(args) - {"command", "path", "view_range"}:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return False
    if not text.strip():
        return False
    bounds = args.get("view_range")
    runtime_lines = text.split("\n")
    if bounds is not None and not (
        isinstance(bounds, list)
        and len(bounds) == 2
        and all(type(n) is int for n in bounds)
        and bounds[0] == 1
        and (bounds[1] == -1 or len(text.splitlines()) <= bounds[1] <= len(runtime_lines))
    ):
        return False
    # DSH formatFileView: padded line number + two spaces, with a header before the lines.
    expected = text.splitlines()
    actual = result.splitlines()
    numbered = [f"{i:6d}  {line}" for i, line in enumerate(expected, 1)]
    return actual == expected or any(actual[i : i + len(numbered)] == numbered for i in range(len(actual)))


def verify_reads(fixture, events) -> dict:
    checks = dict(short_index_read=False, short_handoff_read=False, short_write_after_reads=False)
    root = Path(fixture["unpacked_root"])
    index_path, handoff_path = root / "index.md", root / "handoff.md"
    try:
        index_raw = read_regular(index_path, fixture["max_bytes"])
        handoff_raw = read_regular(handoff_path, fixture["max_bytes"])
        # A relative link/name, never an absolute source path or ../ traversal reference.
        if not re.search(r"(?<![\w./-])(?:\./)?handoff\.md(?![\w/-])", index_raw.decode("utf-8")):
            return checks
    except (FileNotFoundError, ValueError, UnicodeError):
        return checks
    calls, results = parent._tool_calls(events), parent._tool_results(events)
    index_results, handoff_results = [], []
    writes = {str(Path(fixture["output_root"]) / name): [] for name in ("config.json", "plan.json")}
    for call in calls:
        args = call["parsed_arguments"]
        result = results.get(call["call_id"])
        generation = _generation(events, call)
        ri = _result_index(events, call["call_id"])
        if (
            call["name"] != "str_replace_editor"
            or not isinstance(args, dict)
            or generation is None
            or ri is None
            or ri <= call["index"]
            or not result
            or result["is_error"]
            or result["error"]
        ):
            continue
        path = args.get("path")
        if args.get("command") == "view":
            if path == str(index_path) and _full_view(args, index_raw, result["text"]):
                index_results.append(ri)
            if (
                path == str(handoff_path)
                and any(i < generation for i in index_results)
                and _full_view(args, handoff_raw, result["text"])
            ):
                handoff_results.append(ri)
        elif args.get("command") in ("create", "str_replace", "insert") and path in writes:
            writes[path].append(generation)
    checks["short_index_read"] = bool(index_results)
    checks["short_handoff_read"] = bool(handoff_results)
    checks["short_write_after_reads"] = bool(handoff_results) and all(
        generations and max(generations) > min(handoff_results) for generations in writes.values()
    )
    return checks
