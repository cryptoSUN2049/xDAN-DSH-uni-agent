"""Freeze MiMo Code rows as Harbor tasks; never build images or launch resources."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from examples.mimo_dsh_rl.verifier import VerificationError, patch_paths

SOURCE_REPO = "XiaomiMiMo/MiMo-V2.6-RL-oss"
VERIFIER_REVISION = "467f0a19016f0ac4d63b8d17a1f0da9ba07f232c"
FIELDS = {
    "dataset_type",
    "docker_image",
    "cwd",
    "instance_id",
    "problem_statement",
    "test_patch",
    "test_command",
    "verifier_timeout_sec",
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse_instance(row: dict) -> dict:
    """Validate the exact eight-field public contract without rewriting source strings."""
    try:
        extra = row["extra_info"]
        instance = json.loads(extra["instance_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("MiMo row requires extra_info.instance_json") from exc
    if not isinstance(instance, dict) or set(instance) != FIELDS:
        raise ValueError("MiMo instance fields must match the eight-field contract")
    for key in FIELDS - {"verifier_timeout_sec"}:
        if not isinstance(instance[key], str) or not instance[key].strip() or "\x00" in instance[key]:
            raise ValueError(f"Invalid instance field {key}")
    if instance["dataset_type"] != "opensource-code":
        raise ValueError("Only the opensource-code dataset_type is supported")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", instance["instance_id"]) is None:
        raise ValueError("Invalid instance_id")
    if extra.get("instance_id", instance["instance_id"]) != instance["instance_id"]:
        raise ValueError("Conflicting instance_id")
    cwd = PurePosixPath(instance["cwd"])
    if (
        not cwd.is_absolute()
        or ".." in cwd.parts
        or cwd.as_posix() != instance["cwd"]
        or str(cwd) == "/"
        or cwd.parts[1] in {"tests", "logs", "audit-input", "proc", "sys", "dev"}
    ):
        raise ValueError("cwd must be an absolute canonical task workspace")
    timeout = instance["verifier_timeout_sec"]
    if type(timeout) is not int or timeout <= 0:
        raise ValueError("verifier_timeout_sec must be a positive integer")
    if "\n" in instance["test_command"] or "\r" in instance["test_command"]:
        raise ValueError("test_command must be one line")
    if not instance["test_patch"].startswith(("diff --git ", "--- ")):
        raise ValueError("test_patch must be a unified diff")
    try:
        patch_paths(instance["test_patch"])
    except VerificationError as exc:
        raise ValueError(f"test_patch paths are invalid: {exc}") from exc
    if row.get("prompt") != [{"role": "user", "content": instance["problem_statement"]}]:
        raise ValueError("Authoritative prompt must equal the source problem_statement")
    return instance


def load_image_mapping(path: Path | str) -> dict[str, str]:
    mapping = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if not isinstance(entry, dict) or set(entry) != {"dataset_image", "dockerhub_image"}:
            raise ValueError("Invalid image mapping fields")
        source, target = entry["dataset_image"], entry["dockerhub_image"]
        if not isinstance(source, str) or not isinstance(target, str) or not source or not target:
            raise ValueError("Empty image mapping")
        if source in mapping and mapping[source] != target:
            raise ValueError(f"Image mapping conflict for {source}")
        mapping[source] = target
    return mapping


def _image_ref(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("Image requires immutable registry repo@sha256 reference")
    return value


def _gateway_host(origin: str) -> str:
    route = urlsplit(origin)
    hostname = route.hostname or ""
    if (
        route.scheme != "https"
        or "." not in hostname
        or route.path not in ("", "/")
        or route.query
        or route.fragment
        or route.username is not None
        or route.password is not None
        or hostname.endswith((".localhost", ".local", ".internal"))
        or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in hostname.split("."))
    ):
        raise ValueError("Gateway origin must be a public HTTPS origin without path or credentials")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if route.port is not None and route.port <= 0:
            raise ValueError("Invalid Gateway origin port") from None
        return hostname
    raise ValueError("Gateway origin must use DNS")


def prepare_task(
    row, *, output, image_mapping, image_binding, source_revision, split="train", gateway_origin=None
) -> dict:
    """Produce one immutable task package from externally resolved image identities."""
    instance = parse_instance(row)
    if not isinstance(source_revision, str) or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("source_revision must be a fixed 40-character revision")
    if split not in {"train", "validation", "test"}:
        raise ValueError("Unsupported split")
    mapped = image_mapping.get(instance["docker_image"])
    if not mapped:
        raise ValueError(f"Missing image mapping: {instance['docker_image']}")
    original = _image_ref(image_binding.get("original_image"))
    derived = _image_ref(image_binding.get("dsh_image"))
    verifier = _image_ref(image_binding.get("verifier_image", original))
    gateway_host = _gateway_host(gateway_origin) if gateway_origin is not None else None
    # The original resolved image must belong to the exact mapped repository.
    if original.split("@", 1)[0] != mapped.rsplit(":", 1)[0]:
        raise ValueError("Resolved original image differs from mapped repository")
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Task output must be new")
    binding = {
        "schema": "dsh.mimo-code-binding.v1",
        "task_id": instance["instance_id"],
        "cwd": instance["cwd"],
        "runner_python": "/opt/dsh/bin/python",
        "base_ref_capture": "before_agent",
        "artifact_contract": "mimo-code-workspace-v1",
        "image_binding": {"original_image": original, "dsh_image": derived, "verifier_image": verifier},
    }
    verification = {key: instance[key] for key in ("cwd", "test_command", "verifier_timeout_sec")}
    verification.update(test_patch_sha256=sha256(instance["test_patch"].encode()), verifier_revision=VERIFIER_REVISION)
    toml = json.dumps
    network = (
        f'network_mode = "allowlist"\nallowed_hosts = [{toml(gateway_host)}]\n'
        if gateway_host
        else 'network_mode = "no-network"\n'
    )
    files = {
        "instruction.md": instance["problem_statement"].encode(),
        "mimo-binding.json": canonical_json(binding) + b"\n",
        "environment/Dockerfile": f"FROM --platform=linux/amd64 {derived}\n".encode(),
        "tests/test.patch": instance["test_patch"].encode(),
        "tests/verification.json": canonical_json(verification) + b"\n",
        "tests/test.sh": (
            b"#!/bin/sh\nset -eu\nexec python3 /tests/verifier.py --config /tests/verification.json "
            b"--patch /tests/test.patch --base-ref-file /audit-input/mimo-state.json --output-dir /logs/verifier\n"
        ),
        "task.toml": (
            'schema_version = "1.3"\nartifacts = []\n\n[agent]\ntimeout_sec = 1800.0\n\n'
            f"[environment]\ndocker_image = {toml(derived)}\nworkdir = {toml(instance['cwd'])}\n"
            f"{network}"
            "build_timeout_sec = 600.0\ncpus = 2\nmemory_mb = 4096\nstorage_mb = 10240\n\n"
            f'[verifier]\nenvironment_mode = "separate"\ntimeout_sec = {instance["verifier_timeout_sec"] + 120}.0\n\n'
            f"[verifier.environment]\ndocker_image = {toml(verifier)}\nworkdir = {toml(instance['cwd'])}\n"
            'network_mode = "no-network"\nbuild_timeout_sec = 600.0\ncpus = 2\nmemory_mb = 4096\nstorage_mb = 10240\n'
        ).encode(),
    }
    verifier_source = Path(__file__).with_name("verifier.py")
    files["tests/verifier.py"] = verifier_source.read_bytes()
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    task_ref = {"id": "mimo-code-" + instance["instance_id"], "version": "v1", "sha256": sha256(canonical_json(hashes))}
    manifest = {
        "schema": "dsh.mimo-code-task-package.v1",
        "status": "prepared-only",
        "task_ref": task_ref,
        "source_repo": SOURCE_REPO,
        "source_revision": source_revision,
        "source_row_hash": sha256(canonical_json(row)),
        "task_dir": str(output / "task"),
        "task_id": instance["instance_id"],
        "cwd": instance["cwd"],
        "split": split,
        "dataset_image": instance["docker_image"],
        "mapped_image": mapped,
        "original_image": original,
        "dsh_image": derived,
        "verifier_image": verifier,
        "resolved_image_digest": original.split("@", 1)[1],
        "dsh_derived_image_digest": derived.split("@", 1)[1],
        "test_patch_sha256": verification["test_patch_sha256"],
        "verifier_revision": VERIFIER_REVISION,
        "image_binding_hash": sha256(canonical_json(image_binding)),
        "gateway_origin": gateway_origin,
        "artifact_contract": binding["artifact_contract"],
        "files": {"task/" + name: sha256(raw) for name, raw in files.items()},
    }
    for name, raw in files.items():
        target = output / "task" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if name.endswith(".sh"):
            target.chmod(0o755)
    (output / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--row-json", type=Path, required=True)
    parser.add_argument("--image-mapping", type=Path, required=True)
    parser.add_argument("--image-binding", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--split", default="train", choices=("train", "validation", "test"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gateway-origin")
    args = parser.parse_args()
    result = prepare_task(
        json.loads(args.row_json.read_text()),
        output=args.output,
        image_mapping=load_image_mapping(args.image_mapping),
        image_binding=json.loads(args.image_binding.read_text()),
        source_revision=args.source_revision,
        split=args.split,
        gateway_origin=args.gateway_origin,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
