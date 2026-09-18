"""Measure what one pipeline run cost on Modal and whether the sandbox discipline held.

Used by ``90_cost.sh``; also runnable by hand against any run root without side
effects (it only writes ``--out``)::

    python cost_report.py --pipe-root /workspace/.../runs/pipe-r9 --out /tmp/cost.json

Numbers:
  trials, trial_hours     from "Harbor trial done ... elapsed=Ns" in the run's task.log files
  billed_usd              Modal hourly billing rows of ``--app`` inside the run window
  billed_core_hours       CPU dollars / Sandbox CPU price (each sandbox reserves one core;
                          Modal bills max(reserved, used), so CPU bursts count too)
  billed_to_used_ratio    billed_core_hours / trial_hours           threshold <= 1.5
  usd_per_trial           billed_usd / trials                       threshold <= 0.05
  leaked_sandboxes        sandboxes of ``--app`` still alive now    threshold 0

A number that cannot be measured is a breach ("unmeasured:<name>"): a missing
measurement proves nothing, so it must not read as a pass.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Modal Sandbox prices (3x the Function prices). The 2026-09-17 bill back-computes to
# exactly these: 267.88 USD CPU / 0.1419 = 1888 core-h, 90.20 USD memory / 0.0240 = 3756 GiB-h.
CPU_USD_PER_CORE_HOUR = 0.00003942 * 3600
MEM_USD_PER_GIB_HOUR = 0.00000667 * 3600
HARBOR_DEFAULT_APP = "__harbor__"
THRESHOLDS = {"billed_to_used_ratio": 1.5, "usd_per_trial": 0.05, "leaked_sandboxes": 0}
_TRIAL_DONE = re.compile(r"Harbor trial done: .*? elapsed=([0-9.]+)s")


def trial_hours(pipe_root: Path) -> tuple[float, int]:
    seconds, trials = 0.0, 0
    for log in pipe_root.rglob("task.log"):
        for match in _TRIAL_DONE.finditer(log.read_text(errors="replace")):
            seconds += float(match.group(1))
            trials += 1
    return seconds / 3600, trials


def run_start(pipe_root: Path) -> datetime | None:
    """UTC time of the first record in pipeline-summary.jsonl (the driver start)."""
    summary = pipe_root / "pipeline-summary.jsonl"
    if not summary.exists():
        return None
    for line in summary.read_text(errors="replace").replace("\x00", "").splitlines():
        try:
            return datetime.strptime(json.loads(line)["utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (ValueError, KeyError, TypeError):
            continue
    return None


def billed_by_resource(rows: list[dict], app: str, window_start: datetime) -> tuple[dict[str, float], str | None]:
    """Sum hourly billing rows of one app from the hour containing window_start onward."""
    first_hour = window_start.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    totals: dict[str, float] = defaultdict(float)
    latest = None
    for row in rows:
        if row.get("description") != app:
            continue
        hour = datetime.fromisoformat(row["interval_start"]).replace(tzinfo=None)
        if hour < first_hour:
            continue
        totals[row["resource"]] += float(row["cost"])
        latest = max(latest or row["interval_start"], row["interval_start"])
    return dict(totals), latest


def fetch_billing_rows(since: datetime) -> list[dict]:
    # An --end of "now" drops the current, still-filling hour; ending tomorrow keeps it,
    # the same way `--for today` does.
    until = datetime.now(timezone.utc) + timedelta(days=1)
    cmd = ["modal", "billing", "report", "--start", since.strftime("%Y-%m-%d"), "--end", until.strftime("%Y-%m-%d")]
    out = subprocess.run(
        [*cmd, "-r", "h", "--show-resources", "--json"],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    ).stdout
    return json.loads(out)


def app_from_task_config(path: Path) -> str:
    """The Modal app Harbor creates sandboxes in: environment_kwargs.app_name, else Harbor's default."""
    import yaml

    entries = yaml.safe_load(path.read_text())
    for entry in entries if isinstance(entries, list) else [entries]:
        if isinstance(entry, dict) and entry.get("harbor_env") == "modal":
            return str((entry.get("environment_kwargs") or {}).get("app_name") or HARBOR_DEFAULT_APP)
    return HARBOR_DEFAULT_APP


def live_sandboxes(app: str) -> int:
    import modal

    handle = modal.App.lookup(app, create_if_missing=False)
    return sum(1 for _ in modal.Sandbox.list(app_id=handle.app_id))


def evaluate(
    *, trials: int, used_hours: float, billed: dict[str, float] | None, leaked: int | None
) -> dict[str, object]:
    checks: dict[str, object] = {"trials": trials, "trial_hours": round(used_hours, 2), "leaked_sandboxes": leaked}
    breaches: list[str] = []
    if billed is None:
        breaches.append("unmeasured:billing")
    else:
        usd = sum(billed.values())
        core_hours = billed.get("CPU", 0.0) / CPU_USD_PER_CORE_HOUR
        checks.update(
            billed_usd=round(usd, 2),
            billed_usd_by_resource={k: round(v, 4) for k, v in billed.items() if v},
            billed_core_hours=round(core_hours, 1),
            billed_gib_hours=round(billed.get("Memory", 0.0) / MEM_USD_PER_GIB_HOUR, 1),
        )
        if used_hours > 0:
            ratio = core_hours / used_hours
            checks["billed_to_used_ratio"] = round(ratio, 2)
            if ratio > THRESHOLDS["billed_to_used_ratio"]:
                breaches.append(f"billed_to_used_ratio={ratio:.2f}")
        else:
            breaches.append("unmeasured:trial_hours")
        if trials > 0:
            per_trial = usd / trials
            checks["usd_per_trial"] = round(per_trial, 4)
            if per_trial > THRESHOLDS["usd_per_trial"]:
                breaches.append(f"usd_per_trial={per_trial:.3f}")
        else:
            breaches.append("unmeasured:trials")
    if leaked is None:
        breaches.append("unmeasured:leaked_sandboxes")
    elif leaked > THRESHOLDS["leaked_sandboxes"]:
        breaches.append(f"leaked_sandboxes={leaked}")
    checks["thresholds"] = THRESHOLDS
    checks["breaches"] = breaches
    checks["passed"] = not breaches
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pipe-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task-config", type=Path, help="the run's Harbor task config; its app_name picks the app")
    parser.add_argument("--app", help="Modal app override (default: from --task-config, else Harbor's default)")
    args = parser.parse_args()
    if not args.app:
        args.app = app_from_task_config(args.task_config) if args.task_config else HARBOR_DEFAULT_APP

    used_hours, trials = trial_hours(args.pipe_root)
    start = run_start(args.pipe_root)
    notes: list[str] = []
    billed, billing_through = None, None
    if start is None:
        notes.append("no run start in pipeline-summary.jsonl")
    else:
        try:
            rows = fetch_billing_rows(start - timedelta(hours=1))
            billed, billing_through = billed_by_resource(rows, args.app, start)
        except Exception as exc:  # the CLI or network failing is a measurement gap, not a crash
            notes.append(f"billing report unavailable: {type(exc).__name__}: {exc}")
    leaked = None
    try:
        leaked = live_sandboxes(args.app)
    except Exception as exc:
        notes.append(f"sandbox list unavailable: {type(exc).__name__}: {exc}")

    checks = evaluate(trials=trials, used_hours=used_hours, billed=billed, leaked=leaked)
    checks.update(
        app=args.app,
        window_start=start.strftime("%Y-%m-%dT%H:%M:%SZ") if start else None,
        billing_through_hour=billing_through,
        measured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        notes=notes
        + [
            "the newest billing hour may still be filling in; rerun FROM_STAGE=cost an hour later for the final bill",
            "another run using the same app inside this window inflates the billed numbers",
        ],
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(checks, indent=1))
    keys = ("trials", "trial_hours", "billed_usd", "billed_to_used_ratio", "usd_per_trial", "leaked_sandboxes")
    print(json.dumps({k: checks.get(k) for k in (*keys, "passed", "breaches")}))


if __name__ == "__main__":
    main()
