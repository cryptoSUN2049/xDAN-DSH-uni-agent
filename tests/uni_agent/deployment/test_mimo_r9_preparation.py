import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
MODULE = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_r9_preparation.py"


def module():
    spec = importlib.util.spec_from_file_location("r9_preparation", MODULE)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def frozen(tmp_path):
    files = {}
    for name in (
        "deployment/services/harbor_run_controller.py",
        "examples/harbor_opd_rl/launch.py",
        "examples/mimo_dsh_rl/mimo-9b-budget-terminal.yaml",
        "verl/verl/workers/engine/fsdp/transformer_impl.py",
    ):
        path = tmp_path / "run-src-r9" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frozen\n")
        files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    manifest = tmp_path / "integration-check/source-r9-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"git_commit": "a" * 40, "files": files}))
    return tmp_path


def checkpoint(root):
    path = root / "runs/r8/rl-training/checkpoints/global_step_2"
    for name in (
        "data.pt",
        "actor/model_world_size_1_rank_0.pt",
        "actor/optim_world_size_1_rank_0.pt",
        "actor/extra_state_world_size_1_rank_0.pt",
    ):
        item = path / name
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(b"checkpoint")
    (path.parent / "latest_checkpointed_iteration.txt").write_text("2\n")
    return path


def test_fresh_has_no_resume_and_absolute_two_steps(frozen):
    m = module()
    result = m.validate_runtime(frozen, "fresh", "a" * 40, m.DEADLINE - 2000)
    assert result["training_flags"] == ["--total-training-steps", "2", "--save-freq", "1"]
    assert result["wall_clock_seconds"] == 1820
    later = m.validate_runtime(frozen, "fresh", "a" * 40, m.DEADLINE - 1000)
    assert later["wall_clock_seconds"] == 820


def test_resume_requires_complete_c2_and_absolute_three_steps(frozen):
    m = module()
    with pytest.raises(ValueError, match="checkpoint"):
        m.validate_runtime(frozen, "resume", "a" * 40, m.DEADLINE - 2000)
    path = checkpoint(frozen)
    result = m.validate_runtime(frozen, "resume", "a" * 40, m.DEADLINE - 2000)
    assert result["training_flags"] == [
        "--total-training-steps",
        "3",
        "--save-freq",
        "1",
        "--resume-from-path",
        str(path),
    ]
    (path / "actor/optim_world_size_1_rank_0.pt").unlink()
    with pytest.raises(ValueError, match="checkpoint"):
        m.validate_runtime(frozen, "resume", "a" * 40, m.DEADLINE - 2000)


@pytest.mark.parametrize("attack", ["mode", "commit", "hash", "traversal", "late", "too-early", "missing-file"])
def test_invalid_freeze_or_window_fails_closed(frozen, attack):
    m = module()
    mode, commit, now = "fresh", "a" * 40, m.DEADLINE - 2000
    manifest = frozen / "integration-check/source-r9-manifest.json"
    raw = json.loads(manifest.read_text())
    if attack == "mode":
        mode = None
    elif attack == "commit":
        commit = "b" * 40
    elif attack == "hash":
        next(iter(raw["files"].values()))["sha256"] = "0" * 64
    elif attack == "traversal":
        raw["files"]["../outside"] = next(iter(raw["files"].values()))
    elif attack == "late":
        now = m.DEADLINE - 779
    elif attack == "too-early":
        now = m.DEADLINE - 18001
    else:
        raw["files"].pop("deployment/services/harbor_run_controller.py")
    manifest.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        m.validate_runtime(frozen, mode, commit, now)


def test_fixed_template_identity_rejects_modified_source(tmp_path):
    m = module()
    templates = {name: "not trusted" for name in m.TEMPLATE_SHA}
    with pytest.raises(ValueError, match="template"):
        m.render_scripts(templates)


def test_stage_generates_reviewable_scripts_without_executing_and_refuses_reuse(tmp_path, monkeypatch, capsys):
    m = module()
    templates = {
        "prepare": """lease = json.loads((private / 'shared-run-window-r8.json').read_text())
assert discovery['id'] == lease['id']
value['deadline_unix'] = lease['deadline_unix'] - 180
gpu_code = '''
print('ready')
'''
command = ['env', 'CUDA_VISIBLE_DEVICES=', 'PYTHONPATH=' + 'run-src-r8']
""",
        "driver": "wall = min(4800, int(spec['deadline_unix'] - time.time() - 180))\n",
        "wrapper": "def native_training_command():\n    return [\n    ]\n",
    }
    monkeypatch.setattr(
        m, "TEMPLATE_SHA", {name: hashlib.sha256(text.encode()).hexdigest() for name, text in templates.items()}
    )
    output = tmp_path / "bundle"
    argv = ["stage", "--output", str(output)]
    for name, text in templates.items():
        path = tmp_path / (name + ".py")
        path.write_text(text)
        argv += ["--" + name + "-template", str(path)]
    monkeypatch.setattr("sys.argv", argv)
    m.main()
    report = json.loads(capsys.readouterr().out)
    assert report["training_started"] is False
    for name, sha in report["files"].items():
        path = output / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
        ast.parse(path.read_text())
    driver = (output / "launch-r9-driver.py").read_text()
    assert "min(4800" not in driver
    assert "spec['deadline_unix'] - time.time() - 180" in driver
    assert "r9_plan['training_flags']" in (output / "mimo-supervised-native-r9.py").read_text()
    with pytest.raises(FileExistsError):
        m.stage(output, templates)


def test_runtime_gate_requires_explicit_environment(frozen, monkeypatch):
    m = module()
    monkeypatch.setattr(m, "ROOT", frozen)
    monkeypatch.setattr("time.time", lambda: m.DEADLINE - 2000)
    monkeypatch.setenv("MIMO_R9_MODE", "fresh")
    monkeypatch.setenv("MIMO_R9_SOURCE_COMMIT", "a" * 40)
    assert m.runtime_gate()["mode"] == "fresh"
    monkeypatch.delenv("MIMO_R9_MODE")
    with pytest.raises(ValueError, match="Explicit mode"):
        m.runtime_gate()


@pytest.mark.parametrize("now", [True, float("nan"), float("inf"), "1790685801"])
def test_invalid_clock_rejected(frozen, now):
    with pytest.raises(ValueError, match="Invalid clock"):
        module().validate_runtime(frozen, "fresh", "a" * 40, now)


@pytest.mark.parametrize("commit", [None, "abc123", "A" * 40, "g" * 40])
def test_full_commit_required(frozen, commit):
    m = module()
    with pytest.raises(ValueError, match="Full commit"):
        m.validate_runtime(frozen, "fresh", commit, m.DEADLINE - 2000)


def test_entropy_implementation_cannot_be_omitted(frozen):
    m = module()
    path = frozen / "integration-check/source-r9-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"].pop("verl/verl/workers/engine/fsdp/transformer_impl.py")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Required source"):
        m.validate_runtime(frozen, "fresh", "a" * 40, m.DEADLINE - 2000)


def test_source_symlink_rejected_even_if_content_matches(frozen):
    m = module()
    path = frozen / "run-src-r9/deployment/services/harbor_run_controller.py"
    target = frozen / "outside.py"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="Invalid frozen source"):
        m.validate_runtime(frozen, "fresh", "a" * 40, m.DEADLINE - 2000)


@pytest.mark.parametrize("latest", ["1", "3", ""])
def test_checkpoint_requires_committed_iteration_two(frozen, latest):
    m = module()
    path = checkpoint(frozen)
    (path.parent / "latest_checkpointed_iteration.txt").write_text(latest)
    with pytest.raises(ValueError, match="Uncommitted"):
        m.validate_runtime(frozen, "resume", "a" * 40, m.DEADLINE - 2000)
