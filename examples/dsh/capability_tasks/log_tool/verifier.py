"""Strict public-input T2 lifecycle verifier over hash-bound DSH logical events.

Does not execute hidden inputs, authenticate the task envelope, or attest a hostile
host. The caller must separately bind session, runtime, fixture and verifier hashes.
"""

import json
import re
from pathlib import Path

from examples.dsh.capability_tasks.log_tool.oracle import evaluate
from examples.dsh.evolution_verifier import _load_trace, _tool_calls, _tool_results

QUERY = {"platform": "host", "provider": "Tool", "method": "listTools"}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _json(text):
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, "duplicate-json-key")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("nonfinite-json")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _paired(events):
    pending = None
    seen = set()
    pairs = []
    failed = False
    for event in events:
        if event.get("type") == "tool/call":
            parsed = _tool_calls([event])
            _require(pending is None and len(parsed) == 1, "malformed-or-overlapping-call")
            pending = parsed[0]
            cid = pending["call_id"]
            _require(cid not in seen, "duplicate-call-id")
            seen.add(cid)
            args = event["data"]["arguments"]
            pending["parsed_arguments"] = _json(args) if isinstance(args, str) else args
            _require(isinstance(pending["parsed_arguments"], dict), "arguments-not-object")
        elif event.get("type") == "tool/result":
            _require(pending is not None, "orphan-or-duplicate-result")
            data = event["data"]
            message = data["message"]
            blocks = message["content"]
            _require(isinstance(blocks, list) and len(blocks) == 1, "ambiguous-result-blocks")
            block = blocks[0]
            cid = pending["call_id"]
            _require(block.get("type") == "tool-result" and block.get("toolCallId") == cid, "result-call-id-mismatch")
            _require(message.get("source", {}).get("callId") == cid, "result-source-id-mismatch")
            result = _tool_results([event]).get(cid)
            _require(result is not None and type(block.get("isError")) is bool, "missing-explicit-result-status")
            failed = failed or block["isError"] or bool(result["error"])
            pairs.append((pending["name"], pending["parsed_arguments"], result["text"]))
            pending = None
    _require(pending is None, "missing-result")
    return pairs, failed


def _inventory(args, text):
    _require(args == QUERY or args == {**QUERY, "input": {}}, "wrong-inventory-query")
    value = _json(text)
    _require(all(value.get(k) == v for k, v in QUERY.items()), "wrong-inventory-response")
    tools = value["data"]["tools"]
    _require(isinstance(tools, list), "invalid-tool-inventory")
    names = [tool["name"] for tool in tools]
    _require(
        all(isinstance(name, str) and name for name in names) and len(names) == len(set(names)),
        "invalid-or-duplicate-tool-name",
    )
    return set(names)


def evaluate_events(events, *, fixture, tool_name="filter_redact_logs"):
    report = dict(passed=False, eligible=False, reasons=[], matched_calls=0, hidden_inputs_verified=False)
    try:
        _require(isinstance(events, list) and events and events[-1]["type"] == "turn/end", "terminal-event-missing")
        reason = events[-1]["data"].get("reason")
        _require(
            reason == "completed" or isinstance(reason, dict) and reason.get("kind") == "completed",
            "episode-not-completed",
        )
        allowed = {_canonical(call): call for call in fixture["calls"]}
        _require(len({_canonical(call["records"]) for call in allowed.values()}) >= 2, "fixture-needs-distinct-inputs")
        paired, failed = _paired(events)
        report["eligible"] = True
        _require(not failed, "failed-tool-result")
        stage = "initial"
        plugin = package = run = None
        baseline = set()
        inputs = set()
        covered = set()
        for name, args, text in paired:
            if name == "cordis_inspect_list":
                _json(text)
                continue
            if stage == "initial":
                _require(name == "cordis_inspect_self" and not args, "initial-plugin-inventory-required")
                value = _json(text)
                _require(value.get("mode") == "plugins" and value.get("plugins") == [], "initial-plugins-not-empty")
                stage = "baseline"
            elif stage == "baseline":
                _require(name == "cordis_inspect_query", "initial-tool-inventory-required")
                baseline = _inventory(args, text)
                _require(tool_name not in baseline, "candidate-already-exists")
                stage = "define"
            elif stage == "define":
                _require(name == "cordis_define" and args.get("plugin", {}).get("kind") == "new", "new-plugin-required")
                code = args.get("code", {})
                _require(
                    isinstance(code.get("host"), str) and code["host"] and "client" not in code,
                    "host-only-code-required",
                )
                match = re.match(r"^Defined ([^/\s]+)/([^\s(]+) \(", text)
                _require(match is not None, "define-receipt-invalid")
                plugin, package = match.groups()
                stage = "run"
            elif stage == "run":
                _require(
                    name == "cordis_run" and args == dict(pluginId=plugin, packageId=package, mode="run"),
                    "run-instance-mismatch",
                )
                match = re.fullmatch(
                    re.escape(plugin + "/" + package) + r" is (?:running|starting asynchronously) \(([^\s()]+)\)\.",
                    text,
                )
                _require(match is not None, "run-receipt-invalid")
                run = match[1]
                stage = "running"
            elif stage == "running":
                _require(
                    name == "cordis_inspect_self"
                    and args in (dict(pluginId=plugin), dict(pluginId=plugin, packageId=package)),
                    "running-inspection-required",
                )
                value = _json(text)
                summary = value.get("plugin") if value.get("mode") == "package" else value
                _require(summary.get("pluginId") == plugin, "inspected-plugin-mismatch")
                if summary.get("state") in {"defined", "client-pending"}:
                    continue
                _require(
                    summary.get("state") == "running"
                    and summary.get("currentPackageId") == package
                    and summary.get("activeRun") == dict(packageId=package, pluginRunId=run),
                    "active-run-mismatch",
                )
                if value.get("mode") == "package":
                    _require(
                        value.get("packageId") == package
                        and value["runtime"]["host"]["status"] == "running"
                        and value["runtime"]["host"]["waitingFor"] == [],
                        "package-not-running",
                    )
                else:
                    _require(value.get("mode") == "plugin", "invalid-self-mode")
                stage = "registered"
            elif stage == "registered":
                _require(name == "cordis_inspect_query", "active-tool-inventory-required")
                _require(_inventory(args, text) == baseline | {tool_name}, "unexpected-tool-registration")
                stage = "business"
            elif stage == "business" and name == tool_name:
                _require(_canonical(args) in allowed, "input-not-in-public-fixture")
                _require(_canonical(_json(text)) == _canonical(evaluate(**args)), "business-output-mismatch")
                inputs.add(_canonical(args["records"]))
                covered.add(_canonical(args))
                report["matched_calls"] += 1
            elif stage == "business":
                _require(len(inputs) >= 2, "two-distinct-business-inputs-required")
                _require(covered == set(allowed), "missing-public-fixture-call")
                _require(name == "cordis_stop" and args == dict(pluginId=plugin), "stop-instance-mismatch")
                _require(
                    text == f"Dynamic Plugin {plugin} is stopped; its definition and versions remain.",
                    "stop-receipt-invalid",
                )
                stage = "revoked"
            elif stage == "revoked":
                _require(name == "cordis_inspect_query" and _inventory(args, text) == baseline, "tool-not-revoked")
                stage = "undefine"
            elif stage == "undefine":
                _require(name == "cordis_undefine" and args == dict(pluginId=plugin), "undefine-instance-mismatch")
                _require(
                    text == f"Removed dynamic Plugin {plugin} and all of its Packages.", "undefine-receipt-invalid"
                )
                stage = "empty"
            elif stage == "empty":
                _require(name == "cordis_inspect_self" and not args, "final-inventory-required")
                value = _json(text)
                _require(value.get("mode") == "plugins" and value.get("plugins") == [], "final-plugins-not-empty")
                stage = "done"
            else:
                raise ValueError("unexpected-call-after-cleanup")
        _require(stage == "done", "incomplete-lifecycle")
        report.update(passed=True, eligible=True, plugin_id=plugin, package_id=package, plugin_run_id=run)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        report["reasons"] = [str(error)]
    return report


def verify_trace(path: Path, expected_digest: str, *, fixture: dict, tool_name="filter_redact_logs"):
    return evaluate_events(_load_trace(path, expected_digest), fixture=fixture, tool_name=tool_name)
