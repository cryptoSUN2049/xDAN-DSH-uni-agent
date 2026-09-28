import hashlib
import io
import json
from urllib.error import HTTPError

import pytest

from deployment.harbor.mimo.publish_binding import DOCKER_DEFAULT_PATH
from deployment.harbor.mimo.remote_builder import BuilderConfig, _private_registry_target, execute


class Process:
    def __init__(self, stdout="", code=0):
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO("")
        self.returncode = code

    def wait(self):
        return self.returncode


class Sandbox:
    object_id = "sb-cpu-probe"
    terminated = False

    def __init__(self, image_ref, fail_pull=False):
        self.image_ref = image_ref
        self.fail_pull = fail_pull
        self.commands = []

    def exec(self, *args, **kwargs):
        self.commands.append((args, kwargs))
        if args[:2] == ("docker", "pull") and self.fail_pull:
            return Process(code=1)
        if args[:3] == ("docker", "image", "inspect"):
            return Process(json.dumps([{"RepoDigests": [self.image_ref], "Os": "linux", "Architecture": "amd64"}]))
        return Process("{}")

    def terminate(self, *, wait=False):
        self.terminated = True


def config(tmp_path):
    return BuilderConfig(
        mode="probe",
        original_image="docker.io/mimo/task@sha256:" + "a" * 64,
        output=tmp_path / "evidence",
        timeout_seconds=180,
    )


def test_cpu_probe_preserves_inspect_and_always_terminates(tmp_path):
    options = config(tmp_path)
    sandbox = Sandbox(options.original_image)
    result = execute(options, create_sandbox=lambda _: sandbox)
    assert result["status"] == "probe_passed"
    assert sandbox.terminated
    assert json.loads((options.output / "original-inspect.json").read_text())["RepoDigests"] == [options.original_image]
    assert all(0 < kwargs["timeout"] <= 180 for _, kwargs in sandbox.commands)


def test_pull_failure_still_terminates_and_preserves_failure(tmp_path):
    options = config(tmp_path)
    sandbox = Sandbox(options.original_image, fail_pull=True)
    with pytest.raises(RuntimeError):
        execute(options, create_sandbox=lambda _: sandbox)
    assert sandbox.terminated
    evidence = json.loads((options.output / "status.json").read_text())
    assert evidence["status"] == "failed"
    assert evidence["terminated"] is True


def test_dockerhub_reference_normalization_preserves_identity(tmp_path):
    options = config(tmp_path)
    sandbox = Sandbox(options.original_image.removeprefix("docker.io/"))
    result = execute(options, create_sandbox=lambda _: sandbox)
    assert result["status"] == "probe_passed"
    assert result["original_image"] == options.original_image


def test_same_digest_from_another_repository_is_rejected(tmp_path):
    options = config(tmp_path)
    sandbox = Sandbox("other/task@sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="identity/platform"):
        execute(options, create_sandbox=lambda _: sandbox)
    assert sandbox.terminated
    assert (options.output / "original-inspect.json").is_file()


def test_cleanup_failure_cannot_report_probe_success(tmp_path):
    options = config(tmp_path)
    sandbox = Sandbox(options.original_image)

    def fail_termination(*, wait=False):
        raise TimeoutError("not confirmed")

    sandbox.terminate = fail_termination
    with pytest.raises(RuntimeError, match="termination"):
        execute(options, create_sandbox=lambda _: sandbox)
    evidence = json.loads((options.output / "status.json").read_text())
    assert evidence["status"] == "cleanup_failed"
    assert evidence["terminated"] is False


@pytest.mark.parametrize("visibility", ["public", "internal", None])
def test_private_registry_gate_rejects_nonprivate_packages(tmp_path, monkeypatch, visibility):
    options = config(tmp_path)
    options.image_tag = "ghcr.io/example/mimo-dsh:v1"
    responses = [{"login": "example"}, {"visibility": visibility}]
    monkeypatch.setattr(
        "deployment.harbor.mimo.remote_builder.urlopen",
        lambda *args, **kwargs: io.StringIO(json.dumps(responses.pop(0))),
    )
    with pytest.raises(ValueError, match="private GHCR"):
        _private_registry_target(options, "not-a-real-token", allow_missing=True)


def test_new_package_is_allowed_only_before_push(tmp_path, monkeypatch):
    options = config(tmp_path)
    options.image_tag = "ghcr.io/example/mimo-dsh:v1"

    def get(request, *, timeout):
        if request.full_url.endswith("/user"):
            return io.StringIO(json.dumps({"login": "EXAMPLE"}))
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr("deployment.harbor.mimo.remote_builder.urlopen", get)
    assert _private_registry_target(options, "not-a-real-token", allow_missing=True) == "new_package_default_private"
    with pytest.raises(RuntimeError, match="privacy"):
        _private_registry_target(options, "not-a-real-token", allow_missing=False)


def build_config(tmp_path):
    options = config(tmp_path)
    options.mode = "build"
    options.image_tag = "ghcr.io/example/mimo-dsh:v1"
    options.registry_user = "example"
    options.registry_token_file = tmp_path / "private-token"
    options.registry_token_file.write_text("not-a-real-token")
    options.registry_token_file.chmod(0o600)
    options.context = tmp_path / "context"
    options.context.mkdir()
    files = {"Dockerfile": "FROM test\n", "base-inspect.json": "{}"}
    for name, content in files.items():
        (options.context / name).write_text(content)
    (options.context / "context-manifest.json").write_text(
        json.dumps(
            {
                "image_binding": {"original_image": options.original_image},
                "files": {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()},
            }
        )
    )
    return options


def test_public_registry_rejection_precedes_allocation(tmp_path, monkeypatch):
    options = build_config(tmp_path)

    def reject(*args, **kwargs):
        raise ValueError("public package")

    monkeypatch.setattr("deployment.harbor.mimo.remote_builder._private_registry_target", reject)
    allocated = []
    with pytest.raises(ValueError, match="public package"):
        execute(options, create_sandbox=lambda _: allocated.append(True))
    assert allocated == []


@pytest.mark.parametrize("mode", ["build", "verify"])
def test_build_credentials_use_only_stdin_and_digest_is_read_back(tmp_path, monkeypatch, mode):
    options = build_config(tmp_path)
    options.mode = mode
    token = options.registry_token_file.read_text()
    derived = "ghcr.io/example/mimo-dsh@sha256:" + "b" * 64
    options.published_image = derived
    stdin = io.BytesIO()
    stdin.write_eof = lambda: None
    stdin.drain = lambda: None

    class BuildSandbox(Sandbox):
        filesystem = None

        def __init__(self):
            super().__init__(options.original_image)
            self.filesystem = self
            self.uploads = []

        def copy_from_local(self, source, destination):
            self.uploads.append((source, destination))

        def exec(self, *args, **kwargs):
            if args[:2] == ("docker", "run") and "/usr/bin/env" in args:
                self.commands.append((args, kwargs))
                return Process("PATH=" + DOCKER_DEFAULT_PATH + "\n")
            if args[:3] == ("docker", "image", "inspect") and args[3] != options.original_image:
                self.commands.append((args, kwargs))
                return Process(json.dumps([{"RepoDigests": [derived]}]))
            if args[:2] == ("docker", "login"):
                self.commands.append((args, kwargs))
                process = Process(token)
                process.stdin = stdin
                return process
            return super().exec(*args, **kwargs)

    sandbox = BuildSandbox()
    monkeypatch.setattr("deployment.harbor.mimo.remote_builder._private_registry_target", lambda *a, **kw: "private")
    monkeypatch.setattr(
        "deployment.harbor.mimo.remote_builder.finalize_binding", lambda **kw: {"dsh_image": kw["derived_image"]}
    )
    result = execute(options, create_sandbox=lambda _: sandbox)
    assert result["status"] == "image_published_and_verified"
    assert result["image_binding"]["dsh_image"] == derived
    assert sandbox.terminated
    assert stdin.getvalue() == (token + "\n").encode()
    assert ("docker", "pull", derived) in [command for command, _ in sandbox.commands]
    assert all(token not in " ".join(command) for command, _ in sandbox.commands)
    assert all(source != options.registry_token_file for source, _ in sandbox.uploads)
    assert all(token not in path.read_text() for path in options.output.glob("*.log"))
    if mode == "verify":
        assert not sandbox.uploads
        assert all(command[:2] not in (("docker", "build"), ("docker", "push")) for command, _ in sandbox.commands)


@pytest.mark.parametrize("fault", ["floating", "latest", "missing_token", "deadline", "cpu", "output_exists"])
def test_invalid_request_never_creates_sandbox(tmp_path, fault):
    options = config(tmp_path)
    if fault == "floating":
        options.original_image = "mimo/task:latest"
    elif fault == "latest":
        options.mode = "build"
        options.image_tag = "ghcr.io/example/image:latest"
    elif fault == "missing_token":
        options.mode = "build"
        options.image_tag = "ghcr.io/example/image:v1"
    elif fault == "deadline":
        options.timeout_seconds = 0
    elif fault == "cpu":
        options.cpu = 100
    else:
        options.output.mkdir()
    created = []
    with pytest.raises((ValueError, FileExistsError)):
        execute(options, create_sandbox=lambda _: created.append(True))
    assert created == []
