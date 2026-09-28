from tests.uni_agent.tasks import test_harbor_dsh_executor as executor_fixtures
from tests.uni_agent.tasks import test_mimo_harbor_lane as mimo_fixtures
from tests.uni_agent.tasks.test_harbor_dsh_executor import request_for, run
from tests.uni_agent.tasks.test_mimo_binding import binding_value
from uni_agent.tasks.harbor_dsh.mimo import MimoBinding, canonical, digest

harness = executor_fixtures.harness
task_dir = mimo_fixtures.task_dir


def test_executor_uses_task_cwd_and_transports_independent_mimo_receipt(task_dir, harness):
    binding = MimoBinding.model_validate(binding_value())

    def edit(trial):
        def rewrite():
            state = {
                "schema": "dsh.mimo-workspace-state.v1",
                "cwd": "/testbed",
                "gateway_session_id": "session-1",
                "binding_sha256": digest(canonical(binding.model_dump(mode="json", by_alias=True))),
                "base_ref": "c" * 40,
                "base_tree": "d" * 40,
                "snapshot_sha256": "sha256:" + "e" * 64,
            }
            receipt = {
                "schema": "dsh.mimo-verifier-receipt.v1",
                "status": "graded",
                "reward": 1.0,
                "base_ref": state["base_ref"],
                "snapshot_sha256": state["snapshot_sha256"],
                "gateway_session_id": "session-1",
                "verifier_returncode": 0,
            }
            (trial.dsh_dir / "mimo-state.json").write_bytes(canonical(state))
            (trial.paths.verifier_dir / "mimo-receipt.json").write_bytes(canonical(receipt))

        trial.rewrite = rewrite

    harness.edit = edit
    request = request_for(
        task_dir, task_ref={"id": "mimo-code-code-1"}, dsh_release={"image_digest": "sha256:" + "b" * 64}
    )
    result = run(request, task_dir)
    assert result.cleanup_confirmed is True
    assert set(result.artifacts) == {
        "dsh_trace",
        "dsh_result",
        "harbor_result",
        "verifier_log",
        "reward",
        "binding",
        "receipt",
    }
    assert harness.trial.config.agent.kwargs["workdir"] == "/testbed"
    assert harness.trial.config.agent.kwargs["runner_python"] == "/opt/dsh/bin/python"
    assert harness.trial.strategy_kwargs["strategy"] == "mimo-code"
