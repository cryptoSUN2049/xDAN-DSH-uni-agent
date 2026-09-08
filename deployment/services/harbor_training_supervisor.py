"""Bound one owned training process group to its authenticated Harbor controller."""

import argparse
import contextlib
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from deployment.services.harbor_run_controller import read_token


def validate_health(value, expected):
    if any(value.get(key) != item for key, item in expected.items()):
        raise ValueError("Controller identity mismatch")
    if value.get("healthy") is not True or value.get("state") not in ("unregistered", "registering", "ready"):
        raise ValueError("Controller unhealthy")


def supervise(command, cwd, environment, root, health, *, wall_seconds=2700, interval=5, grace=30):
    health()  # No GPU work before the first successful authenticated check.
    started = time.monotonic()
    reason = "training-exited"
    with (root / "train.log").open("xb") as log:
        process = subprocess.Popen(
            command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            while process.poll() is None:
                if time.monotonic() - started >= wall_seconds:
                    reason = "wall-clock-deadline"
                    break
                try:
                    health()
                except Exception:
                    reason = "controller-health-failed"
                    break
                time.sleep(interval)
        finally:
            # Only signal the process group created above; never global Ray/pkill.
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
    result = {
        "exit_code": process.returncode,
        "reason": reason,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "pid": process.pid,
    }
    if reason != "training-exited" and result["exit_code"] == 0:
        result["exit_code"] = 125
    (root / "supervisor-result.json").write_text(json.dumps(result, indent=2) + "\n")
    (root / "exit-code").write_text(str(result["exit_code"]) + "\n")
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    launch = json.loads(args.launch.read_text())
    manifest = json.loads(args.manifest.read_text())
    route = launch["registration"]
    run_id = launch["postprocessor"]["run_id"]
    expected = {"run_id": run_id, "controller_id": route["controller_id"], "run_spec_sha256": route["run_spec_sha256"]}
    token = read_token(Path(route["token_file"]))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        route["controller_url"] + "/v1/runs/" + run_id + "/status", headers={"Authorization": "Bearer " + token}
    )

    def health():
        with opener.open(request, timeout=5) as response:
            value = json.loads(response.read(16385))
        validate_health(value, expected)

    environment = {**os.environ, **manifest["environment"]}
    command = [environment["PYTHON_BIN"], "-m", "examples.harbor.train_m2_online_rl", "--launch", str(args.launch)]
    result = supervise(
        command,
        Path.cwd(),
        environment,
        args.launch.parent,
        health,
        wall_seconds=manifest.get("wall_clock_seconds", 2700),
    )
    raise SystemExit(0 if result["exit_code"] == 0 else 1)


if __name__ == "__main__":
    main()
