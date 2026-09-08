import json
from types import SimpleNamespace

import pytest

from deployment.checks.harbor_t2_scripted_smoke import Policy, check_result, private_output


def test_wrongoutput_changes_real_definition_only():
    policy = Policy("wrongoutput", [])
    body = {"messages": [{"role": "tool"}]}
    policy.respond(body)
    policy.respond(body)
    chunks = policy.respond(body)
    call = chunks[1]["choices"][0]["delta"]["tool_calls"][0]
    assert call["function"]["name"] == "cordis_define"
    assert "execute(a){return [];" in json.loads(call["function"]["arguments"])["code"]["host"]


def test_noop_stops_without_tools():
    assert Policy("noop", []).respond({})[0]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize("mode,reward", [("positive", 1), ("wrongoutput", 0), ("noop", 0)])
def test_expected_scores(mode, reward):
    check_result(
        mode, SimpleNamespace(exception_info=None, verifier_result=SimpleNamespace(rewards={"reward": reward}))
    )
    with pytest.raises(RuntimeError):
        check_result(
            mode, SimpleNamespace(exception_info=None, verifier_result=SimpleNamespace(rewards={"reward": 1 - reward}))
        )


def test_tamper_requires_exact_rejection_and_no_score():
    check_result(
        "tamper", SimpleNamespace(exception_info="Bridge trace/status/session identity mismatch", verifier_result=None)
    )
    with pytest.raises(RuntimeError):
        check_result("tamper", SimpleNamespace(exception_info="Docker unavailable", verifier_result=None))


def test_existing_output_rejected(tmp_path):
    with pytest.raises(FileExistsError):
        private_output(tmp_path)
    path = tmp_path / "new"
    private_output(path)
    assert path.stat().st_mode & 0o777 == 0o700


def test_real_http_session_auth_model_and_sse():
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from deployment.checks.harbor_t2_scripted_smoke import KEY, MODEL, start_server

    server, thread, requests, errors = start_server(Policy("noop", []), "session-test")
    root = f"http://127.0.0.1:{server.server_port}"
    body = json.dumps({"model": MODEL, "stream": True}).encode()
    try:
        req = Request(
            root + "/sessions/session-test/v1/chat/completions", data=body, headers={"Authorization": f"Bearer {KEY}"}
        )
        with urlopen(req, timeout=5) as response:
            raw = response.read().decode()
        chunk = json.loads(raw.splitlines()[0].removeprefix("data: "))
        assert chunk["model"] == MODEL
        assert chunk["id"].startswith("chatcmpl-session-test-")
        assert "[DONE]" in raw
        assert len(requests) == 1 and not errors
        for path, key in [
            ("/sessions/wrong/v1/chat/completions", KEY),
            ("/sessions/session-test/v1/chat/completions", "wrong"),
        ]:
            with pytest.raises(HTTPError) as caught:
                urlopen(Request(root + path, data=body, headers={"Authorization": f"Bearer {key}"}), timeout=5)
            assert caught.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_output_permission_ignored_fails_before_writes(tmp_path, monkeypatch):
    from pathlib import Path

    original = Path.mkdir

    def ignoring_mode(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.chmod(0o777)

    monkeypatch.setattr(Path, "mkdir", ignoring_mode)
    path = tmp_path / "public"
    with pytest.raises(ValueError, match="private permissions"):
        private_output(path)
    assert list(path.iterdir()) == []


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_trial_cleanup_is_actual_separate_gate(tmp_path, monkeypatch, cleanup_fails):
    import asyncio

    pytest.importorskip("harbor")
    from deployment.checks import harbor_t2_scripted_smoke as smoke
    from uni_agent.tasks.harbor_dsh import executor, isolated_trial

    fixture = tmp_path / "fixture.json"
    fixture.write_text('{"calls": []}')
    task = tmp_path / "task"
    task.mkdir()
    output = tmp_path / "output"
    calls = []

    class Trial:
        async def run(self):
            return SimpleNamespace(exception_info=None, verifier_result=SimpleNamespace(rewards={"reward": 0}))

    class Server:
        server_port = 12345

        def shutdown(self):
            calls.append("shutdown")

        def server_close(self):
            calls.append("close")

    async def cleanup(trial):
        calls.append("cleanup")
        if cleanup_fails:
            raise RuntimeError("Harbor cleanup left resources behind")

    monkeypatch.setattr(
        smoke, "start_server", lambda *args: (Server(), SimpleNamespace(join=lambda *args: None), [{}], [])
    )
    monkeypatch.setattr(isolated_trial, "create_isolated_trial", lambda *args, **kwargs: Trial())
    monkeypatch.setattr(executor, "_confirm_cleanup", cleanup)
    if cleanup_fails:
        with pytest.raises(RuntimeError, match="resources behind"):
            asyncio.run(smoke.run(task, fixture, output, modes=["noop"]))
    else:
        asyncio.run(smoke.run(task, fixture, output, modes=["noop"]))
    report = json.loads((output / "scripted-smoke.json").read_text())
    assert report["passed"] is (not cleanup_fails)
    assert report["cases"][0]["cleanup_confirmed"] is (not cleanup_fails)
    assert calls == ["shutdown", "close", "cleanup"]
    assert report["source_sha256"][str(fixture)]
