"""Package one public T2 Harbor task; never builds images or runs an agent.

The sidecar manifest is outside task/ so the TaskRef can bind every task file
without a self-reference. Source status records uncommitted inputs explicitly.
"""

import argparse
import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path

from examples.dsh.capability_tasks.log_tool.task_bundle import CODE_PATHS, build_rows
from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH, T2_PATCH_SHA256
from uni_agent.agents.dsh.runner import _patches_digest

PARENT_IMAGE = "sha256:846b46c90ebd71b3ababbd4a1cb50459a99d6fde97d42f6503e84a78ce60fc97"
PARENT_TAG = "uni-agent-dsh:0.1.3a2-1263ff5-amd64"
VERIFIER_IMAGE = "python@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
PATCH = Path("examples/dsh/evolution.patch.yml")
FIXTURE = Path("examples/dsh/capability_tasks/log_tool/fixtures/dev-01.json")
IMAGE_MANIFEST = Path("deployment/versions/harbor-execution-image.json")
VERIFIER_SOURCES = (
    Path("examples/harbor/t2_verifier.py"),
    Path("examples/dsh/capability_tasks/log_tool/oracle.py"),
    Path("examples/dsh/capability_tasks/log_tool/verifier.py"),
    Path("examples/dsh/evolution_verifier.py"),
    Path("examples/dsh/verifier.py"),
    Path("uni_agent/agents/dsh/harbor_release.py"),
)


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read(root, relative):
    path = root / relative
    if not path.is_file() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Source must be a regular file: {relative}")
    if any(part.is_symlink() for part in (path, *path.parents) if part != root and root in part.parents):
        raise ValueError(f"Source symlink is not allowed: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Source escapes root: {relative}")
    return path.read_bytes()


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()


def prepare(*, root, output, agent_image_digest, verifier_image_digest=None):
    root, output = Path(root).resolve(), Path(output).absolute()
    if not isinstance(agent_image_digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", agent_image_digest) is None:
        raise ValueError("agent_image_digest must be a fixed sha256 digest")
    if verifier_image_digest is not None and (
        not isinstance(verifier_image_digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", verifier_image_digest) is None
    ):
        raise ValueError("verifier_image_digest must be a fixed sha256 digest")
    if output.exists() or output.is_symlink():
        raise ValueError("Harbor T2 output must be new")
    patch = _read(root, PATCH)
    if _sha(patch) != T2_PATCH_SHA256:
        raise ValueError("T2 patch bytes differ from the reviewed release")
    if root != Path(__file__).resolve().parents[2]:
        raise ValueError("root must match the checkout running this module and its imported task builder")
    paths = (
        set(CODE_PATHS)
        | set(VERIFIER_SOURCES)
        | {PATCH, FIXTURE, IMAGE_MANIFEST, Path("examples/harbor/prepare_t2_task.py")}
    )
    sources = {p: _read(root, p) for p in sorted(paths)}
    image = json.loads(sources[IMAGE_MANIFEST])
    if image["image_id"] != PARENT_IMAGE or image["python_distribution_version"] != "0.1.3a2":
        raise ValueError("Agent parent image/runtime differs from the reviewed release")
    rows, bundle = build_rows(root, environment_digest=agent_image_digest, patches=[str(root / PATCH)])
    if any(entry["sha256"] != _sha(sources[Path(entry["path"])]) for entry in bundle["files"]):
        raise ValueError("Task builder source changed during preparation")
    selected = [row for row in rows if row["uid"] == "log-tool-dev-01"]
    if len(selected) != 1:
        raise ValueError("Exactly one public dev-01 task is required")
    row = selected[0]
    metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
    if metadata["split"] != "validation" or metadata["fixture_digest"] != _sha(sources[FIXTURE]):
        raise ValueError("dev-01 fixture identity/split differs from the task bundle")
    commit = _git(root, "rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("Source commit is not a full git SHA")
    source_status = _git(root, "status", "--porcelain", "--untracked-files=all", "--", *map(str, sorted(paths)))
    files = {
        "instruction.md": row["prompt"][0]["content"].encode(),
        "environment/evolution.patch.yml": patch,
        "environment/Dockerfile": (
            f"# Before building, inspect {PARENT_TAG} and require image ID {PARENT_IMAGE}.\n"
            "# This local tag has no registry manifest digest; build with --pull=false.\n"
            f"FROM --platform=linux/amd64 {PARENT_TAG}\n"
            f"COPY evolution.patch.yml {T2_PATCH_PATH}\n"
        ).encode(),
        "environment/docker-compose.yaml": b"services:\n  main:\n    platform: linux/amd64\n    network_mode: bridge\n",
        "tests/docker-compose.yaml": b"services:\n  main:\n    platform: linux/amd64\n    network_mode: none\n",
        "tests/fixture.json": sources[FIXTURE],
        "tests/Dockerfile": (
            f"FROM --platform=linux/amd64 {VERIFIER_IMAGE}\n"
            "ENV PYTHONPATH=/opt/t2-verifier PYTHONDONTWRITEBYTECODE=1\n"
            "COPY src/ /opt/t2-verifier/\nCOPY fixture.json /tests/fixture.json\n"
            "COPY test.sh /tests/test.sh\nWORKDIR /app\n"
        ).encode(),
        "tests/test.sh": (
            b"#!/bin/sh\nset -eu\n"
            b"exec python -m examples.harbor.t2_verifier --fixture /tests/fixture.json "
            b"--input-dir /audit-input --output-dir /logs/verifier\n"
        ),
    }
    verifier_pin = f'docker_image = "{verifier_image_digest}"\n' if verifier_image_digest is not None else ""
    files["task.toml"] = (
        'schema_version = "1.3"\nartifacts = []\n\n[agent]\ntimeout_sec = 600.0\n\n'
        f'[environment]\ndocker_image = "{agent_image_digest}"\nbuild_timeout_sec = 120.0\n'
        'cpus = 1\nmemory_mb = 2048\nstorage_mb = 2048\nworkdir = "/app"\n\n'
        '[verifier]\nenvironment_mode = "separate"\ntimeout_sec = 30.0\n\n'
        f"[verifier.environment]\n{verifier_pin}build_timeout_sec = 120.0\ncpus = 1\nmemory_mb = 512\n"
        'storage_mb = 1024\nworkdir = "/app"\n'
    ).encode()
    for path in VERIFIER_SOURCES:
        files["tests/src/" + path.as_posix()] = sources[path]
        for parent in path.parents:
            if parent != Path("."):
                files["tests/src/" + (parent / "__init__.py").as_posix()] = b""
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    task_ref = dict(
        id="t2-log-tool-dev-01",
        version="v1",
        sha256=_sha(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()),
    )
    manifest = dict(
        schema="dsh.harbor-t2-task-package.v1",
        status="prepared-only",
        task_dir=str(output / "task"),
        case_id="log-tool-dev-01",
        evaluation_visibility="public-development-not-hidden",
        task_ref=task_ref,
        source_commit=commit,
        source_status=source_status.splitlines(),
        source_dirty=bool(source_status),
        source_files={str(p): _sha(raw) for p, raw in sources.items()},
        verifier_bundle=bundle,
        agent_image_digest=agent_image_digest,
        agent_parent_image_digest=PARENT_IMAGE,
        agent_parent_local_tag=PARENT_TAG,
        verifier_parent_image=VERIFIER_IMAGE,
        verifier_image_digest=verifier_image_digest,
        platform="linux/amd64",
        runtime={
            k: image[k]
            for k in ("dsh_revision", "python_distribution_version", "runtime_binary_sha256", "runtime_rg_sha256")
        },
        patch=dict(path=T2_PATCH_PATH, sha256=T2_PATCH_SHA256, paths_sha256=_patches_digest((T2_PATCH_PATH,))),
        t2_fixture=dict(
            task_ref=task_ref,
            fixture_path=str(output / "task/tests/fixture.json"),
            fixture_sha256=_sha(sources[FIXTURE]),
        ),
        files={"task/" + name: _sha(raw) for name, raw in files.items()},
        manifest_excludes_self=True,
    )
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, raw in files.items():
        path = output / "task" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    with (output / "manifest.json").open("x") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-image-digest", required=True)
    parser.add_argument("--verifier-image-digest", help="Optional prebuilt verifier sha256 image identity")
    args = parser.parse_args()
    manifest = prepare(
        root=args.root,
        output=args.output,
        agent_image_digest=args.agent_image_digest,
        verifier_image_digest=args.verifier_image_digest,
    )
    print(json.dumps({"task_dir": manifest["task_dir"], "task_ref": manifest["task_ref"]}))


if __name__ == "__main__":
    main()
