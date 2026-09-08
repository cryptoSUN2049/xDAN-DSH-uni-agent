"""Bound one owned training process group to its authenticated Harbor controller."""

import argparse
import contextlib
import errno
import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from deployment.services.harbor_run_controller import read_token


def validate_health(value, expected):
    if any(value.get(key) != item for key, item in expected.items()):
        raise ValueError("Controller identity mismatch")
    if value.get("healthy") is not True or value.get("state") not in ("unregistered", "registering", "ready"):
        raise ValueError("Controller unhealthy")


def record_health_failure(root, exc, phase):
    # Deliberately exclude exception text, URL, headers and response body.
    diagnostic = dict(phase=phase, observed_at_unix=time.time(), exception_type=type(exc).__name__)
    if isinstance(exc, urllib.error.HTTPError) and type(exc.code) is int:
        diagnostic["http_status"] = exc.code
    elif isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        diagnostic["reason_type"] = type(exc.reason).__name__
    descriptor = os.open(root / "health-failure.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(diagnostic, output, sort_keys=True)
        output.write("\n")
    return diagnostic


TRANSPORT_FAILURE_WINDOW_SECONDS = 90


def transient_transport_error(exc):
    """Allow only concrete transport faults, never HTTP/auth/validation failures."""
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, urllib.error.URLError):
        exc = exc.reason
    if isinstance(exc, TimeoutError | ConnectionRefusedError | ConnectionResetError | ConnectionAbortedError):
        return True
    if isinstance(exc, socket.gaierror):
        return exc.errno == socket.EAI_AGAIN
    return isinstance(exc, OSError) and exc.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH}


def supervise(command, cwd, environment, root, health, *, wall_seconds=2700, interval=5, grace=30):
    try:
        health()  # No GPU work before the first successful authenticated check.
    except Exception as exc:
        record_health_failure(root, exc, "preflight")
        raise
    health_failure = None
    transport_since = None
    transport_error = None
    transient_failures = 0
    recovered_windows = 0
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
                if (
                    transport_since is not None
                    and time.monotonic() - transport_since >= TRANSPORT_FAILURE_WINDOW_SECONDS
                ):
                    health_failure = record_health_failure(root, transport_error, "runtime")
                    reason = "controller-health-failed"
                    break
                try:
                    health()
                except Exception as exc:
                    if not transient_transport_error(exc):
                        health_failure = record_health_failure(root, exc, "runtime")
                        reason = "controller-health-failed"
                        break
                    transient_failures += 1
                    if transport_since is None:
                        transport_since = time.monotonic()
                    transport_error = exc
                else:
                    # An over-budget check cannot erase the expired outage window.
                    if transport_since is not None:
                        if time.monotonic() - transport_since >= TRANSPORT_FAILURE_WINDOW_SECONDS:
                            health_failure = record_health_failure(root, transport_error, "runtime")
                            reason = "controller-health-failed"
                            break
                        recovered_windows += 1
                    transport_since = None
                    transport_error = None
                remaining = wall_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    reason = "wall-clock-deadline"
                    break
                if transport_since is not None:
                    outage_remaining = TRANSPORT_FAILURE_WINDOW_SECONDS - (time.monotonic() - transport_since)
                    if outage_remaining <= 0:
                        health_failure = record_health_failure(root, transport_error, "runtime")
                        reason = "controller-health-failed"
                        break
                    remaining = min(remaining, outage_remaining)
                time.sleep(min(interval, remaining))
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
        "transient_health_failures": transient_failures,
        "recovered_health_windows": recovered_windows,
    }
    if health_failure is not None:
        result["health_failure"] = health_failure
    if reason != "training-exited" and result["exit_code"] == 0:
        result["exit_code"] = 125
    (root / "supervisor-result.json").write_text(json.dumps(result, indent=2) + "\n")
    (root / "exit-code").write_text(str(result["exit_code"]) + "\n")
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def training_command(manifest, launch_path, python_bin):
    command = [python_bin, "-m", "examples.harbor.train_m2_online_rl", "--launch", str(launch_path)]
    if "lora_adapter" not in manifest:
        return command
    adapter = manifest["lora_adapter"]
    if not isinstance(adapter, dict) or set(adapter) != {"path", "bundle_sha256"}:
        raise ValueError("lora_adapter requires exactly path and bundle_sha256")
    path, digest = adapter["path"], adapter["bundle_sha256"]
    if (
        not isinstance(path, str)
        or not path.strip()
        or "\x00" in path
        or not isinstance(digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
    ):
        raise ValueError("lora_adapter requires a nonempty path and fixed bundle sha256")
    # The existing wrapper verifies the actual adapter files and bundle identity.
    return command + ["--lora-adapter-path", path, "--lora-adapter-bundle-sha256", digest]


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
    command = training_command(manifest, args.launch, environment["PYTHON_BIN"])
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
