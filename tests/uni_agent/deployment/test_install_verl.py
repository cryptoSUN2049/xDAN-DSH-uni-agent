"""Exercise bootstrap command ordering without installing packages or using GPUs."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def bootstrap_fixture(tmp_path, *, numpy="2.3.5", check_exit=0):
    repo = tmp_path / "repo"
    script = repo / "deployment/bootstrap/install-verl.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "deployment/bootstrap/install-verl.sh", script)
    # This suite verifies shell ordering; actual Git/patch behavior has its own
    # tests against temporary checkouts in test_verl_source_overlay.py.
    checker = repo / "deployment/checks/verl_source_overlay.py"
    checker.parent.mkdir(parents=True)
    checker.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "with Path(os.environ['COMMANDS']).open('a') as f: f.write(json.dumps(['source-verify',*sys.argv[1:]])+'\\n')\n"
        "assert '--apply' not in sys.argv\n"
        "sys.exit(int(os.environ.get('SOURCE_CHECK_EXIT','0')))\n"
    )
    lock_dir = repo / "deployment/versions"
    lock_dir.mkdir()
    shutil.copyfile(ROOT / "deployment/versions/native-numpy-overlay.txt", lock_dir / "native-numpy-overlay.txt")
    (repo / "verl").mkdir()
    (repo / "verl/uv.lock").write_bytes(b"upstream immutable fixture")
    lock = {
        "integration": {"verl_revision": "fefb080262e1c015a0ea05f958822a6a512dc795"},
        "gpu_python": {
            "verl_uv_lock_sha256": "sha256:" + hashlib.sha256((repo / "verl/uv.lock").read_bytes()).hexdigest(),
            "validated_resolution_adjustment": {"numpy": numpy},
        },
    }
    (lock_dir / "g1-deployment-lock.json").write_text(json.dumps(lock))
    commands = tmp_path / "commands.jsonl"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, source in {
        "uname": "#!/bin/sh\ncase $1 in -s) echo Linux;; -m) echo x86_64;; esac\n",
        "git": "#!/bin/sh\ncase $* in *rev-parse*) echo fefb080262e1c015a0ea05f958822a6a512dc795;; esac\n",
        "uv": f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        "with Path(os.environ['COMMANDS']).open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1:3] == ['pip','check']: sys.exit(int(os.environ['CHECK_EXIT']))\n",
    }.items():
        path = bin_dir / name
        path.write_text(source)
        path.chmod(0o755)
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    fake_python = venv / "bin/python"
    fake_python.write_text(
        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        "if '-c' in sys.argv:\n"
        "    assert '-I' in sys.argv\n"
        "    assert 'PYTHONPATH' not in os.environ\n"
        "    with Path(os.environ['COMMANDS']).open('a') as f:\n"
        "        f.write(json.dumps(['isolated-import',*sys.argv[1:]])+'\\n')\n"
        "else:\n"
        f"    os.execv({sys.executable!r}, [{sys.executable!r},*sys.argv[1:]])\n"
    )
    fake_python.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "DSH_TRAIN_VENV": str(venv),
        "DSH_UV_CACHE": str(tmp_path / "cache"),
        "COMMANDS": str(commands),
        "CHECK_EXIT": str(check_exit),
        "PYTHONPATH": "/old/working/environment",
    }
    return script, env, commands


def test_bootstrap_applies_locked_numpy_then_checks_and_imports(tmp_path):
    script, env, commands = bootstrap_fixture(tmp_path)
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    overlay = next(i for i, args in enumerate(calls) if "--require-hashes" in args)
    check = next(i for i, args in enumerate(calls) if args[:2] == ["pip", "check"])
    assert calls[0][0] == "source-verify"
    assert calls[1] == ["sync", "--frozen", "--extra", "fsdp", "--extra", "vllm"]
    assert "--no-deps" in calls[overlay]
    assert "--only-binary=:all:" in calls[overlay]
    requirement = Path(calls[overlay][-1]).read_text()
    assert "numpy==2.3.5 --hash=sha256:0d8163f43acde9a73c2a33605353a4f1bc4798745a8b1d73183b28e5b435ae28" in requirement
    assert overlay < check < len(calls) - 1
    assert calls[-1][0] == "isolated-import"


def test_incompatible_packages_fail_before_import_gate(tmp_path):
    script, env, commands = bootstrap_fixture(tmp_path, check_exit=17)
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 17
    assert "isolated-import" not in commands.read_text()


def test_post_lock_operations_ignore_project_dependency_overrides(tmp_path):
    script, env, commands = bootstrap_fixture(tmp_path)
    (script.parents[2] / "verl/pyproject.toml").write_text('[tool.uv]\noverride-dependencies = ["numpy>=2.0.0"]\n')
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    pip_calls = [args for args in calls if args[0] == "pip"]
    assert len(pip_calls) == 3
    assert all("--no-config" in args for args in pip_calls)
    # Frozen sync still needs upstream GPU indexes/configuration; isolate only
    # the reviewed post-lock installation and verification operations.
    assert "--no-config" not in calls[1]


@pytest.mark.parametrize("version", ["2.4.6", "", "2.3.5 --extra-index-url untrusted"])
def test_bootstrap_refuses_unapproved_overlay(tmp_path, version):
    script, env, commands = bootstrap_fixture(tmp_path, numpy=version)
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "--require-hashes" not in commands.read_text()


@pytest.mark.parametrize("field", ["verl_revision", "verl_uv_lock_sha256"])
def test_overlay_is_bound_to_source_and_upstream_lock(tmp_path, field):
    script, env, commands = bootstrap_fixture(tmp_path)
    path = script.parents[1] / "versions/g1-deployment-lock.json"
    lock = json.loads(path.read_text())
    lock["integration" if field == "verl_revision" else "gpu_python"][field] = "mismatch"
    path.write_text(json.dumps(lock))
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "--require-hashes" not in commands.read_text()


def test_source_verification_fails_before_any_installation(tmp_path):
    script, env, commands = bootstrap_fixture(tmp_path)
    env["SOURCE_CHECK_EXIT"] = "23"
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 23
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    assert len(calls) == 1 and calls[0][0] == "source-verify"
