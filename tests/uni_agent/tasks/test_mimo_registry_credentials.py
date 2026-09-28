from types import SimpleNamespace

import pytest

from tests.uni_agent.tasks import test_harbor_dsh_executor as executor_fixtures
from tests.uni_agent.tasks import test_harbor_dsh_isolated_trial as trial_fixtures
from tests.uni_agent.tasks.test_harbor_dsh_protocol import payload, policy
from uni_agent.tasks.harbor_dsh.environment_backend import TRACKED_MODAL_IMPORT
from uni_agent.tasks.harbor_dsh.isolated_trial import _validate_runtime
from uni_agent.tasks.harbor_dsh.ledger import JobLedger
from uni_agent.tasks.harbor_dsh.worker import HarborWorker

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
task_dir = trial_fixtures.task_dir
harness = executor_fixtures.harness


def test_modal_pull_secret_does_not_enable_sandbox_secret_kwargs(task_dir):
    environment = {
        "type": "modal",
        "import_path": TRACKED_MODAL_IMPORT,
        "delete": True,
        "kwargs": {"registry_secret": "mimo-dsh-ghcr"},
    }
    assert _validate_runtime(trial_fixtures.config(task_dir, environment=environment), task_dir) == task_dir.resolve()
    for kwargs in [{"registry_secret": "bad/name"}, {"registry_secret": ""}, {"secrets": ["mimo-dsh-ghcr"]}]:
        with pytest.raises(ValueError):
            _validate_runtime(trial_fixtures.config(task_dir, environment={**environment, "kwargs": kwargs}), task_dir)
    with pytest.raises(ValueError):
        _validate_runtime(trial_fixtures.config(task_dir, environment={**environment, "type": "docker"}), task_dir)


@pytest.mark.asyncio
async def test_worker_forwards_operator_registry_secret_separately_from_job(tmp_path):
    calls = []

    async def execute(request, **kwargs):
        calls.append(kwargs)
        assert "registry_secret" not in request.model_dump()
        await kwargs["on_verifying"]()
        return SimpleNamespace(trial_id="modal-trial", cleanup_confirmed=True, artifacts={"reward": b"0"})

    data = payload()
    with JobLedger(tmp_path / "jobs.sqlite") as ledger:
        worker = HarborWorker(
            ledger=ledger,
            policy=policy(data),
            worker_id="worker-1",
            task_dir=tmp_path,
            root=tmp_path / "worker",
            gateway_base_url="https://gateway.example.com",
            environment_backend="modal",
            registry_secret="mimo-dsh-ghcr",
            executor=execute,
            clock=lambda: 1000.0,
        )
        worker.submit(data)
        await worker.wait(data["job_id"])
        assert calls[0]["registry_secret"] == "mimo-dsh-ghcr"
        assert calls[0]["gateway_base_url"] == "https://gateway.example.com" + data["model_route"]["session_path"]


@pytest.mark.parametrize("backend,secret", [("docker", "mimo-dsh-ghcr"), ("modal", "../bad"), ("modal", "")])
def test_worker_rejects_invalid_operator_registry_setting(tmp_path, backend, secret):
    with JobLedger(tmp_path / "jobs.sqlite") as ledger, pytest.raises(ValueError):
        HarborWorker(
            ledger=ledger,
            policy=policy(payload()),
            worker_id="worker-1",
            task_dir=tmp_path,
            root=tmp_path / "worker",
            gateway_base_url=(
                "https://gateway.example.com" if backend == "modal" else "http://host.docker.internal:1234"
            ),
            environment_backend=backend,
            registry_secret=secret,
        )


@pytest.mark.parametrize(
    "image,expected",
    [
        ("ghcr.io/owner/dsh@sha256:" + "a" * 64, "mimo-dsh-ghcr"),
        ("docker.io/xiaomi/task@sha256:" + "b" * 64, None),
    ],
)
def test_pull_credential_is_scoped_to_ghcr_and_never_mounted(tmp_path, image, expected):
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths

    from uni_agent.tasks.harbor_dsh.modal_environment import TrackedModalEnvironment

    environment = tmp_path / "environment"
    environment.mkdir()
    env = TrackedModalEnvironment(
        environment_dir=environment,
        environment_name="mimo",
        session_id="mimo-env",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=EnvironmentConfig(docker_image=image),
        registry_secret="mimo-dsh-ghcr",
    )
    assert env._registry_secret == expected
    assert env._secrets == []
