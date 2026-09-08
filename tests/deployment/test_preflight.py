import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parents[2] / "deployment/checks/preflight.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_unresolved_release_cannot_pass_with_all_packages_present():
    manifest = dict.fromkeys(preflight.IDENTITIES, "fixed")
    manifest["dsh_release"] = None
    failures = preflight.readiness(manifest, dict.fromkeys(preflight.REQUIRED, "1"), "Linux", True, manifest)
    assert "unresolved identity: dsh_release" in failures


def test_wrong_checkout_is_rejected():
    manifest = dict.fromkeys(preflight.IDENTITIES, "fixed")
    failures = preflight.readiness(
        manifest,
        dict.fromkeys(preflight.REQUIRED, "1"),
        "Linux",
        True,
        {"integration_revision": "other", "verl": "fixed"},
    )
    assert failures == ["revision mismatch: integration_revision"]


def test_missing_gpu_and_sdk_are_not_hidden():
    manifest = dict.fromkeys(preflight.IDENTITIES, "fixed")
    installed = dict.fromkeys(preflight.REQUIRED, "1")
    installed["deepseek-harness-sdk"] = None
    failures = preflight.readiness(manifest, installed, "Linux", False, manifest)
    assert "GPU inventory unavailable" in failures
    assert "missing package: deepseek-harness-sdk" in failures
