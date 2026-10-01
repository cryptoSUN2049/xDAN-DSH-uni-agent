"""Pinned source, argument transport, and owned process deadline contracts."""

import argparse
import hashlib
import json
import os
import subprocess
import sys

import pytest

from examples.mimo_multidomain_rl import launch as module


def arguments(tmp_path, **changes):
    values = {
        "domain": "music",
        "model": tmp_path / "model with spaces;echo unsafe",
        "train": tmp_path / "train.parquet",
        "heldout": tmp_path / "heldout.parquet",
        "run_id": "test-run",
        "steps": 1,
        "run_dir": tmp_path / "run",
        "resume": None,
        "override": [],
        "runtime_seconds": 60,
    }
    values.update(changes)
    return argparse.Namespace(**values)


def cli_fixture(tmp_path, monkeypatch, **changes):
    source = tmp_path / "reference"
    entry = source / "verl/trainer/main_ppo.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("# fixed test source\n")
    monkeypatch.setattr(module, "SOURCE_ENTRY_SHA256", hashlib.sha256(entry.read_bytes()).hexdigest())
    args = arguments(tmp_path, **changes)
    args.train.write_bytes(b"fixed train")
    args.heldout.write_bytes(b"fixed heldout")
    argv = [
        "launch",
        "--domain",
        args.domain,
        "--source",
        str(source),
        "--model",
        str(args.model),
        "--train",
        str(args.train),
        "--heldout",
        str(args.heldout),
        "--run-dir",
        str(args.run_dir),
        "--run-id",
        args.run_id,
        "--runtime-seconds",
        "60",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return args, entry


def test_command_preserves_paths_in_argument_vector(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    monkeypatch.setenv("WANDB_API_KEY", "must-not-appear")
    monkeypatch.setenv("ABC2MIDI_BIN", "/owned tools/abc2midi")
    command = module.command(args)
    model = next(arg.split("=", 1)[1] for arg in command if arg.startswith("actor_rollout_ref.model.path="))
    assert json.loads(model) == str(args.model.resolve())
    assert "must-not-appear" not in repr(command)
    binary = next(arg.split("=", 1)[1] for arg in command if "env_vars.ABC2MIDI_BIN=" in arg)
    assert json.loads(binary) == "/owned tools/abc2midi"
    assert command[0] == sys.executable


def test_nonimplemented_recipe_fails_before_launch(tmp_path, monkeypatch):
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    monkeypatch.setattr(module, "RECIPE", recipes)
    with pytest.raises(ValueError, match="No implemented recipe"):
        module.command(arguments(tmp_path, domain="cyber"))


def test_resume_requires_physical_actor_and_data_checkpoint(tmp_path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    with pytest.raises(ValueError, match="native checkpoint"):
        module.command(arguments(tmp_path, resume=checkpoint))
    (checkpoint / "data.pt").write_bytes(b"native data")
    (checkpoint / "actor").mkdir()
    command = module.command(arguments(tmp_path, resume=checkpoint))
    assert 'trainer.resume_mode="resume_path"' in command
    assert f"trainer.resume_from_path={json.dumps(str(checkpoint.resolve()))}" in command


def test_source_tamper_rejected_before_subprocess(tmp_path, monkeypatch):
    _, entry = cli_fixture(tmp_path, monkeypatch)
    entry.write_text("# changed source\n")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("source mismatch must not spawn"))
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


def test_reused_run_identity_cannot_overwrite_receipt(tmp_path, monkeypatch):
    args, _ = cli_fixture(tmp_path, monkeypatch)
    args.run_dir.mkdir()
    receipt = args.run_dir / "launch-receipt.json"
    receipt.write_text("frozen receipt")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("reused identity must not spawn"))
    with pytest.raises(FileExistsError, match="run identity"):
        module.main()
    assert receipt.read_text() == "frozen receipt"


def test_preflight_composes_source_first_and_never_starts_training(tmp_path, monkeypatch):
    args, _ = cli_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--preflight-only"])
    calls = []

    def compose(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write("resolved: true\n")

    monkeypatch.setattr(module.subprocess, "run", compose)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("preflight must not start training"))
    module.main()
    assert len(calls) == 1
    command, options = calls[0]
    assert command[-3:] == ["--cfg", "job", "--resolve"]
    assert options["env"]["PYTHONPATH"].split(os.pathsep)[0] == str((tmp_path / "reference").resolve())
    assert options["check"] and options["timeout"] == 600
    receipt = json.loads((args.run_dir / "launch-receipt.json").read_text())
    assert receipt["state"] == "preflight"
    assert receipt["train_sha256"] == hashlib.sha256(args.train.read_bytes()).hexdigest()


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="requires POSIX process groups")
def test_deadline_terminates_only_owned_process_group(tmp_path, monkeypatch):
    args, _ = cli_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: None)
    real_popen = subprocess.Popen
    owned = []
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    unrelated = real_popen(sleeper, start_new_session=True)

    class DeadlineProcess:
        def __init__(self, command, **options):
            assert options["start_new_session"] is True
            self.child = real_popen(sleeper, env=options["env"], start_new_session=True)
            self.pid = self.child.pid
            self.first_wait = True
            owned.append(self.child)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.child.wait(timeout=5)

        def wait(self, timeout=None):
            if self.first_wait:
                self.first_wait = False
                assert timeout == 60
                raise subprocess.TimeoutExpired("owned test process", timeout)
            return self.child.wait(timeout=timeout)

    monkeypatch.setattr(module.subprocess, "Popen", DeadlineProcess)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            module.main()
        assert unrelated.poll() is None
        assert owned[0].returncode == -15
        receipt = json.loads((args.run_dir / "launch-receipt.json").read_text())
        assert receipt["state"] == "timeout" and receipt["exit_code"] == 124
        assert "finished_at" in receipt
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
        for child in owned:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
