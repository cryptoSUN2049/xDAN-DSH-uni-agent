"""CPU checks for the trusted memory profile and its executable policy contract."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from examples.dsh.memory_closed.profile import build_memory_patch


def test_closed_profile_uses_only_policy_overlay_and_disables_shell(tmp_path):
    patch = build_memory_patch(
        role="reader",
        chain_id="chain",
        session_id="B",
        source_version="pinned",
        read_files=[tmp_path / "handoff"],
        write_file=None,
    )
    assert patch[:2] == [
        {"id": "persistent-bash", "disabled": True},
        {"id": "persistent-pwsh", "disabled": True},
    ]
    plugin = patch[2]["insert"][0]
    assert plugin["name"].startswith("file:")
    assert plugin["config"]["writeFile"] is None
    assert plugin["config"]["readFiles"] == [str(tmp_path / "handoff")]
    assert "probe" not in json.dumps(patch)
    assert "cordis-host-runner" not in json.dumps(patch)


def test_node_policy_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required to execute runtime policy tests")
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [node, "--test", str(root / "examples/dsh/memory_closed/policy.test.mjs")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
