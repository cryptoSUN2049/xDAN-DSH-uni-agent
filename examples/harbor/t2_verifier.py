"""Independent Harbor T2 public-fixture verifier, after trusted host bridge upload.

The three supplied files are consistency checked, not independent attestation.
Container orchestration must bind their origin to the requested trial/session.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from examples.dsh.capability_tasks.log_tool.verifier import verify_trace
from uni_agent.agents.dsh.harbor_release import T2_PATCH_SHA256, release_patch_paths_digest


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Verifier input must be a regular file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Verifier input exceeds byte budget")
    return raw


def _json(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate JSON key")
            obj[key] = value
        return obj

    def invalid(value):
        raise ValueError("Nonfinite JSON")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def run_verifier(*, fixture_path, input_dir=Path("/audit-input"), output_dir=Path("/logs/verifier")):
    source, destination = Path(input_dir), Path(output_dir)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Invalid audit input directory")
    if (destination / "reward.txt").exists() or (destination / "reward.txt").is_symlink():
        raise ValueError("Refusing to overwrite a previous reward")
    trace = _read(source / "session.jsonl", 16 * 1024 * 1024)
    raw_run = _read(source / "run.json", 1024 * 1024)
    status = _json(_read(source / "status.json", 65536))
    helper = _json(raw_run)
    if not isinstance(status, dict) or not isinstance(helper, dict):
        raise ValueError("Bridge evidence must be objects")
    session = status.get("gateway_session_id")
    if not isinstance(session, str) or not session:
        raise ValueError("Missing Gateway session identity")
    trace_path = "/tmp/uni-agent-dsh/artifacts/" + hashlib.sha256(session.encode()).hexdigest()[:24] + "/session.jsonl"
    count = sum(bool(line.strip()) for line in trace.splitlines())
    expected_status = dict(
        schema="dsh.harbor-agent-execution.v1",
        status="completed",
        finished=True,
        finish_reason="completed",
        dsh_session_id="dsh-" + session,
        trace_sha256=_sha(trace),
        run_sha256=_sha(raw_run),
        event_count=count,
    )
    expected_helper = dict(
        schema="dsh.uni-agent.dsh-run.v1",
        dsh_session_id="dsh-" + session,
        finish_reason="completed",
        trace_persisted=True,
        trace_sha256=_sha(trace),
        event_count=count,
        profile="sdk-minimal",
        trace_path=trace_path,
        patches_sha256=release_patch_paths_digest(
            SimpleNamespace(profile="sdk-minimal", patch_sha256s=(T2_PATCH_SHA256,))
        ),
    )
    if (
        any(status.get(k) != v for k, v in expected_status.items())
        or any(helper.get(k) != v for k, v in expected_helper.items())
        or status.get("finished") is not True
        or helper.get("trace_persisted") is not True
        or type(status.get("event_count")) is not int
        or type(helper.get("event_count")) is not int
    ):
        raise ValueError("Bridge hash/session/finished identity mismatch")
    fixture_raw = _read(Path(fixture_path), 1024 * 1024)
    fixture = _json(fixture_raw)
    if not isinstance(fixture, dict) or not isinstance(fixture.get("calls"), list):
        raise ValueError("Invalid fixed public fixture")
    evaluation = verify_trace(source / "session.jsonl", _sha(trace), fixture=fixture)
    if evaluation["eligible"] is not True:
        raise ValueError("Untrusted trace rejected: " + ",".join(evaluation["reasons"]))
    reward = int(evaluation["passed"] is True)
    report = dict(
        schema="dsh.harbor-t2-verifier.v1",
        reward=float(reward),
        evaluation=evaluation,
        gateway_session_id=session,
        dsh_session_id="dsh-" + session,
        trace_sha256=_sha(trace),
        fixture_sha256=_sha(fixture_raw),
        hidden_inputs_verified=False,
    )
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "t2-report.json").open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    with (destination / "reward.txt").open("x") as stream:
        stream.write(str(reward) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", dest="fixture_path", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, default=Path("/audit-input"))
    parser.add_argument("--output-dir", type=Path, default=Path("/logs/verifier"))
    try:
        report = run_verifier(**vars(parser.parse_args()))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        print(f"T2 Harbor verifier rejected evidence: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
