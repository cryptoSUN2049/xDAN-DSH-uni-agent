"""Prepare private M2 data/config from a frozen controller spec; never launch GPU work."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import tomllib
import yaml

from deployment.services.harbor_run_controller import RunSpec, digest
from uni_agent.agents.dsh.harbor_release import release_patch_paths
from uni_agent.tasks.harbor_dsh.evolution_scoring import EvolutionBinding, load_evolution_binding
from uni_agent.tasks.harbor_dsh.protocol import DshRelease, TaskRef
from uni_agent.tasks.harbor_dsh.registration import _token
from uni_agent.tasks.harbor_dsh.task import T2FixtureBinding, _fixture_lane, _json, load_t2_fixture

EVALUATION_SCOPE = "same-task-engineering-evaluation-not-generalization"


def task_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Task directory must be a real directory")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Frozen task may not contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Frozen task contains a non-regular file")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest(files)


def _outside_repo(path: Path):
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any((parent / ".git").exists() for parent in path.resolve().parents)
    ):
        raise ValueError("Private output path must be absolute and outside the repository")


def _write(path: Path, raw: bytes):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)


def _rows(
    instruction: str,
    run_id: str,
    split: str,
    count: int,
    *,
    task_id: str = "m2-file-write",
    fixture: dict | None = None,
):
    return [
        {
            "uid": f"{run_id}-{split}-{index}",
            "agent_name": "task",
            "data_source": f"harbor/{task_id}/{split}",
            "prompt": [{"role": "user", "content": instruction}],
            "extra_info": {
                "index": index,
                "split": split,
                "evaluation_scope": EVALUATION_SCOPE,
                **(
                    {"public_fixture_case_id": fixture["case_id"], "public_fixture_split": fixture["split"]}
                    if fixture
                    else {}
                ),
                "sample_id": f"{run_id}-{split}-{index}",
                "tools_kwargs": {"task": {"name": "harbor_dsh"}},
            },
        }
        for index in range(count)
    ]


def prepare_training(
    *,
    run_spec_path: Path,
    task_dir: Path,
    output_dir: Path,
    task_config_path: Path,
    registration_token_file: Path,
    worker_token_file: Path,
    train_count: int = 2,
    heldout_count: int = 1,
    t2_fixture_binding: Path | None = None,
    evolution_binding: Path | None = None,
) -> Path:
    """Spec paths remain Mac-owned; task/credential/output paths refer to this host."""
    for count in (train_count, heldout_count):
        if type(count) is not int or not 1 <= count <= 16:
            raise ValueError("Engineering dataset counts must be between one and sixteen")
    for path in (output_dir, task_config_path):
        _outside_repo(path)
    if task_config_path.parent.resolve() != output_dir.resolve():
        raise ValueError("Task YAML must be inside the private output directory")
    spec = RunSpec.model_validate_json(run_spec_path.read_bytes())
    template = spec.policy_template
    refs = template["task_refs"]
    if len(refs) != 1 or task_digest(task_dir) != refs[0]["sha256"]:
        raise ValueError("Expected the one frozen task directory from the run spec")
    manifest = tomllib.loads((task_dir / "task.toml").read_text())
    if manifest.get("environment", {}).get("docker_image") != template["dsh_release"]["image_digest"]:
        raise ValueError("Current task image differs from the frozen DSH release")
    release = DshRelease.model_validate(template["dsh_release"])
    if t2_fixture_binding is not None and evolution_binding is not None:
        raise ValueError("T2 and evolution bindings are mutually exclusive")
    t2 = t2_fixture_binding is not None
    if bool(release_patch_paths(release)) != (t2 or evolution_binding is not None):
        raise ValueError("T2 requires an explicit operator fixture binding; empty release must omit it")
    binding = None
    fixture = None
    if t2:
        binding = T2FixtureBinding.model_validate(_json(t2_fixture_binding.read_bytes()))
        expected_path = (task_dir / "tests" / "fixture.json").resolve(strict=True)
        if Path(binding.fixture_path).resolve(strict=True) != expected_path:
            raise ValueError("T2 binding must use the frozen task's tests/fixture.json")
        frozen = load_t2_fixture(binding, TaskRef.model_validate(refs[0]))
        if frozen.raw != expected_path.read_bytes():
            raise ValueError("T2 fixture bytes differ from frozen task")
        fixture = _json(frozen.raw)
    evolution = None
    if evolution_binding is not None:
        evolution = EvolutionBinding.model_validate(_json(evolution_binding.read_bytes()))
        for field, filename in (("fixture_path", "fixture.json"), ("metadata_path", "metadata.json")):
            if Path(getattr(evolution, field)).resolve(strict=True) != (task_dir / "tests" / filename).resolve(
                strict=True
            ):
                raise ValueError("Evolution binding must use frozen task tests files")
        descriptor = {
            key: evolution.model_dump(mode="json")[key]
            for key in ("kind", "fixture_sha256", "metadata_sha256", "source_sha256s")
        }
        if _json((task_dir / "evolution.json").read_bytes()) != descriptor:
            raise ValueError("Evolution descriptor differs from operator binding")
        frozen_evolution = load_evolution_binding(
            evolution, TaskRef.model_validate(refs[0]), repository_root=Path(__file__).resolve().parents[2]
        )
        _fixture_lane(release, TaskRef.model_validate(refs[0]), None, frozen_evolution)
        metadata = _json(frozen_evolution.metadata_raw)
        fixture = {"case_id": metadata["scenario_id"], "split": metadata["split"]}
    instruction = (task_dir / "instruction.md").read_text()
    if not instruction.strip():
        raise ValueError("Frozen task instruction is empty")
    _token(str(registration_token_file))
    worker_token = _token(str(worker_token_file))
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    actual = output_dir.lstat()
    if not stat.S_ISDIR(actual.st_mode) or actual.st_uid != os.getuid() or stat.S_IMODE(actual.st_mode) != 0o700:
        raise ValueError(
            "Output filesystem did not enforce private owner permissions; use a permissions-capable local path"
        )
    task_config = {
        "name": "harbor_dsh",
        "run_id": spec.run_id,
        "task_ref": refs[0],
        "policy": template,
        "worker_url": f"http://127.0.0.1:{spec.remote_worker_port}",
        "worker_token": worker_token,
        "worker_id": spec.worker_id,
        "artifact_root": str(output_dir / "artifacts"),
        "instruction": instruction,
    }
    if binding is not None:
        task_config["t2_fixture"] = binding.model_dump(mode="json")
    if evolution is not None:
        task_config["evolution_binding"] = evolution.model_dump(mode="json")
    _write(task_config_path, yaml.safe_dump(task_config, allow_unicode=True, sort_keys=True).encode())
    for split, count in (("train", train_count), ("heldout", heldout_count)):
        path = output_dir / f"{split}.parquet"
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            pq.write_table(
                pa.Table.from_pylist(
                    _rows(
                        instruction,
                        spec.run_id,
                        split,
                        count,
                        task_id=refs[0]["id"] if t2 or evolution is not None else "m2-file-write",
                        fixture=fixture,
                    )
                ),
                output,
            )
    registration = {
        "controller_url": f"http://127.0.0.1:{spec.remote_control_port}",
        "token_file": str(registration_token_file),
        "registration_root": str(output_dir / "registrations"),
        "controller_id": spec.controller_id,
        "run_spec_sha256": digest(spec.model_dump(mode="json")),
        "timeout_seconds": 30.0,
    }
    launch = {
        "schema": "dsh.harbor-m2-launch.v1",
        "evaluation_scope": EVALUATION_SCOPE,
        "environment": {
            "TRAIN_FILE": str(output_dir / "train.parquet"),
            "TEST_FILE": str(output_dir / "heldout.parquet"),
            "TASK_CONFIG": str(task_config_path),
            "RUN_ROOT": str(output_dir),
            "PROJECT_NAME": "harbor-evolution-engineering"
            if evolution is not None
            else ("harbor-t2-engineering" if t2 else "harbor-m2-engineering"),
            "EXP_NAME": spec.run_id,
            "MODEL_ID": template["model_name"],
            "TRAIN_MAX_SAMPLES": str(train_count),
            "VAL_MAX_SAMPLES": str(heldout_count),
        },
        "registration": registration,
        "postprocessor": {
            "artifact_root": str(output_dir / "artifacts"),
            "run_id": spec.run_id,
            "worker_id": spec.worker_id,
            "task_ref": refs[0],
            "instruction": instruction,
            "policy_template": template,
            "registration_root": registration["registration_root"],
            "controller_id": spec.controller_id,
            "run_spec_sha256": registration["run_spec_sha256"],
        },
    }
    if binding is not None:
        launch["postprocessor"]["t2_fixture"] = binding.model_dump(mode="json")
    if evolution is not None:
        launch["postprocessor"]["evolution_binding"] = evolution.model_dump(mode="json")
    path = output_dir / "launch.json"
    _write(path, (json.dumps(launch, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "run-spec-path",
        "task-dir",
        "output-dir",
        "task-config-path",
        "registration-token-file",
        "worker-token-file",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--t2-fixture-binding", type=Path, help="Operator T2FixtureBinding JSON bound to this frozen task"
    )
    parser.add_argument(
        "--evolution-binding", type=Path, help="Operator EvolutionBinding JSON bound to this frozen task"
    )
    parser.add_argument("--train-count", type=int, default=2)
    parser.add_argument("--heldout-count", type=int, default=1)
    args = parser.parse_args()
    print(prepare_training(**vars(args)))


if __name__ == "__main__":
    main()
