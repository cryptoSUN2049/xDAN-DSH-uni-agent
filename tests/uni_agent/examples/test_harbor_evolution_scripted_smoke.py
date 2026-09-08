import json
from types import SimpleNamespace

import pytest

from deployment.checks.harbor_evolution_scripted_smoke import Policy, check_result


@pytest.mark.parametrize("mode", ["positive", "partial", "missing_define", "tamper"])
def test_policy_uses_real_returned_ids_and_exact_given_input(mode):
    policy = Policy(
        mode, fixture={"operation": "redact_email", "input": "owner@example.org"}, candidate="redact_payload"
    )
    body = {"messages": [{"role": "user", "content": "execute"}]}
    observed = []
    final = None
    for _ in range(10):
        chunks = policy.respond(body)
        calls = [
            call for chunk in chunks for choice in chunk["choices"] for call in choice["delta"].get("tool_calls", [])
        ]
        if not calls:
            final = json.loads(chunks[0]["choices"][0]["delta"]["content"])
            break
        assert len(calls) == 1
        fn = calls[0]["function"]
        args = json.loads(fn["arguments"])
        observed.append((fn["name"], args))
        if fn["name"] == "cordis_define":
            content = (
                "Defined evo-17/pkg-28 (Bounded transform); it is not running yet. "
                "Use cordis_run to activate this Package."
            )
        else:
            content = "ok"
        body["messages"].append({"role": "tool", "content": content})
    assert final is not None
    names = [name for name, _ in observed]
    expected = ["str_replace_editor", "cordis_inspect_list"]
    if mode != "missing_define":
        expected += ["cordis_define", "cordis_run"]
        if mode != "partial":
            expected += ["redact_payload"]
        expected += ["cordis_stop", "cordis_undefine"]
        assert final["plugin_id"] == "evo-17" and final["package_id"] == "pkg-28"
    assert names == expected
    for name, args in observed:
        if name == "cordis_run":
            assert args == {"pluginId": "evo-17", "packageId": "pkg-28", "mode": "run"}
        if name in ("cordis_stop", "cordis_undefine"):
            assert args == {"pluginId": "evo-17"}
        if name == "redact_payload":
            assert args == {"text": "owner@example.org"}
        if name == "cordis_define":
            assert "harness.registerTool" in args["code"]["host"]
    with pytest.raises(ValueError):
        policy.respond(body)


def test_define_ids_are_not_invented_on_bad_result():
    policy = Policy("positive", fixture={"operation": "redact_email", "input": "a@b.org"}, candidate="redact")
    body = {"messages": [{"role": "user"}]}
    for _ in range(3):
        policy.respond(body)
        body["messages"].append({"role": "tool", "content": "wrong"})
    with pytest.raises(ValueError, match="define result"):
        policy.respond(body)


@pytest.mark.parametrize("mode,reward", [("positive", 1.0), ("partial", 0.25)])
def test_exact_fractional_trial_reward_required(mode, reward):
    check_result(
        mode, SimpleNamespace(exception_info=None, verifier_result=SimpleNamespace(rewards={"reward": reward}))
    )
    with pytest.raises(RuntimeError):
        check_result(
            mode, SimpleNamespace(exception_info=None, verifier_result=SimpleNamespace(rewards={"reward": 0.0}))
        )


def test_missing_define_requires_specific_verifier_veto_and_no_reward():
    result = SimpleNamespace(exception_info="missing reward", verifier_result=None)
    check_result("missing_define", result, b"Evolution hard-veto evidence is not eligible for training")
    with pytest.raises(RuntimeError):
        check_result("missing_define", result, b"unrelated infrastructure failure")


def test_tamper_requires_specific_bridge_rejection():
    check_result(
        "tamper", SimpleNamespace(exception_info="Bridge trace/status/session identity mismatch", verifier_result=None)
    )
    with pytest.raises(RuntimeError):
        check_result("tamper", SimpleNamespace(exception_info="unknown error", verifier_result=None))


def test_taskref_mismatch_rejected_before_server_or_output(tmp_path, monkeypatch):
    import asyncio

    from deployment.checks import harbor_evolution_scripted_smoke as smoke

    task = tmp_path / "task"
    task.mkdir()
    (task / "instruction.md").write_text("fixed task")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"task_ref": {"id": "redact", "version": "v1", "sha256": "sha256:" + "0" * 64}}))
    monkeypatch.setattr(smoke, "start_server", lambda *_args: pytest.fail("No server before TaskRef admission"))
    with pytest.raises(ValueError, match="TaskRef"):
        asyncio.run(smoke.run(task, manifest, tmp_path / "output"))
    assert not (tmp_path / "output").exists()
