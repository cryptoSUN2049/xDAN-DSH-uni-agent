"""Prepare one public given-code email-redaction Harbor task, without running it."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from examples.dsh.prepare_evolution_dataset import _patches_digest, _prompt
from examples.harbor.prepare_t2_task import _git, _read, _sha
from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH, T2_PATCH_SHA256
from uni_agent.tasks.harbor_dsh.evolution_scoring import EVOLUTION_KIND, SOURCES
from uni_agent.tasks.harbor_dsh.evolution_scoring_v2 import EVOLUTION_V2_KIND, SOURCE_HASHES, VERIFIER_BUNDLE_SHA256

PARENT_IMAGE = "sha256:b016c85140a58f7d842eadb0238925ee1c347143cc7bede5b9b35bfa38747dca"
PARENT_TAG = "uni-agent-dsh:t2-log-tool-r1"
RUNTIME_SHA = "sha256:d1a467a9c14a38ad5f01591d2cdb125852cb1a1d3b0ecb678dfde383404e80cb"
PATCH = Path("examples/dsh/evolution.patch.yml")
FIXTURE = Path("examples/dsh/fixtures/evolution-v2/redact-train-01.json")
VERIFIER_SOURCES = (
    "examples/harbor/evolution_verifier.py",
    "uni_agent/tasks/harbor_dsh/evolution_scoring.py",
    "uni_agent/tasks/harbor_dsh/protocol.py",
    *SOURCES,
)


def _json_bytes(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(
    *,
    root,
    source_dir,
    source_manifest_sha256,
    output,
    agent_image_digest,
    verifier_image_digest=None,
    admission_version="v1",
):
    _require(admission_version in ("v1", "v2"), "invalid admission version")
    v2 = admission_version == "v2"
    scoring_sources = tuple("examples/dsh/" + name for name in SOURCE_HASHES) if v2 else SOURCES
    verifier_sources = (
        VERIFIER_SOURCES
        + (
            "examples/harbor/evolution_verifier_v2.py",
            "uni_agent/tasks/harbor_dsh/evolution_scoring_v2.py",
            "examples/dsh/evolution_verifier_v2.py",
        )
        if v2
        else VERIFIER_SOURCES
    )
    root, source_dir, output = Path(root).resolve(), Path(source_dir).resolve(), Path(output).absolute()
    _require(root == Path(__file__).resolve().parents[2], "root must match the imported checkout")
    _require(not output.exists() and not output.is_symlink(), "output must be new")
    _require(not output.resolve().is_relative_to(root), "output must be outside checkout")
    for value in (agent_image_digest, verifier_image_digest):
        _require(
            value is None or isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value),
            "invalid image digest",
        )
    _require(agent_image_digest is not None, "agent image digest required")
    source_raw = _read(source_dir, Path("manifest.json"))
    _require(_sha(source_raw) == source_manifest_sha256, "source manifest SHA mismatch")
    source = json.loads(source_raw)
    _require(
        source["schema"] == ("dsh.redact-curriculum.v2" if v2 else "dsh.evolution-dataset-manifest.v1")
        and (v2 or source["counts"] == {"train": 16, "holdout": 8}),
        "expected version-matched source dataset manifest",
    )
    selected = []
    for split, count in [("train", 4), ("holdout", 2)] if v2 else [("train", 16), ("holdout", 8)]:
        raw = _read(source_dir, Path(split + ".parquet"))
        entry = source["files"][split + ".parquet"]
        _require(_sha(raw) == entry["sha256"], "source parquet SHA mismatch")
        rows = pq.read_table(pa.BufferReader(raw)).to_pylist()
        _require(len(rows) == count == entry["records"], "source parquet count mismatch")
        for index, row in enumerate(rows):
            metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
            if metadata["scenario_id"] == "redact-train-01":
                _require(split == "train" and metadata["split"] == "train", "fixed scenario split mismatch")
                selected.append((index, row))
    _require(len(selected) == 1, "exactly one redact-train-01 required")
    index, row = selected[0]
    metadata = row["extra_info"]["tools_kwargs"]["task"]["metadata"]
    source_task = source["task"]
    _require(
        source_task["task_name"] == "dsh_architecture"
        and source_task["profile"] == "sdk-minimal"
        and source_task["patches"] == [str(PATCH)]
        and source_task["environment_digest"] == RUNTIME_SHA,
        "source runtime/patch configuration mismatch",
    )
    paths = {Path(p) for p in verifier_sources} | {
        PATCH,
        FIXTURE,
        Path("examples/dsh/prepare_evolution_dataset.py"),
        Path("examples/harbor/prepare_evolution_task.py"),
    }
    sources = {p: _read(root, p) for p in sorted(paths)}
    _require(_sha(sources[PATCH]) == T2_PATCH_SHA256, "patch bytes mismatch")
    fixture_raw = sources[FIXTURE]
    _require(
        source["fixtures"]["redact-train-01"] == {"path": str(FIXTURE), "sha256": _sha(fixture_raw)}
        and metadata["fixture_path"] == str(FIXTURE)
        and metadata["fixture_digest"] == _sha(fixture_raw),
        "fixture identity mismatch",
    )
    _require(
        metadata["operation"] == "redact_email"
        and row["extra_info"]["tools_kwargs"]["task"]["name"] == "dsh_architecture",
        "fixed operation/task mismatch",
    )
    for key in ["environment_digest", "profile", "verifier_id", "verifier_version", "verifier_code_digest"]:
        _require(metadata[key] == source_task[key], "source metadata identity mismatch: " + key)
    _require(
        metadata["verifier_code_digest"] == (VERIFIER_BUNDLE_SHA256 if v2 else _sha(sources[Path(SOURCES[0])]))
        and metadata["verifier_id"] == "dsh-harness-evolution-verifier"
        and metadata["verifier_version"] == ("2" if v2 else "1")
        and metadata["task_version"] == ("2" if v2 else "1")
        and metadata["patches_sha256"] == _patches_digest([str(PATCH)]),
        "source scorer/patch digest mismatch",
    )
    if v2:
        _require(source.get("verifier_sources") == SOURCE_HASHES, "source verifier map mismatch")
        _require(
            all(
                _sha(sources[Path("examples/dsh/" + name)]) == "sha256:" + value
                for name, value in SOURCE_HASHES.items()
            ),
            "source verifier bytes mismatch",
        )
    fixture = json.loads(fixture_raw)
    _require(
        fixture.get("operation") == "redact_email" and isinstance(fixture.get("input"), str), "invalid email fixture"
    )
    original_prompt = _prompt(
        fixture_path=str(root / FIXTURE), candidate_tool_name=metadata["candidate_tool_name"], operation="redact_email"
    )
    _require(row["prompt"] == original_prompt, "source prompt differs from original fixed implementation")
    instruction = original_prompt[0]["content"].replace(str(root / FIXTURE), "/app/fixture.json")
    deployed = {**metadata, "fixture_path": "/app/fixture.json", "patches_sha256": _patches_digest([T2_PATCH_PATH])}
    metadata_raw = _json_bytes(deployed)
    marker = dict(
        kind=EVOLUTION_V2_KIND if v2 else EVOLUTION_KIND,
        fixture_sha256=_sha(fixture_raw),
        metadata_sha256=_sha(metadata_raw),
        source_sha256s={p: _sha(sources[Path(p)]) for p in scoring_sources},
    )
    if v2:
        marker["verifier_bundle_sha256"] = VERIFIER_BUNDLE_SHA256
    parent = (
        f"# Require docker inspect {PARENT_TAG} image ID {PARENT_IMAGE}; build --pull=false.\n"
        f"FROM --platform=linux/amd64 {PARENT_TAG}\n"
    )
    files = {
        "instruction.md": instruction.encode(),
        "evolution.json": _json_bytes(marker),
        "environment/evolution.patch.yml": sources[PATCH],
        "environment/fixture.json": fixture_raw,
        "environment/Dockerfile": (
            parent + "COPY fixture.json /app/fixture.json\nRUN chmod 0444 /app/fixture.json\n"
        ).encode(),
        "environment/docker-compose.yaml": b"services:\n  main:\n    platform: linux/amd64\n    network_mode: bridge\n",
        "tests/docker-compose.yaml": b"services:\n  main:\n    platform: linux/amd64\n    network_mode: none\n",
        "tests/fixture.json": fixture_raw,
        "tests/metadata.json": metadata_raw,
        "tests/Dockerfile": (
            parent + "ENV PYTHONPATH=/opt/evolution-verifier PYTHONDONTWRITEBYTECODE=1\n"
            "COPY src/ /opt/evolution-verifier/\nCOPY fixture.json /tests/fixture.json\n"
            "COPY metadata.json /tests/metadata.json\nCOPY test.sh /tests/test.sh\nWORKDIR /app\n"
        ).encode(),
        "tests/test.sh": (
            b"#!/bin/sh\nset -eu\nexec python -m examples.harbor.evolution_verifier "
            b"--input-dir /audit-input --output-dir /logs/verifier\n"
        ),
    }
    if v2:
        files["tests/test.sh"] = files["tests/test.sh"].replace(
            b"examples.harbor.evolution_verifier ", b"examples.harbor.evolution_verifier_v2 "
        )
    verifier_pin = f'docker_image = "{verifier_image_digest}"\n' if verifier_image_digest else ""
    files["task.toml"] = (
        'schema_version = "1.3"\nartifacts = []\n\n[agent]\ntimeout_sec = 600.0\n\n'
        f'[environment]\ndocker_image = "{agent_image_digest}"\nbuild_timeout_sec = 120.0\n'
        'cpus = 1\nmemory_mb = 2048\nstorage_mb = 2048\nworkdir = "/app"\n\n'
        '[verifier]\nenvironment_mode = "separate"\ntimeout_sec = 30.0\n\n'
        f"[verifier.environment]\n{verifier_pin}build_timeout_sec = 120.0\n"
        'cpus = 1\nmemory_mb = 512\nstorage_mb = 1024\nworkdir = "/app"\n'
    ).encode()
    for name in verifier_sources:
        path = Path(name)
        files["tests/src/" + name] = sources[path]
        for parent_path in path.parents:
            if parent_path != Path("."):
                files["tests/src/" + str(parent_path / "__init__.py")] = b""
    task_ref = dict(
        id="evolution-redact-train-01",
        version="v2" if v2 else "v1",
        sha256=_sha(
            json.dumps(
                {name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ),
    )
    status = _git(root, "status", "--porcelain", "--untracked-files=all", "--", *map(str, sorted(paths)))
    result = dict(
        schema="dsh.harbor-evolution-task-package.v1",
        status="prepared-only",
        task_dir=str(output / "task"),
        task_ref=task_ref,
        scenario_id="redact-train-01",
        evaluation_visibility="single-public-training-case-engineering-only",
        hidden_inputs_verified=False,
        source_manifest_sha256=source_manifest_sha256,
        source_files=source["files"],
        source_row_index=index,
        original_row=row,
        original_metadata_sha256=_sha(_json_bytes(metadata)),
        deployment_metadata_changes={
            k: {"original": metadata[k], "deployed": v} for k, v in deployed.items() if metadata.get(k) != v
        },
        source_commit=_git(root, "rev-parse", "HEAD"),
        source_dirty=bool(status),
        source_status=status.splitlines(),
        source_code_files={str(p): _sha(raw) for p, raw in sources.items()},
        agent_parent_local_tag=PARENT_TAG,
        agent_parent_image_digest=PARENT_IMAGE,
        verifier_parent_image_digest=PARENT_IMAGE,
        agent_image_digest=agent_image_digest,
        verifier_image_digest=verifier_image_digest,
        runtime_sha256=RUNTIME_SHA,
        evolution_binding={
            **marker,
            "task_ref": task_ref,
            "fixture_path": str(output / "task/tests/fixture.json"),
            "metadata_path": str(output / "task/tests/metadata.json"),
        },
        files={"task/" + name: _sha(value) for name, value in files.items()},
        manifest_excludes_self=True,
    )
    if v2:
        result["schema"] = "dsh.harbor-evolution-task-package.v2"
        result["evolution_v2_binding"] = result.pop("evolution_binding")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, value in {**{"task/" + k: v for k, v in files.items()}, "manifest.json": _json_bytes(result)}.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(value)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ["root", "source-dir", "output"]:
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--agent-image-digest", required=True)
    parser.add_argument("--verifier-image-digest")
    parser.add_argument("--admission-version", choices=("v1", "v2"), default="v1")
    result = prepare(**vars(parser.parse_args()))
    print(json.dumps({"task_dir": result["task_dir"], "task_ref": result["task_ref"]}))


if __name__ == "__main__":
    main()
