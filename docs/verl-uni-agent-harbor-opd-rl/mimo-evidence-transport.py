"""Standalone private evidence transport; never authorizes training or edits source evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath

CONTROL_LIMIT = 1 << 20
DATA_LIMIT = 32 << 20
JOB_LIMIT = 64 << 20
TOTAL_LIMIT = 256 << 20
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
CHAIN = re.compile(r"(admission|dump)-chain-(0|[1-9][0-9]*)\.json\Z")
KINDS = {"binding", "receipt", "dsh_trace", "dsh_result", "harbor_result", "verifier_log", "reward"}


def canonical(value, newline=True):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        + ("\n" if newline else "")
    ).encode()


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse(raw):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate_json_key")
            value[key] = item
        return value

    def nonfinite(_):
        raise ValueError("nonfinite_json")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def directory(path, private=True):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe_root")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or (private and info.st_mode & 0o077):
            raise ValueError("unsafe_directory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def read(root, relative, limit, private=True):
    path = PurePosixPath(relative)
    if path.is_absolute() or path.as_posix() != relative or any(p in ("..", ".") for p in path.parts):
        raise ValueError("unsafe_relative_path")
    fd = directory(root, private)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or (private and info.st_mode & 0o077):
                raise ValueError("unsafe_directory")
        item = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(item, "rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.getuid()
                or (private and before.st_mode & 0o077)
                or before.st_size > limit
            ):
                raise ValueError("unsafe_or_oversized_file")
            raw = source.read(limit + 1)
            after = os.fstat(source.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink", "st_mode")
            if (
                len(raw) != before.st_size
                or len(raw) > limit
                or any(getattr(before, f) != getattr(after, f) for f in fields)
            ):
                raise ValueError("file_changed")
            return raw
    finally:
        os.close(fd)


def control(root, name):
    raw = read(root, name, CONTROL_LIMIT)
    value = parse(raw)
    if not isinstance(value, dict) or canonical(value) != raw:
        raise ValueError("noncanonical_control")
    return value, raw


def _add(result, root, relative, raw, namespace, previous):
    key = namespace + "/" + relative
    entry = dict(sha256=sha(raw), size_bytes=len(raw), original_absolute_path=str(Path(root) / relative))
    if key in previous and previous[key]["sha256"] != entry["sha256"]:
        raise ValueError("sealed_source_changed")
    if sum(item["size_bytes"] for item in result["files"].values()) + len(raw) > TOTAL_LIMIT:
        raise ValueError("snapshot_budget_exceeded")
    if key not in previous:
        entry["raw"] = raw
    result["files"][key] = entry


def _job(root, job, run_id, result, previous):
    prefix = f"artifacts/{job}/"
    request, req_raw = control(root, prefix + "request.json")
    if (
        request["run_id"] != run_id
        or request["job_id"] != job
        or request["schema"] != "dsh.harbor-job-request.v2"
        or request["termination_policy"] != "budget-terminal-v1"
    ):
        raise ValueError("request_identity")
    if sha(canonical({k: v for k, v in request.items() if k != "request_sha256"}, False)) != request["request_sha256"]:
        raise ValueError("request_hash")
    _add(result, root, prefix + "request.json", req_raw, "gpu-launch", previous)
    manifest, manifest_raw = control(root, prefix + "manifest.json")
    for key in ("job_id", "gateway_session_id", "nonce", "request_sha256"):
        if manifest[key] != request[key]:
            raise ValueError("manifest_identity")
    _add(result, root, prefix + "manifest.json", manifest_raw, "gpu-launch", previous)
    entries, total, seen = manifest["artifacts"], 0, set()
    budget = request["budgets"]["max_artifact_bytes"]
    if type(budget) is not int or not 0 < budget <= JOB_LIMIT or len(entries) > 32:
        raise ValueError("artifact_budget")
    for entry in entries:
        name, size = entry["id"], entry["size_bytes"]
        if not re.fullmatch(r"object-[0-9]+", name) or name in seen or type(size) is not int or size < 0:
            raise ValueError("artifact_identity")
        seen.add(name)
        total += size
        if total > budget:
            raise ValueError("artifact_budget")
        content = read(root, prefix + name, size)
        if len(content) != size or sha(content) != entry["sha256"]:
            raise ValueError("artifact_hash")
        _add(result, root, prefix + name, content, "gpu-launch", previous)
    receipt, receipt_raw = control(root, prefix + "receipt.json")
    expected_finished = receipt.get("termination_kind") == "completed"
    if (
        receipt["schema"] != "dsh.harbor-verifier-receipt.v2"
        or receipt["run_id"] != run_id
        or receipt["termination_policy"] != "budget-terminal-v1"
        or receipt.get("termination_kind") not in {"completed", "budget_exhausted"}
        or receipt["finished"] is not expected_finished
    ):
        raise ValueError("receipt_terminal")
    if (
        manifest["schema"] != "dsh.harbor-job-manifest.v1"
        or manifest["status"] != "succeeded"
        or len(entries) != 7
        or {e["kind"] for e in entries} != KINDS
    ):
        raise ValueError("incomplete_manifest")
    if (
        receipt["manifest_canonical_sha256"] != sha(manifest_raw)
        or sha(canonical({k: v for k, v in receipt.items() if k != "receipt_id"})) != receipt["receipt_id"]
    ):
        raise ValueError("receipt_hash")
    for key in ("job_id", "gateway_session_id", "nonce", "request_sha256", "worker_id", "trial_id", "artifacts"):
        if receipt[key] != manifest[key]:
            raise ValueError("receipt_identity")
    _add(result, root, prefix + "receipt.json", receipt_raw, "gpu-launch", previous)
    state = dict(stage="candidate", chains=[], dumped_chains=[])
    result["jobs"][job] = state
    fd = directory(Path(root) / prefix)
    try:
        names = sorted(os.listdir(fd))
    finally:
        os.close(fd)
    admissions, dumps = {}, {}
    for name in names:
        match = CHAIN.fullmatch(name)
        if not match:
            continue
        kind, index = match.group(1), int(match.group(2))
        value, content = control(root, prefix + name)
        if value["framework_context"] != receipt["framework_context"]:
            raise ValueError("chain_context")
        if kind == "admission":
            if (
                value["schema"] != "dsh.harbor-budget-admission.v1"
                or value["run_id"] != run_id
                or value["chain_id"] != index
                or value["receipt_sha256"] != receipt["receipt_id"]
                or any(value[k] != receipt[k] for k in ("termination_policy", "termination_kind", "finished"))
            ):
                raise ValueError("admission_identity")
            if value["admission_sha256"] != sha(
                canonical({k: v for k, v in value.items() if k != "admission_sha256"}, False)
            ):
                raise ValueError("admission_hash")
            admissions[index] = value
        else:
            if (
                value["schema"] != "dsh.harbor-budget-dump.v1"
                or index not in admissions
                or value["admission_sha256"] != admissions[index]["admission_sha256"]
            ):
                raise ValueError("dump_identity")
            dumps[index] = value
        _add(result, root, prefix + name, content, "gpu-launch", previous)
    state["chains"] = sorted(admissions)
    if admissions:
        state["stage"] = "admitted"
    return receipt, admissions, dumps


def collect(launch_root, agent_log_root, run_id, previous_file_hashes=None):
    if not ID.fullmatch(run_id):
        raise ValueError("unsafe_run_id")
    previous = previous_file_hashes or {}
    result = dict(schema="mimo-evidence-snapshot.v1", run_id=run_id, files={}, jobs={}, pending=[], errors=[])
    jobs = {}
    for name in ("launch.json", "train.parquet", "heldout.parquet", f"registrations/{run_id}/registration.json"):
        try:
            content = read(launch_root, name, DATA_LIMIT)
            if name.endswith(".json"):
                parse(content)
            _add(result, launch_root, name, content, "gpu-launch", previous)
        except FileNotFoundError:
            result["pending"].append(name)
        except (OSError, ValueError, TypeError):
            result["errors"].append(dict(path=name, code="unsafe_or_incomplete_file"))
    try:
        fd = directory(Path(launch_root) / "artifacts")
        try:
            names = sorted(os.listdir(fd))
        finally:
            os.close(fd)
        if len(names) > 1024:
            raise ValueError("job_count_limit")
        for job in names:
            if not ID.fullmatch(job):
                result["errors"].append(dict(code="unsafe_job_name"))
                continue
            try:
                jobs[job] = _job(launch_root, job, run_id, result, previous)
            except FileNotFoundError:
                result["pending"].append(job)
            except (OSError, ValueError, KeyError, TypeError):
                result["jobs"].pop(job, None)
                result["errors"].append(dict(job_id=job, code="job_integrity_rejected"))
    except FileNotFoundError:
        result["pending"].append("artifacts")
    except (OSError, ValueError):
        result["errors"].append(dict(code="unsafe_artifact_root"))
    try:
        os.close(directory(agent_log_root, private=False))
        found = 0
        for base, dirs, files in os.walk(agent_log_root, followlinks=False):
            found += len(dirs) + len(files)
            if found > 10000:
                raise ValueError("agent_scan_limit")
            if "trajectory.json" not in files:
                continue
            relative = (Path(base) / "trajectory.json").relative_to(agent_log_root).as_posix()
            try:
                content = read(agent_log_root, relative, CONTROL_LIMIT, private=False)
                metadata = parse(content)
                if metadata["schema"] != "uni-agent.trajectory-dump.v2":
                    raise ValueError("dump_schema")
                npz_name = str(PurePosixPath(relative).with_name("trajectory.npz"))
                npz = read(agent_log_root, npz_name, DATA_LIMIT, private=False)
                if (
                    sha(npz) != metadata["trajectory_npz_sha256"]
                    or len(metadata["trajectories"]) != metadata["num_trajectories"]
                ):
                    raise ValueError("npz_hash")
                linked = []
                for trajectory in metadata["trajectories"]:
                    job = trajectory["reward_info"]["harbor_dsh"]["job_id"]
                    receipt, admissions, dumps = jobs[job]
                    chain = trajectory["chain_id"]
                    if type(chain) is not int or chain not in admissions or chain not in dumps:
                        raise ValueError("missing_private_chain")
                    context = {key: metadata[key] for key in receipt["framework_context"]}
                    if (
                        context != receipt["framework_context"]
                        or metadata["session_id"] != context["gateway_session_id"]
                        or dumps[chain]["metadata_sha256"] != sha(canonical(metadata, False))
                        or dumps[chain]["trajectory_npz_sha256"] != sha(npz)
                    ):
                        raise ValueError("dump_binding_hash")
                    linked.append((job, chain))
                _add(result, agent_log_root, relative, content, "gpu-agent", previous)
                _add(result, agent_log_root, npz_name, npz, "gpu-agent", previous)
                for job, chain in linked:
                    result["jobs"][job]["dumped_chains"].append(chain)
            except FileNotFoundError:
                result["pending"].append(relative)
            except (OSError, ValueError, KeyError, TypeError):
                result["errors"].append(dict(path=relative, code="dump_integrity_rejected"))
    except FileNotFoundError:
        result["pending"].append("agent_log_root")
    except (OSError, ValueError):
        result["errors"].append(dict(code="unsafe_agent_root"))
    for state in result["jobs"].values():
        if state["chains"] and set(state["chains"]) == set(state["dumped_chains"]):
            state["stage"] = "dump_complete"
    result["source_missing"] = sorted(set(previous) - set(result["files"]))
    return result


def allowed(name, run_id):
    parts = PurePosixPath(name).parts
    if "/".join(parts) != name or len(parts) < 2 or any(not ID.fullmatch(p) for p in parts[:-1]):
        return False
    if parts[0] == "gpu-agent":
        return len(parts) <= 8 and parts[-1] in {"trajectory.json", "trajectory.npz"}
    if parts[0] != "gpu-launch":
        return False
    if len(parts) == 2:
        return parts[1] in {"launch.json", "train.parquet", "heldout.parquet"}
    if len(parts) == 4 and parts[1:3] == ("registrations", run_id):
        return parts[3] == "registration.json"
    return (
        len(parts) == 4
        and parts[1] == "artifacts"
        and (
            parts[-1] in {"request.json", "manifest.json", "receipt.json"}
            or re.fullmatch(r"object-[0-9]+", parts[-1])
            or CHAIN.fullmatch(parts[-1])
        )
    )


def put(root, name, raw):
    parent = root
    for part in PurePosixPath(name).parts[:-1]:
        parent /= part
        parent.mkdir(mode=0o700, exist_ok=True)
        os.close(directory(parent))
    target = root / name
    if target.exists() or target.is_symlink():
        if read(root, name, max(len(raw), 1)) != raw:
            raise ValueError("archive_conflict")
        return
    fd, temporary = tempfile.mkstemp(prefix=".transport-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, target, follow_symlinks=False)
    finally:
        os.unlink(temporary)
    fd = directory(parent)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def archive(snapshot, destination):
    destination = Path(destination)
    if snapshot["schema"] != "mimo-evidence-snapshot.v1" or not ID.fullmatch(snapshot["run_id"]):
        raise ValueError("snapshot_identity")
    if len(snapshot["files"]) > 10000 or sum(e["size_bytes"] for e in snapshot["files"].values()) > TOTAL_LIMIT:
        raise ValueError("snapshot_budget")
    for name, entry in snapshot["files"].items():
        if (
            not allowed(name, snapshot["run_id"])
            or type(entry["size_bytes"]) is not int
            or not 0 <= entry["size_bytes"] <= JOB_LIMIT
        ):
            raise ValueError("unsafe_archive_entry")
        if "raw" in entry and (
            type(entry["raw"]) is not bytes
            or len(entry["raw"]) != entry["size_bytes"]
            or sha(entry["raw"]) != entry["sha256"]
        ):
            raise ValueError("transport_hash")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.close(directory(destination))
    files = {}
    for name, entry in snapshot["files"].items():
        if "raw" in entry:
            put(destination, name, entry["raw"])
        stored = read(destination, name, max(entry["size_bytes"], 1))
        if len(stored) != entry["size_bytes"] or sha(stored) != entry["sha256"]:
            raise ValueError("archive_conflict")
        files[name] = {key: value for key, value in entry.items() if key != "raw"}
    return dict(
        files=files,
        jobs=snapshot["jobs"],
        pending=snapshot["pending"],
        errors=snapshot["errors"],
        source_missing=snapshot["source_missing"],
    )


def wire(snapshot, encode):
    for entry in snapshot["files"].values():
        if "raw" in entry:
            entry["raw"] = (
                base64.b64encode(entry["raw"]).decode("ascii")
                if encode
                else base64.b64decode(entry["raw"], validate=True)
            )
    return snapshot


def main(argv=None):
    import fcntl
    import shlex
    import signal
    import subprocess
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-id", "launch-root", "agent-log-root", "deadline"):
        parser.add_argument("--" + name, required=True, type=float if name == "deadline" else str)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--gpu-host")
    parser.add_argument("--gpu-port", type=int, default=11403)
    parser.add_argument("--ssh-key", type=Path)
    parser.add_argument("--known-hosts", type=Path)
    parser.add_argument("--remote-read", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.deadline)
        or args.deadline <= time.time()
        or args.deadline > time.time() + 86400
        or not ID.fullmatch(args.run_id)
    ):
        raise ValueError("invalid_deadline_or_run")
    os.umask(0o077)
    if args.remote_read:
        signal.alarm(max(1, min(40, int(args.deadline - time.time()))))
        previous_raw = sys.stdin.buffer.read((8 << 20) + 1)
        if len(previous_raw) > 8 << 20:
            raise ValueError("previous_index_limit")
        snapshot = collect(Path(args.launch_root), Path(args.agent_log_root), args.run_id, parse(previous_raw))
        sys.stdout.buffer.write(canonical(wire(snapshot, True), False))
        return
    if not all((args.destination, args.gpu_host, args.ssh_key, args.known_hosts)) or not re.fullmatch(
        r"[A-Za-z0-9.:-]+", args.gpu_host
    ):
        raise ValueError("operator_transport_configuration_required")
    destination = args.destination
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    root_fd = directory(destination)
    lock_fd = os.open("watcher.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("unsafe_lock")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        script = Path(__file__).read_bytes()
        status = dict(
            schema="mimo-private-evidence-transport.v1",
            run_id=args.run_id,
            helper_sha256=sha(script),
            pid=os.getpid(),
            deadline_unix=args.deadline,
            files={},
            jobs={},
            cycles=0,
            scope="byte-preserving transport only; not training admission",
        )
        try:
            previous = parse(read(destination, "status.json", 16 << 20))
            if previous["run_id"] != args.run_id or previous["helper_sha256"] != sha(script):
                raise ValueError("archive_identity_conflict")
            status["files"], status["jobs"] = previous["files"], previous["jobs"]
        except FileNotFoundError:
            pass
        remote = [
            "python3",
            "-c",
            script.decode(),
            "--remote-read",
            "--run-id",
            args.run_id,
            "--launch-root",
            args.launch_root,
            "--agent-log-root",
            args.agent_log_root,
            "--deadline",
            str(args.deadline),
        ]
        command = [
            "ssh",
            "-p",
            str(args.gpu_port),
            "-i",
            str(args.ssh_key),
            "-o",
            "UserKnownHostsFile=" + str(args.known_hosts),
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=2",
            "root@" + args.gpu_host,
            shlex.join(remote),
        ]
        stopped = False

        def stop(_signum, _frame):
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        def save_status():
            fd, temporary = tempfile.mkstemp(prefix=".status-", dir=destination)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(canonical(status))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, destination / "status.json")
                os.fsync(root_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

        while time.time() < args.deadline and not stopped:
            status["cycles"] += 1
            status["last_cycle_started_unix"] = time.time()
            try:
                response = subprocess.run(
                    command,
                    input=canonical(status["files"], False),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=min(45, args.deadline - time.time()),
                    check=True,
                )
                if len(response.stdout) > 384 << 20:
                    raise ValueError("transport_byte_limit")
                snapshot = wire(parse(response.stdout), False)
                if snapshot["run_id"] != args.run_id:
                    raise ValueError("transport_run_mismatch")
                saved = archive(snapshot, destination)
                status["files"].update(saved.pop("files"))
                status.update(saved)
                status["last_success_unix"] = time.time()
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                status["errors"] = [dict(code="cycle_failed", error_type=type(error).__name__)]
            status["last_cycle_finished_unix"] = time.time()
            status["state"] = "watching" if args.watch else "once_finished"
            save_status()
            print(
                json.dumps(
                    dict(
                        state=status["state"],
                        files=len(status["files"]),
                        jobs=len(status["jobs"]),
                        pending=len(status.get("pending", [])),
                        errors=status.get("errors", []),
                    )
                ),
                flush=True,
            )
            if not args.watch:
                return 1 if status.get("errors") else 0
            for _ in range(30):
                if stopped or time.time() >= args.deadline:
                    break
                time.sleep(max(0, min(1, args.deadline - time.time())))
        status["state"] = "stopped" if stopped else "deadline_reached"
        status["finished_unix"] = time.time()
        save_status()
        return 0
    finally:
        os.close(lock_fd)
        os.close(root_fd)


if __name__ == "__main__":
    raise SystemExit(main())
