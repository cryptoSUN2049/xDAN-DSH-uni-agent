import json

import pytest

from examples.dsh.ops import write_run_manifest as writer


def test_run_manifest_binds_verified_overlay(tmp_path, monkeypatch):
    identity = {"overlay_id": "tested-overlay", "state": "patched"}
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"verl_effective_source": identity}))
    repo = tmp_path / "verl"
    observed = []

    def actual(path):
        observed.append(path)
        return identity, str(repo / "verl/__init__.py")

    monkeypatch.setattr(writer, "_actual_verl_identity", actual, raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "manifest",
            "--run-root",
            str(tmp_path / "run"),
            "--status",
            "prepared",
            "--dataset-manifest",
            str(dataset),
            "--verl-root",
            str(repo),
        ],
    )
    writer.main()
    result = json.loads((tmp_path / "run/run-manifest.json").read_text())
    assert result["verl_effective_source"] == identity
    assert result["verl_import_source"] == str(repo / "verl/__init__.py")
    assert observed == [repo]


def test_run_manifest_rejects_overlay_claim_mismatch(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"verl_effective_source": {"overlay_id": "claimed"}}))
    monkeypatch.setattr(
        writer, "_actual_verl_identity", lambda p: ({"overlay_id": "actual"}, "actual.py"), raising=False
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "manifest",
            "--run-root",
            str(tmp_path / "run"),
            "--status",
            "prepared",
            "--dataset-manifest",
            str(dataset),
            "--verl-root",
            str(tmp_path / "verl"),
        ],
    )
    with pytest.raises(ValueError, match="effective source"):
        writer.main()
    assert not (tmp_path / "run/run-manifest.json").exists()


def test_actual_verl_identity_rejects_wrong_editable_import(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deployment.checks import verl_source_overlay

    monkeypatch.setattr(verl_source_overlay, "verify_verl_source", lambda *a, **k: {"state": "patched"})
    monkeypatch.setattr(
        writer.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=str(tmp_path / "old/verl/__init__.py"))
    )
    with pytest.raises(ValueError, match="import does not use"):
        writer._actual_verl_identity(tmp_path / "new")
