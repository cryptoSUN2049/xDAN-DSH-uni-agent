"""Run packaging orchestration against a fixture publisher, never a real build."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deployment/bootstrap/package-dsh-runtime.sh"
REVISION = "b2369692ea530007075ebcd18d39fdba0bbd3982"
RUNTIME = "deepseek-harness-sdk-runtime-linux-x64"
pytestmark = [pytest.mark.cpu, pytest.mark.level0]


@pytest.fixture
def package_job(tmp_path):
    source = tmp_path / "source checkout"
    output = tmp_path / "release output"
    binaries = tmp_path / "bin"
    for path in (source / "scripts", source / "dist-exe", binaries):
        path.mkdir(parents=True)
    for name in (RUNTIME, RUNTIME + "-rg"):
        path = source / "dist-exe" / name
        path.write_bytes(name.encode())
        path.chmod(0o700)
    (source / "scripts/build-python-release.py").write_text(
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "package = args[args.index('--package') + 1]\n"
        "with open(os.environ['TEST_CALLS'], 'a') as calls:\n"
        "    calls.write(json.dumps(args) + '\\n')\n"
        "if os.environ.get('TEST_PACKAGE_FAILURE') == package: sys.exit(7)\n"
        "suffix = ('runtime_bin-0.1.3a2-py3-none-manylinux_2_28_x86_64'\n"
        "          if package == 'runtime' else 'sdk-0.1.3a2-py3-none-any')\n"
        "output = pathlib.Path(args[args.index('--output-dir') + 1])\n"
        "(output / ('deepseek_harness_' + suffix + '.whl')).write_bytes(package.encode())\n"
    )
    commands = {
        "uname": "print(os.environ['TEST_OS'] if sys.argv[1] == '-s' else os.environ['TEST_ARCH'])",
        "git": (
            "if sys.argv[-2:] == ['rev-parse', 'HEAD']:\n"
            "    print(os.environ['TEST_HEAD'])\n"
            "elif 'status' in sys.argv:\n"
            "    assert '--untracked-files=no' in sys.argv\n"
            "    print(os.environ.get('TEST_DIRTY', ''), end='')\n"
            "    sys.exit(int(os.environ.get('TEST_GIT_STATUS_EXIT', '0')))\n"
            "else: sys.exit(99)"
        ),
        "uv": "print(os.environ['TEST_UV_VERSION']); sys.exit(int(os.environ.get('TEST_UV_EXIT', '0')))",
        "sha256sum": (
            "import hashlib\n"
            "for name in sys.argv[1:]:\n"
            "    print(hashlib.sha256(Path(name).read_bytes()).hexdigest() + '  ' + name)"
        ),
    }
    for name, body in commands.items():
        path = binaries / name
        path.write_text(f"#!{sys.executable}\nimport os, sys\nfrom pathlib import Path\n{body}\n")
        path.chmod(0o700)
    (binaries / "python3").symlink_to(sys.executable)
    environment = {
        "PATH": str(binaries) + ":/usr/bin:/bin",
        "DSH_SOURCE_ROOT": str(source),
        "DSH_RELEASE_ROOT": str(output),
        "TEST_CALLS": str(tmp_path / "calls.jsonl"),
        "TEST_OS": "Linux",
        "TEST_ARCH": "x86_64",
        "TEST_HEAD": REVISION,
        "TEST_UV_VERSION": "uv 0.9.0 (fixture)",
    }

    def run(**overrides):
        return subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=environment | overrides,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    return run, source, output, tmp_path / "calls.jsonl"


@pytest.mark.parametrize("uv_version", ["uv 0.9.0 (fixture)", "uv 0.9.1 (fixture)"])
def test_publishes_both_wheels_in_order_and_records_actual_tool_version(package_job, uv_version):
    run, source, output, calls = package_job
    result = run(TEST_UV_VERSION=uv_version)
    assert result.returncode == 0, result.stderr
    arguments = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [args[args.index("--package") + 1] for args in arguments] == ["runtime", "sdk"]
    assert arguments[0][arguments[0].index("--platform") + 1] == "linux-x64"
    assert Path(arguments[0][arguments[0].index("--runtime-exe") + 1]).name == RUNTIME
    assert "--runtime-exe" not in arguments[1]
    info = json.loads((output / "build-info.json").read_text())
    assert info["source_revision"] == REVISION
    assert info["uv_version"] == uv_version
    assert info["python_distribution_version"] == "0.1.3a2"
    sums = {}
    for line in (output / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = Path(name) if Path(name).is_absolute() else output / name
        assert expected == hashlib.sha256(path.read_bytes()).hexdigest()
        sums[path.name] = expected
    assert {RUNTIME, RUNTIME + "-rg"}.issubset(sums)
    assert len([name for name in sums if name.endswith(".whl")]) == 2


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_output_is_never_reused_or_overwritten(package_job, kind):
    run, source, output, calls = package_job
    if kind == "directory":
        output.mkdir()
        (output / "keep").write_text("preserved")
    elif kind == "file":
        output.write_text("preserved")
    else:
        output.symlink_to(source / "absent")
    assert run().returncode != 0
    assert not calls.exists()
    if kind == "directory":
        assert (output / "keep").read_text() == "preserved"
    elif kind == "file":
        assert output.read_text() == "preserved"
    else:
        assert output.is_symlink()


@pytest.mark.parametrize("name", [RUNTIME, RUNTIME + "-rg"])
def test_missing_payload_fails_before_output_creation(package_job, name):
    run, source, output, calls = package_job
    (source / "dist-exe" / name).unlink()
    assert run().returncode != 0
    assert not output.exists() and not calls.exists()


@pytest.mark.parametrize(
    "override",
    [
        {"TEST_HEAD": "7840bced35ee07ebefbdce0106b56dbc00bdc3ef"},
        {"TEST_DIRTY": " M tracked.py\n"},
        {"TEST_GIT_STATUS_EXIT": "1"},
        {"TEST_OS": "Darwin"},
        {"TEST_ARCH": "aarch64"},
        {"DSH_SOURCE_ROOT": "relative"},
        {"DSH_RELEASE_ROOT": "relative"},
        {"TEST_UV_EXIT": "1"},
    ],
)
def test_invalid_source_platform_paths_or_tool_never_publish(package_job, override):
    run, _source, output, calls = package_job
    assert run(**override).returncode != 0
    assert not output.exists() and not calls.exists()


@pytest.mark.parametrize("failed_package", ["runtime", "sdk"])
def test_official_packaging_failure_stops_without_success_manifest(package_job, failed_package):
    run, _source, output, calls = package_job
    assert run(TEST_PACKAGE_FAILURE=failed_package).returncode == 7
    assert not (output / "SHA256SUMS").exists()
    assert not (output / "build-info.json").exists()
    arguments = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(arguments) == (1 if failed_package == "runtime" else 2)
