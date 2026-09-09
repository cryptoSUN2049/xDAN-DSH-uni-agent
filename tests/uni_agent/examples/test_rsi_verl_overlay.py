"""Use real temporary Git sources to exercise the RSI source gate without GPUs."""

import subprocess

import pytest

from deployment.checks import verl_source_overlay as overlay
from examples.dsh.rsi_closed import prepare_worker_eval as prep
from tests.uni_agent.examples.test_verl_source_overlay import checkout  # noqa: F401


@pytest.fixture
def rsi_checkout(request, monkeypatch):
    repo = request.getfixturevalue("checkout")
    root = repo.parent
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / "source.py").write_text("# committed integration source\n")
    subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(prep, "ROOT", root)
    monkeypatch.setattr(prep, "SOURCES", ["source.py"])
    overlay.apply_verl_source(repo)
    return repo


def test_rsi_gate_accepts_only_exact_authorized_overlay(rsi_checkout):
    prep.require_clean_sources()
    assert prep.verl_source_identity() == overlay.verify_verl_source(rsi_checkout)


@pytest.mark.parametrize("fault", ["target", "untracked", "uv-lock", "staged", "integration"])
def test_rsi_gate_rejects_unknown_changes(rsi_checkout, fault):
    path = rsi_checkout / overlay.TARGET
    if fault == "untracked":
        (rsi_checkout / "unexpected.py").write_text("unknown")
    elif fault == "uv-lock":
        (rsi_checkout / "uv.lock").write_text("changed")
    elif fault == "staged":
        subprocess.run(["git", "-C", str(rsi_checkout), "add", overlay.TARGET], check=True)
    elif fault == "integration":
        (rsi_checkout.parent / "source.py").write_text("changed")
    else:
        path.write_text(path.read_text() + "\n# unknown\n")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        prep.require_clean_sources()
    assert path.read_bytes() == before
