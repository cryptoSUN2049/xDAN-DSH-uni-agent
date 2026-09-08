import json
import shutil
import subprocess
from pathlib import Path

import pytest

from uni_agent.tasks.dsh.memory_artifacts import _sha
from uni_agent.tasks.dsh.rsi_candidates import initialize


def test_node_rsi_policy_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for actual ESM policy tests")
    path = Path(__file__).resolve().parents[3] / "examples/dsh/rsi_closed/policy.test.mjs"
    result = subprocess.run([node, "--test", str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def loaded(tmp_path):
    pins = {
        key: _sha(key.encode())
        for key in ["model_sha256", "runtime_sha256", "base_harness_sha256", "devset_sha256", "verifier_sha256"]
    }
    pins.update(evolution_run_id="rsi-overlay-test", case_ids=["case-a", "case-b"], max_tokens=64)
    spec = {"schema": "dsh.rsi-profile.v1", "profile": "sdk-minimal", "allowed_tools": ["str_replace_editor"]}
    root = tmp_path / "registry"
    identities = initialize(root, spec, pins)
    file = tmp_path / "evidence.txt"
    file.write_text("public evidence")
    return root, identities, file


def test_renderer_pins_selection_policy_and_has_no_probe(loaded):
    from examples.dsh.rsi_closed.profile import POLICY_SHA256, build_patch

    root, ids, file = loaded
    value = build_patch(root, ids["pins_sha256"], ids["active_sha256"], [file])
    assert value["policy_sha256"] == POLICY_SHA256
    assert value["selection"]["candidate_sha256"] == ids["candidate_sha256"]
    serialized = json.dumps(value["patch"])
    assert "probe.mjs" not in serialized
    assert "persistent-bash" in serialized
    assert value["patch"][-1]["insert"][0]["config"]["candidateSha256"] == ids["candidate_sha256"]
    assert value["read_files"][str(file)] == _sha(file.read_bytes())


def test_renderer_rejects_source_pin_or_symlink(loaded, monkeypatch):
    from examples.dsh.rsi_closed import profile

    root, ids, file = loaded
    monkeypatch.setattr(profile, "POLICY_SHA256", _sha(b"wrong"))
    with pytest.raises(ValueError, match="policy source"):
        profile.build_patch(root, ids["pins_sha256"], ids["active_sha256"], [file])


def test_renderer_refuses_unsupported_tool(loaded, tmp_path):
    from examples.dsh.rsi_closed.profile import build_patch

    root, _, file = loaded
    pins = json.loads((root / "pins.json").read_text())
    spec = {"schema": "dsh.rsi-profile.v1", "profile": "sdk-minimal", "allowed_tools": ["cordis_define"]}
    other = tmp_path / "unsupported"
    ids = initialize(other, spec, pins)
    with pytest.raises(ValueError, match="subset"):
        build_patch(other, ids["pins_sha256"], ids["active_sha256"], [file])


def test_renderer_rejects_links_and_stale_selection(loaded, tmp_path):
    import os

    from examples.dsh.rsi_closed.profile import build_patch

    root, ids, file = loaded
    alias = tmp_path / "alias"
    alias.symlink_to(file)
    with pytest.raises((OSError, ValueError)):
        build_patch(root, ids["pins_sha256"], ids["active_sha256"], [alias])
    alias.unlink()
    os.link(file, alias)
    with pytest.raises(ValueError, match="single-link"):
        build_patch(root, ids["pins_sha256"], ids["active_sha256"], [file])
    with pytest.raises(ValueError, match="compare-and-swap"):
        build_patch(root, ids["pins_sha256"], _sha(b"stale"), [file])


def test_renderer_records_fresh_process_selection(loaded):
    import sys

    root, ids, file = loaded
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "examples.dsh.rsi_closed.profile",
            "--registry",
            str(root),
            "--pins-sha256",
            ids["pins_sha256"],
            "--active-sha256",
            ids["active_sha256"],
            "--read-file",
            str(file),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = json.loads(result.stdout)
    assert value["selection"]["candidate_sha256"] == ids["candidate_sha256"]
    assert value["runtime_started"] is False
