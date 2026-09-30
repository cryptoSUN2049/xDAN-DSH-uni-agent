"""Independently replay private MiMo/Qwen evidence against actual trajectory NPZ."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def require(condition, message):
    if not condition:
        raise ValueError(message)


def state_ok(state):
    require(set(state) == {"prompt_ids", "response_ids", "response_mask", "response_logprobs"}, "state fields")
    for key in ("prompt_ids", "response_ids"):
        require(all(type(x) is int and x >= 0 for x in state[key]), "invalid token IDs")
    n = len(state["response_ids"])
    require(len(state["response_mask"]) == len(state["response_logprobs"]) == n, "alignment")
    require(all(type(x) is int and x in (0, 1) for x in state["response_mask"]), "mask")
    require(all(type(x) in (int, float) and math.isfinite(x) for x in state["response_logprobs"]), "finite")


def replay(events):
    require(bool(events), "empty journal")
    session = events[0]["session_id"]
    pending, chains, versions, starts = {}, {}, {}, {}
    terminal = None
    committed = 0
    context_tokens = 0
    model_tokens = 0
    for seq, event in enumerate(events):
        require(terminal is None, "event after finalize")
        require(event["schema"] == "uni-agent.token-journal.v1" and event["session_id"] == session, "identity")
        require(type(event["seq"]) is int and event["seq"] == seq, "sequence")
        kind = event["kind"]
        if kind == "prepare":
            request = event["request"]
            require(type(request) is int and request == len(pending), "request sequence")
            prepared = event["prepared"]
            state_ok(prepared)
            require(event["context_ids"] == prepared["prompt_ids"] + prepared["response_ids"], "backend context")
            old = event["previous"]
            if old is None:
                require(event["chain_id"] is None and not event["rollback"], "new chain")
                require(prepared["response_ids"] == [], "new chain response")
            else:
                state_ok(old)
                require(chains.get(event["chain_id"]) == old, "prior committed chain")
                prefix = event["assistant_prefix"]
                expected_prompt = old["prompt_ids"]
                keep = len(old["response_ids"])
                if event["rollback"]:
                    start = starts[event["chain_id"]]
                    require(bool(prefix), "empty assistant prefix")
                    require(event["rollback_keep"] == len(start["response_ids"]) - len(prefix), "rollback boundary")
                    if not start["response_ids"]:
                        require(start["prompt_ids"][-len(prefix) :] == prefix, "rollback prompt suffix")
                        expected_prompt = start["prompt_ids"][: -len(prefix)]
                        keep = 0
                    else:
                        require(start["response_ids"][-len(prefix) :] == prefix, "rollback response suffix")
                        keep = event["rollback_keep"]
                require(prepared["prompt_ids"] == expected_prompt, "unsupported prompt rewrite")
                require(type(keep) is int and 0 <= keep <= len(old["response_ids"]), "rollback boundary")
                for key in ("response_ids", "response_mask", "response_logprobs"):
                    require(prepared[key][:keep] == old[key][:keep], "retained prefix changed")
                added = len(prepared["response_ids"]) - keep
                require(added >= 0, "context truncated")
                require(prepared["response_mask"][keep:] == [0] * added, "context/boundary trained")
                require(prepared["response_logprobs"][keep:] == [0.0] * added, "context logprob")
                context_tokens += added
            pending[request] = {"prepare": event, "backend": None, "closed": False}
        elif kind in {"backend", "commit", "failure", "denied"}:
            require(event.get("request") in pending, "event without prepare")
            item = pending[event["request"]]
            require(not item["closed"], "event after request terminal")
            if kind == "backend":
                require(item["backend"] is None, "duplicate backend")
                ids, probs = event["token_ids"], event["log_probs"]
                require(isinstance(probs, list) and len(ids) == len(probs), "backend logprob alignment")
                require(all(type(t) is int and t >= 0 for t in ids), "backend tokens")
                require(all(type(p) in (int, float) and math.isfinite(p) for p in probs), "backend finite")
                lo, hi = event["min_global_steps"], event["max_global_steps"]
                require(type(lo) is int and type(hi) is int and 0 <= lo <= hi, "backend policy version")
                item["backend"] = event
            elif kind == "commit":
                backend = item["backend"]
                require(
                    backend is not None and backend["stop_reason"] not in {"abort", "aborted"},
                    "commit without successful backend",
                )
                prep = item["prepare"]
                expected = {key: list(value) for key, value in prep["prepared"].items()}
                expected["response_ids"] += backend["token_ids"]
                expected["response_mask"] += [1] * len(backend["token_ids"])
                expected["response_logprobs"] += backend["log_probs"]
                state_ok(event["state"])
                require(event["state"] == expected, "assistant token/mask/logprob merge")
                chain = event["chain_id"]
                require(type(chain) is int and chain > 0, "chain id")
                if prep["chain_id"] is None:
                    require(chain not in chains, "duplicate new chain")
                    versions[chain] = []
                else:
                    require(chain == prep["chain_id"] and chains[chain] == prep["previous"], "commit changed chain")
                if prep["rollback"]:
                    require(bool(versions[chain]), "rollback without prior generation")
                    versions[chain].pop()
                versions[chain].append((backend["min_global_steps"], backend["max_global_steps"]))
                chains[chain] = expected
                starts[chain] = prep["prepared"]
                committed += 1
                model_tokens += len(backend["token_ids"])
                item["closed"] = True
            else:
                require(kind != "denied" or item["backend"] is None, "denied after backend")
                prep = item["prepare"]
                if kind == "denied" and prep["chain_id"] is not None and prep["rollback"]:
                    chain = prep["chain_id"]
                    if not starts[chain]["response_ids"]:
                        del chains[chain]
                        del versions[chain]
                        del starts[chain]
                    else:
                        chains[chain] = prep["prepared"]
                        versions[chain].pop()
                item["closed"] = True
        elif kind == "finalize":
            require(all(v["closed"] for v in pending.values()), "unfinished request")
            terminal = event["trajectories"]
            require(len({t["chain_id"] for t in terminal}) == len(terminal), "duplicate final chain")
            require({t["chain_id"] for t in terminal} == set(chains), "missing final chain")
            for trajectory in terminal:
                require(
                    trajectory["state"] == chains[trajectory["chain_id"]], "final state differs from committed state"
                )
        else:
            raise ValueError("unknown journal event")
    require(terminal is not None and committed > 0, "no completed real generation")
    return (
        terminal,
        versions,
        {
            "session_id": session,
            "commits": committed,
            "backend_tokens": model_tokens,
            "context_tokens": context_tokens,
            "events": len(events),
        },
    )


def audit(journal, metadata):
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    terminal, versions, summary = replay(events)
    meta = json.loads(metadata.read_text())
    npz = metadata.with_name("trajectory.npz")
    digest = hashlib.sha256(npz.read_bytes()).hexdigest()
    require(meta["trajectory_npz_sha256"] == "sha256:" + digest, "NPZ hash")
    require(meta["gateway_session_id"] == summary["session_id"], "dump session")
    require(len(meta["trajectories"]) == len(terminal), "dump chains")
    with np.load(npz, allow_pickle=False) as arrays:
        for index, (saved, expected) in enumerate(zip(meta["trajectories"], terminal, strict=True)):
            chain = expected["chain_id"]
            require(saved["chain_id"] == chain, "dump chain identity")
            require(saved["generation_count"] == len(versions[chain]), "generation count")
            require(saved["min_global_steps"] == min(v[0] for v in versions[chain]), "minimum policy version")
            require(saved["max_global_steps"] == max(v[1] for v in versions[chain]), "maximum policy version")
            for key, value in expected["state"].items():
                dtype = np.float32 if key == "response_logprobs" else np.int64
                require(np.isfinite(np.asarray(value, dtype=dtype)).all(), "normalized finite")
                require(np.isfinite(arrays[f"traj{index}_{key}"]).all(), "NPZ finite")
                require(
                    np.array_equal(arrays[f"traj{index}_{key}"], np.asarray(value, dtype=dtype)), "NPZ differs: " + key
                )
    return {
        "passed": True,
        **summary,
        "journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
        "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
        "npz_sha256": digest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-dir", type=Path, required=True)
    parser.add_argument("--agent-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session-id", action="append", default=[])
    args = parser.parse_args()
    results = []
    try:
        selected = set(args.session_id)
        seen = set()
        for metadata in sorted(args.agent_dir.rglob("trajectory.json")):
            session = json.loads(metadata.read_text())["gateway_session_id"]
            if selected and session not in selected:
                continue
            require(session not in seen, "duplicate dump session")
            seen.add(session)
            journal = args.journal_dir / (hashlib.sha256(session.encode()).hexdigest() + ".jsonl")
            results.append(audit(journal, metadata))
        require(bool(results), "no actual trajectory dumps")
        require(not selected or selected == seen, "missing selected session")
        report = {
            "schema": "mimo.token-semantic-audit.v1",
            "passed": True,
            "sessions": results,
            "selection": "explicit_session_ids" if selected else "all_finalized_dumps",
            "training_consumption_proven_by_this_audit": False,
            "scope": "backend output transport and MiMo/Qwen merge semantics; not model forward recomputation",
        }
    except Exception as exc:
        report = {
            "schema": "mimo.token-semantic-audit.v1",
            "passed": False,
            "sessions": results,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
