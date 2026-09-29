import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]
MODULE = Path(__file__).resolve().parents[3] / "docs/verl-uni-agent-harbor-opd-rl/mimo_observability.py"


def module():
    spec = importlib.util.spec_from_file_location("mimo_observability", MODULE)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def response(step=4, grad=0.1, reward=0.75, timestamp=100):
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {
                        "__name__": "rl_insight_monitor_" + name,
                        "project": "project",
                        "experiment_name": "r11",
                    },
                    "value": [timestamp, str(value)],
                }
                for name, value in [
                    ("training_global_step", step),
                    ("actor_grad_norm", grad),
                    ("critic_rewards_mean", reward),
                ]
            ],
        },
    }


def test_real_terminal_vector_ack():
    m = module()
    assert m.verify_ack(response(), "project", "r11", 4, 99) == {
        "training_global_step": 4.0,
        "actor_grad_norm": 0.1,
        "critic_rewards_mean": 0.75,
    }


@pytest.mark.parametrize("mutation", ["step", "nan", "old", "missing", "duplicate", "identity", "type", "failure"])
def test_rejects_unproven_vectors(mutation):
    m = module()
    data = response()
    values = data["data"]["result"]
    if mutation == "step":
        values[0]["value"][1] = "3"
    elif mutation == "nan":
        values[1]["value"][1] = "nan"
    elif mutation == "old":
        values[0]["value"][0] = 98
    elif mutation == "missing":
        values.pop()
    elif mutation == "duplicate":
        values.append(values[0])
    elif mutation == "identity":
        values[0]["metric"]["experiment_name"] = "another-run"
    elif mutation == "type":
        data["data"]["resultType"] = "matrix"
    else:
        data["status"] = "error"
    assert m.verify_ack(data, "project", "r11", 4, 99) is None


def test_query_escapes_identity_and_requests_native_metric_names():
    text = module().metric_query('project"one', "r11")
    assert 'project="project\\"one"' in text
    assert "rl_insight_monitor_actor_grad_norm" in text
    assert 'experiment_name="r11"' in text


def test_ack_polls_and_keeps_backend_evidence(tmp_path):
    m = module()
    replies = iter([response(step=3), response()])
    times = iter([0, 0, 1, 1])
    report = m.wait_for_ack(
        "project",
        "r11",
        4,
        99,
        tmp_path / "ack.json",
        query=lambda query, timeout: next(replies),
        clock=lambda: next(times),
        sleep=lambda _: None,
    )
    assert report["status"] == "passed"
    assert report["backend_response"] == response()
    assert json.loads((tmp_path / "ack.json").read_text())["values"]["training_global_step"] == 4


def test_timeout_writes_failure_and_does_not_claim_ack(tmp_path):
    m = module()
    times = iter([0, 0, 46, 46])
    with pytest.raises(TimeoutError, match="acknowledge"):
        m.wait_for_ack(
            "project",
            "r11",
            4,
            99,
            tmp_path / "ack.json",
            query=lambda query, timeout: response(step=3),
            clock=lambda: next(times),
            sleep=lambda _: None,
        )
    assert json.loads((tmp_path / "ack.json").read_text())["status"] == "failed"


def test_transport_error_is_bounded_and_recorded(tmp_path):
    m = module()
    times = iter([0, 0, 46, 46])

    def unavailable(query, timeout):
        raise TimeoutError("collector unreachable")

    with pytest.raises(TimeoutError):
        m.wait_for_ack(
            "project",
            "r11",
            4,
            99,
            tmp_path / "ack.json",
            query=unavailable,
            clock=lambda: next(times),
            sleep=lambda _: None,
        )
    assert json.loads((tmp_path / "ack.json").read_text())["last_error_type"] == "TimeoutError"


def test_native_training_failure_never_calls_ack():
    m = module()
    calls = []

    def failed():
        raise RuntimeError("native training failed")

    with pytest.raises(RuntimeError, match="native training failed"):
        m.run_then_ack(failed, lambda started: calls.append(started))
    assert not calls


def test_ack_occurs_after_native_completion():
    m = module()
    calls = []
    m.run_then_ack(lambda: calls.append("native"), lambda started: calls.append(started), now=lambda: 99)
    assert calls == ["native", 99]


@pytest.mark.parametrize("payload", [{}, {"status": "success", "data": {}}, response(grad="not-a-number")])
def test_malformed_ack_fails_closed(payload):
    assert module().verify_ack(payload, "project", "r11", 4, 99) is None


def test_deadline_reserve_prevents_late_queries(tmp_path):
    m = module()
    assert m.DEADLINE == 1790709401
    with pytest.raises(TimeoutError):
        m.wait_for_ack(
            "project",
            "r11",
            4,
            99,
            tmp_path / "ack.json",
            query=lambda *_: pytest.fail("must not query past cleanup boundary"),
            clock=lambda: 1,
            wall_clock=lambda: m.DEADLINE - 179,
        )
    assert json.loads((tmp_path / "ack.json").read_text())["budget_seconds"] == 0


def test_http_query_uses_real_read_endpoint(monkeypatch):
    import io

    m = module()
    calls = []

    def opener(url, timeout):
        calls.append((url, timeout))
        return io.StringIO(json.dumps(response()))

    monkeypatch.setattr(m, "urlopen", opener)
    assert m.query_prometheus("a{b=1}", 3) == response()
    assert calls == [("http://127.0.0.1:9090/api/v1/query?query=a%7Bb%3D1%7D", 3)]


def test_composition_retains_native_actor_through_ack(monkeypatch, tmp_path):
    from types import SimpleNamespace

    m = module()
    events = []
    handle = SimpleNamespace(run=SimpleNamespace(remote=lambda config: events.append("native") or "result"))
    ray = SimpleNamespace(remote=lambda **kwargs: lambda cls: cls, get=lambda obj: obj)
    native = SimpleNamespace(remote=lambda: handle)
    runner = m.make_observed_runner(ray, native)()
    config = SimpleNamespace(
        trainer=SimpleNamespace(
            project_name="project",
            experiment_name="r11",
            total_training_steps=4,
            default_local_dir=str(tmp_path / "checkpoints"),
        )
    )

    def acknowledge(*args):
        assert runner.native_runner is handle
        events.append("ack")
        assert args[:3] == ("project", "r11", 4)
        return "passed"

    monkeypatch.setattr(m, "wait_for_ack", acknowledge)
    assert runner.run(config) == "passed"
    assert events == ["native", "ack"]
