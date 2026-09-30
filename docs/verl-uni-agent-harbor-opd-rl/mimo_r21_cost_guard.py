"""Stop only the allocated recovery Pod at its immutable six-hour deadline."""

import argparse
import hashlib
import json
import os
import stat
import time
import urllib.error
import urllib.request
from pathlib import Path

POD = "vo6u0t8x398bnm"
VOLUME = "72jdno5cuk"
ALLOCATION = 1790791473
DEADLINE = 1790813073
AUTH_SHA = "e45736ba0f833f3388ab468ea81dff530eb1580069cd8a5b51ffc7f5ea7dd704"
API = "https://api.runpod.io/v2/pods/" + POD


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Credential must be an owned private regular file")
        raw = stream.read(4097)
    key = raw.decode().strip()
    if not 32 <= len(key) <= 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ValueError("Invalid credential")
    return key


def authorization(path):
    if path.is_symlink() or path.stat().st_mode & 0o222:
        raise ValueError("Authorization must be a readonly regular file")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != AUTH_SHA:
        raise ValueError("Authorization bytes changed")
    value = json.loads(raw)
    expected = {
        "schema": "mimo.recovery-authorization.v1",
        "pod_id": POD,
        "allocated_at_unix": ALLOCATION,
        "deadline_unix": DEADLINE,
        "max_run_seconds": 21600,
        "cleanup_reserve_seconds": 180,
        "stage": "r20f",
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise ValueError("Allocated recovery window differs")
    if os.environ.get("RUNPOD_POD_ID") != POD:
        raise ValueError("Guard must run on its owned Pod")
    return value


def validate_pod(value):
    volumes = {item["volumeId"] for item in value.get("mounts", {}).get("network", [])}
    if (
        value.get("id") != POD
        or value.get("name") != "mimo-dsh-9b-r21-dual-20261001"
        or value.get("gpu", {}).get("count") != 2
        or value.get("gpu", {}).get("id") != "NVIDIA RTX PRO 6000 Blackwell Server Edition"
        or value.get("dataCenterId") != "EUR-IS-1"
        or volumes != {VOLUME}
    ):
        raise ValueError("Refuse any Pod outside this recovery allocation")


def request(key, action=None):
    data = None if action is None else json.dumps({"action": action}).encode()
    req = urllib.request.Request(
        API if action is None else API + "/action",
        data=data,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "runpodctl"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def emit(path, event, **fields):
    value = {"at": time.time(), "event": event, "pod_id": POD, "deadline_unix": DEADLINE, **fields}
    with path.open("a") as stream:
        stream.write(json.dumps(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def stop_owned(key, now):
    if now < DEADLINE:
        raise ValueError("Do not stop before the authorized deadline")
    value = request(key)
    validate_pod(value)
    if value.get("status") == "EXITED":
        return {"status": "EXITED", "already_stopped": True}
    if "stop" not in value.get("actions", []):
        raise ValueError("Stop action unavailable; no automatic delete fallback")
    value = request(key, "stop")
    validate_pod(value)
    return {"status": value.get("status"), "already_stopped": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    authorization(args.authorization)
    key = read_private(args.key)
    value = request(key)
    validate_pod(value)
    emit(args.journal, "identity_checked", status=value.get("status"), check_only=args.check_only)
    if args.check_only:
        print(json.dumps({"passed": True, "read_only": True, "pod_id": POD, "deadline_unix": DEADLINE}))
        return
    emit(args.journal, "armed", pid=os.getpid())
    while time.time() < DEADLINE:
        time.sleep(max(0, min(30, DEADLINE - time.time())))
    # A transient control-plane failure must not silently disable the cost guard.
    while True:
        try:
            result = stop_owned(key, time.time())
            emit(args.journal, "stop_requested", **result)
            return
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            emit(args.journal, "stop_retry", error_type=type(error).__name__)
            time.sleep(30)


if __name__ == "__main__":
    main()
