"""Real git repositories prove hidden-test reset, grading, and failure separation."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from examples.mimo_dsh_rl.verifier import VerificationError, freeze_baseline, verify

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
PATCH = (
    "diff --git a/hidden.sh b/hidden.sh\nnew file mode 100755\n--- /dev/null\n+++ b/hidden.sh\n"
    '@@ -0,0 +1,2 @@\n+#!/bin/sh\n+test "$(cat answer.txt)" = correct\n'
)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True).stdout.strip()


def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "answer.txt").write_text("wrong")
    return repo, freeze_baseline(repo)


def grade(repo, base, **overrides):
    return verify(cwd=repo, base_ref=base, test_patch=PATCH, test_command="bash hidden.sh", timeout=5, **overrides)


def test_actual_failure_then_correct_edit_produces_distinct_rewards(tmp_path):
    repo, base = repository(tmp_path)
    assert grade(repo, base)["reward"] == 0.0
    assert not (repo / "hidden.sh").exists()
    (repo / "answer.txt").write_text("correct")
    result = grade(repo, base)
    assert result["reward"] == 1.0 and result["verifier_returncode"] == 0
    assert (repo / "answer.txt").read_text() == "correct"
    assert not (repo / "hidden.sh").exists()


@pytest.mark.parametrize("timeout", [5, 5.0])
def test_numeric_timeout_types_keep_completed_failure_as_zero_reward(tmp_path, timeout):
    repo, base = repository(tmp_path)
    result = verify(cwd=repo, base_ref=base, test_patch=PATCH, test_command="bash hidden.sh", timeout=timeout)
    assert result["status"] == "graded" and result["reward"] == 0.0
    assert not (repo / "hidden.sh").exists()


@pytest.mark.parametrize("timeout", [True, False, "5", None, 0, -1])
def test_invalid_timeout_remains_infrastructure_error_before_hidden_tests(tmp_path, timeout):
    repo, base = repository(tmp_path)
    with pytest.raises(VerificationError, match="invalid_verifier_config"):
        verify(cwd=repo, base_ref=base, test_patch=PATCH, test_command="bash hidden.sh", timeout=timeout)
    assert not (repo / "hidden.sh").exists()
    assert (repo / "answer.txt").read_text() == "wrong"


def test_agent_cannot_override_test_by_precreating_or_committing_it(tmp_path):
    repo, base = repository(tmp_path)
    (repo / "hidden.sh").write_text("exit 0\n")
    git(repo, "add", "hidden.sh")
    git(repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "agent commit")
    assert grade(repo, base)["reward"] == 0.0
    assert not (repo / "hidden.sh").exists()


def test_modified_existing_test_resets_to_frozen_base_not_agent_head(tmp_path):
    repo, base = repository(tmp_path)
    (repo / "existing.sh").write_text("exit 1\n")
    git(repo, "add", "existing.sh")
    git(repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial tests")
    base = freeze_baseline(repo)
    (repo / "existing.sh").write_text("exit 0\n")
    patch = (
        "diff --git a/existing.sh b/existing.sh\n--- a/existing.sh\n+++ b/existing.sh\n"
        '@@ -1 +1 @@\n-exit 1\n+test "$(cat answer.txt)" = correct\n'
    )
    result = verify(cwd=repo, base_ref=base, test_patch=patch, test_command="bash existing.sh", timeout=5)
    assert result["reward"] == 0
    assert (repo / "existing.sh").read_text() == "exit 1\n"


def test_bad_patch_is_infrastructure_error_without_model_reward(tmp_path):
    repo, base = repository(tmp_path)
    patch = "diff --git a/answer.txt b/answer.txt\n--- a/answer.txt\n+++ b/answer.txt\n@@ -1 +1 @@\n-absent\n+correct\n"
    with pytest.raises(VerificationError, match="apply_test_patch_failed"):
        verify(cwd=repo, base_ref=base, test_patch=patch, test_command="true", timeout=5)


def test_timeout_is_not_a_wrong_model_answer(tmp_path):
    repo, base = repository(tmp_path)
    with pytest.raises(VerificationError, match="timeout"):
        verify(cwd=repo, base_ref=base, test_patch=PATCH, test_command="sleep 10", timeout=0.05)
    assert not (repo / "hidden.sh").exists()


def test_patch_path_escape_is_rejected_without_touching_outside(tmp_path):
    repo, base = repository(tmp_path)
    patch = PATCH.replace("a/hidden.sh", "a/../outside").replace("b/hidden.sh", "b/../outside")
    with pytest.raises(VerificationError, match="patch_path"):
        verify(cwd=repo, base_ref=base, test_patch=patch, test_command="true", timeout=5)
    assert not (tmp_path / "outside").exists()


def test_future_history_reference_rejected_before_agent(tmp_path):
    repo, base = repository(tmp_path)
    (repo / "answer.txt").write_text("correct")
    git(repo, "add", "answer.txt")
    git(repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "secret answer")
    git(repo, "tag", "answer")
    git(repo, "checkout", "--detach", base)
    with pytest.raises(VerificationError, match="history"):
        freeze_baseline(repo)


def test_standalone_receipt_binds_operator_snapshot_and_session(tmp_path):
    from examples.mimo_dsh_rl.prepare_tasks import sha256

    repo, base = repository(tmp_path)
    config = tmp_path / "verification.json"
    config.write_text(
        json.dumps(
            {
                "cwd": str(repo),
                "test_command": "bash hidden.sh",
                "verifier_timeout_sec": 5,
                "test_patch_sha256": sha256(PATCH.encode()),
            }
        )
    )
    patch = tmp_path / "test.patch"
    patch.write_text(PATCH)
    state = tmp_path / "mimo-state.json"
    state.write_text(
        json.dumps(
            {
                "cwd": str(repo),
                "base_ref": base,
                "snapshot_sha256": "sha256:" + "a" * 64,
                "gateway_session_id": "session-one",
            }
        )
    )
    out = tmp_path / "logs"
    script = Path(__file__).resolve().parents[3] / "examples/mimo_dsh_rl/verifier.py"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(script),
            "--config",
            str(config),
            "--patch",
            str(patch),
            "--base-ref-file",
            str(state),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads((out / "mimo-receipt.json").read_text())
    assert receipt["status"] == "graded"
    assert receipt["base_ref"] == base and receipt["gateway_session_id"] == "session-one"
    assert receipt["snapshot_sha256"] == "sha256:" + "a" * 64
    assert json.loads((out / "reward.json").read_text()) == {"reward": 0.0}


def test_diff_hunk_contents_are_not_misread_as_file_headers():
    from examples.mimo_dsh_rl.verifier import patch_paths

    patch = (
        "diff --git a/text.txt b/text.txt\n--- a/text.txt\n+++ b/text.txt\n"
        "@@ -1 +1 @@\n--- previous title\n+++ next title\n"
    )
    assert patch_paths(patch) == ["text.txt"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_cli_never_leaves_stale_model_reward_on_infrastructure_failure(tmp_path, monkeypatch, corrupt):
    from examples.mimo_dsh_rl.prepare_tasks import sha256
    from examples.mimo_dsh_rl.verifier import main

    repo, base = repository(tmp_path)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "cwd": str(repo),
                "test_command": "bash hidden.sh",
                "verifier_timeout_sec": 5,
                "test_patch_sha256": sha256(PATCH.encode()),
            }
        )
    )
    patch = tmp_path / "test.patch"
    patch.write_text(PATCH + ("corrupted" if corrupt else ""))
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "cwd": str(repo),
                "base_ref": base,
                "snapshot_sha256": "sha256:" + "a" * 64,
                "gateway_session_id": "test-session",
            }
        )
    )
    output = tmp_path / "logs"
    output.mkdir()
    (output / "reward.json").write_text('{"reward": 1.0}')
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verifier",
            "--config",
            str(config),
            "--patch",
            str(patch),
            "--base-ref-file",
            str(state),
            "--output-dir",
            str(output),
        ],
    )
    code = main()
    receipt = json.loads((output / "mimo-receipt.json").read_text())
    if corrupt:
        assert code == 2 and receipt["status"] == "infra_error"
        assert "digest_mismatch" in receipt["error"]
        assert "reward" not in receipt and not (output / "reward.json").exists()
    else:
        assert code == 0 and receipt["status"] == "graded"
        assert json.loads((output / "reward.json").read_text()) == {"reward": 0.0}
    assert receipt["base_ref"] == base and receipt["gateway_session_id"] == "test-session"


def test_patch_parent_symlink_cannot_escape_workspace(tmp_path):
    repo, base = repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "hidden").symlink_to(outside, target_is_directory=True)
    patch = PATCH.replace("a/hidden.sh", "a/hidden/test.sh").replace("b/hidden.sh", "b/hidden/test.sh")
    with pytest.raises(VerificationError, match="symlink parent"):
        verify(cwd=repo, base_ref=base, test_patch=patch, test_command="true", timeout=5)
    assert not list(outside.iterdir())


def test_traditional_multifile_diff_resets_every_path(tmp_path):
    from examples.mimo_dsh_rl.verifier import patch_paths

    repo, base = repository(tmp_path)
    patch = (
        "--- /dev/null\n+++ b/first.sh\n@@ -0,0 +1 @@\n+exit 1\n"
        "--- /dev/null\n+++ b/second.sh\n@@ -0,0 +1 @@\n+exit 0\n"
    )
    assert patch_paths(patch) == ["first.sh", "second.sh"]
    (repo / "second.sh").write_text("exit 99\n")
    result = verify(cwd=repo, base_ref=base, test_patch=patch, test_command="bash second.sh", timeout=5)
    assert result["reward"] == 1.0
    assert not (repo / "first.sh").exists() and not (repo / "second.sh").exists()


@pytest.mark.parametrize("name", ["fixture.bin", "fixture with space.bin", "fixture-\u00e9.bin"])
def test_binary_patch_reset_and_apply_preserves_exact_bytes(tmp_path, name):
    from examples.mimo_dsh_rl.verifier import patch_paths

    repo, base = repository(tmp_path)
    fixture = repo / name
    fixture.write_bytes(bytes(range(256)))
    git(repo, "add", "--intent-to-add", "--", name)
    patch = subprocess.run(
        ["git", "-C", str(repo), "diff", "--binary", "--no-ext-diff"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "GIT binary patch" in patch
    assert patch_paths(patch) == [name]
    git(repo, "reset", "-q", base, "--", name)
    fixture.write_bytes(b"agent-precreated-content")
    command = (
        f"python3 -c 'from pathlib import Path; assert Path({json.dumps(name)}).read_bytes() == bytes(range(256))'"
    )
    result = verify(cwd=repo, base_ref=base, test_patch=patch, test_command=command, timeout=5)
    assert result["reward"] == 1.0
    assert not fixture.exists()


@pytest.mark.parametrize("name", ["../escape", ".git/config", "dir/../../escape", "/etc/passwd", "nul\x00path"])
def test_binary_only_unsafe_patch_paths_are_rejected(name):
    from examples.mimo_dsh_rl.verifier import patch_paths

    patch = f"diff --git a/{name} b/{name}\nnew file mode 100644\nGIT binary patch\nliteral 1\nA\n"
    with pytest.raises(VerificationError, match="patch_path"):
        patch_paths(patch)


def test_rename_only_patch_collects_old_and_new_paths():
    from examples.mimo_dsh_rl.verifier import patch_paths

    patch = "diff --git a/old.txt b/new.txt\nsimilarity index 100%\nrename from old.txt\nrename to new.txt\n"
    assert patch_paths(patch) == ["new.txt", "old.txt"]


def test_git_default_strip_accepts_nonstandard_source_prefix_without_rewriting(tmp_path):
    from examples.mimo_dsh_rl.verifier import patch_paths

    repo, base = repository(tmp_path)
    patch = PATCH.replace("diff --git a/hidden.sh", "diff --git ab/hidden.sh")
    assert patch_paths(patch) == ["hidden.sh"]
    result = verify(cwd=repo, base_ref=base, test_patch=patch, test_command="bash hidden.sh", timeout=5)
    assert result["reward"] == 0.0
