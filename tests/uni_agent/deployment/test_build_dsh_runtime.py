"""Exercise shell preflight only; fake mkdir stops before any build/download."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deployment/bootstrap/build-dsh-runtime.sh"
BASELINE = "7840bced35ee07ebefbdce0106b56dbc00bdc3ef"
CANDIDATE = "b2369692ea530007075ebcd18d39fdba0bbd3982"
pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def preflight(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    commands = {
        "uname": "print(os.environ['TEST_OS'] if sys.argv[1] == '-s' else os.environ['TEST_ARCH'])",
        "git": (
            "if sys.argv[-2:] == ['rev-parse', 'HEAD']:\n"
            "    print(os.environ['TEST_HEAD'])\n"
            "elif 'status' in sys.argv:\n"
            "    assert '--untracked-files=no' in sys.argv\n"
            "    print(os.environ.get('TEST_DIRTY', ''), end='')\n"
            "    sys.exit(int(os.environ.get('TEST_GIT_STATUS_EXIT', '0')))\n"
            "else:\n"
            "    sys.exit(99)"
        ),
        "mkdir": "Path(os.environ['TEST_BOUNDARY']).write_text('preflight accepted'); sys.exit(75)",
    }
    for name, body in commands.items():
        path = binaries / name
        path.write_text(f"#!{sys.executable}\nimport os, sys\nfrom pathlib import Path\n{body}\n")
        path.chmod(0o700)
    environment = {
        "PATH": str(binaries),
        "DSH_SOURCE_ROOT": str(tmp_path / "source"),
        "DSH_TOOLS_ROOT": str(tmp_path / "tools"),
        "TEST_BOUNDARY": str(tmp_path / "boundary"),
        "TEST_OS": "Linux",
        "TEST_ARCH": "x86_64",
        "TEST_HEAD": BASELINE,
    }

    def run(**overrides):
        return subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=environment | overrides,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    return run, tmp_path / "boundary"


@pytest.mark.parametrize("revision", [None, BASELINE, CANDIDATE])
def test_only_default_baseline_or_explicit_approved_candidate_reaches_build_boundary(preflight, revision):
    run, boundary = preflight
    overrides = {} if revision is None else {"DSH_BUILD_REVISION": revision, "TEST_HEAD": revision}
    result = run(**overrides)
    assert result.returncode == 75, result.stderr
    assert boundary.read_text() == "preflight accepted"


@pytest.mark.parametrize("revision", ["", "main", "b236969", "c" * 40])
def test_unknown_revision_fails_before_any_mutation(preflight, revision):
    run, boundary = preflight
    result = run(DSH_BUILD_REVISION=revision)
    assert result.returncode == 2
    assert not boundary.exists()


@pytest.mark.parametrize("dirty", [" M tracked.ts\n", "M  staged.ts\n", " M submodule\n"])
def test_dirty_tracked_checkout_is_rejected(preflight, dirty):
    run, boundary = preflight
    result = run(TEST_DIRTY=dirty)
    assert result.returncode == 2
    assert not boundary.exists()


def test_git_status_failure_cannot_look_like_a_clean_checkout(preflight):
    run, boundary = preflight
    result = run(TEST_GIT_STATUS_EXIT="1")
    assert result.returncode != 0
    assert not boundary.exists()


@pytest.mark.parametrize("system,architecture", [("Darwin", "x86_64"), ("Linux", "aarch64")])
def test_non_linux_x64_platform_is_rejected(preflight, system, architecture):
    run, boundary = preflight
    assert run(TEST_OS=system, TEST_ARCH=architecture).returncode == 2
    assert not boundary.exists()


@pytest.mark.parametrize("revision,head", [(BASELINE, CANDIDATE), (CANDIDATE, BASELINE)])
def test_checkout_must_match_selected_revision(preflight, revision, head):
    run, boundary = preflight
    assert run(DSH_BUILD_REVISION=revision, TEST_HEAD=head).returncode == 2
    assert not boundary.exists()


@pytest.mark.parametrize("field", ["DSH_SOURCE_ROOT", "DSH_TOOLS_ROOT"])
def test_relative_roots_are_rejected(preflight, field):
    run, boundary = preflight
    assert run(**{field: "relative"}).returncode == 2
    assert not boundary.exists()


def test_candidate_manifest_does_not_claim_unbuilt_artifacts_or_change_baseline():
    candidate = json.loads((ROOT / "deployment/versions/dsh-session-v2-candidate.json").read_text())
    baseline = json.loads((ROOT / "deployment/versions/dsh-runtime-candidate.json").read_text())
    assert baseline["revision"] == BASELINE
    assert candidate["revision"] == CANDIDATE
    assert candidate["status"] == "not-deployed"
    assert candidate["package_version"] == "0.1.3-alpha.2"
    assert candidate["upstream_revision"] == "c389f96bf3a9b6807cb71ed6bdad5849be0df6d8"
    for key in ("runtime_digest", "runtime_wheel_sha256", "sdk_wheel_sha256", "image_digest"):
        assert candidate[key] is None
    assert candidate["node"] == baseline["node"] == "24.20.0"
    assert candidate["pnpm"] == baseline["pnpm"] == "11.7.0"
    assert candidate["target"] == baseline["target"] == "node24-linux-x64"
