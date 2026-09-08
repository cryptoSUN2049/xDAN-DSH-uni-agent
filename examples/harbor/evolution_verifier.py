"""Independent Harbor verifier for the frozen original evolution scoring rule."""

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from uni_agent.tasks.harbor_dsh.evolution_scoring import (
    EvolutionBinding,
    _json,
    load_evolution_binding,
    require_evolution_admission,
    score_evolution,
)


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("Verifier evidence must be a bounded regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Verifier evidence exceeds budget")
    return raw


def run_verifier(
    *,
    input_dir=Path("/audit-input"),
    output_dir=Path("/logs/verifier"),
    fixture_path=Path("/tests/fixture.json"),
    metadata_path=Path("/tests/metadata.json"),
    repository_root=None,
):
    source, destination = Path(input_dir), Path(output_dir)
    if source.is_symlink() or not source.is_dir() or destination.is_symlink():
        raise ValueError("Invalid verifier directory")
    for name in ("reward.txt", "evolution-report.json"):
        if (destination / name).exists() or (destination / name).is_symlink():
            raise ValueError("Refusing to overwrite verifier output")
    binding = EvolutionBinding.model_validate(_json(_read(source / "evolution-binding.json", 65536)))
    if binding.fixture_path != "/tests/fixture.json" or binding.metadata_path != "/tests/metadata.json":
        raise ValueError("Evolution verifier requires fixed controller-owned input paths")
    # Overrides are for isolated CPU tests; the public CLI exposes no path override.
    binding = binding.model_copy(update={"fixture_path": str(fixture_path), "metadata_path": str(metadata_path)})
    frozen = load_evolution_binding(
        binding, binding.task_ref, repository_root=Path(repository_root or Path(__file__).resolve().parents[2])
    )
    trace = _read(source / "session.jsonl", 16 * 1024 * 1024)
    run_raw = _read(source / "run.json", 1024 * 1024)
    status = _json(_read(source / "status.json", 65536))
    run = _json(run_raw)
    if not isinstance(status, dict) or not isinstance(run, dict):
        raise ValueError("Bridge evidence must be objects")
    session = status.get("gateway_session_id")
    if not isinstance(session, str) or not session:
        raise ValueError("Missing Gateway session")
    count = sum(bool(line.strip()) for line in trace.splitlines())
    expected = dict(
        schema="dsh.harbor-agent-execution.v1",
        status="completed",
        finished=True,
        finish_reason="completed",
        dsh_session_id="dsh-" + session,
        trace_sha256=_sha(trace),
        run_sha256=_sha(run_raw),
        event_count=count,
    )
    trace_path = "/tmp/uni-agent-dsh/artifacts/" + hashlib.sha256(session.encode()).hexdigest()[:24] + "/session.jsonl"
    if (
        any(status.get(k) != v for k, v in expected.items())
        or status.get("finished") is not True
        or type(status.get("event_count")) is not int
        or run.get("trace_path") != trace_path
    ):
        raise ValueError("Bridge status/session/trace identity mismatch")
    report = score_evolution(
        frozen=frozen,
        task_ref=binding.task_ref,
        trace=trace,
        trace_sha256=_sha(trace),
        run_raw=run_raw,
        run_sha256=_sha(run_raw),
        gateway_session_id=session,
    )
    require_evolution_admission(report, report["reward"])
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "evolution-report.json").open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    with (destination / "reward.txt").open("x") as stream:
        stream.write(str(report["reward"]) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("/audit-input"))
    parser.add_argument("--output-dir", type=Path, default=Path("/logs/verifier"))
    try:
        report = run_verifier(**vars(parser.parse_args()))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        print(f"Evolution Harbor verifier rejected evidence: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
