import pytest

from deployment.checks.work_state_runtime_canary import validate_probe


def test_real_tool_contract_distinguishes_missing_from_denied():
    calls = [
        dict(label="missing", error=True, denied=False),
        dict(label="create", error=False, denied=False),
        dict(label="denied", error=True, denied=True),
    ]
    results = [
        dict(label=c["label"], isError=c["error"], expectedTextPresent=c["denied"], forbiddenTextPresent=False)
        for c in calls
    ]
    report = dict(tools=["str_replace_editor"], results=results)
    validate_probe(report, calls)
    results[0]["expectedTextPresent"] = True
    with pytest.raises(ValueError, match="missing"):
        validate_probe(report, calls)


def test_hidden_text_and_missing_calls_cannot_pass():
    calls = [dict(label="deny", error=True, denied=True)]
    report = dict(tools=["str_replace_editor"], results=[])
    with pytest.raises(ValueError):
        validate_probe(report, calls)
    report["results"] = [dict(label="deny", isError=True, expectedTextPresent=True, forbiddenTextPresent=True)]
    with pytest.raises(ValueError):
        validate_probe(report, calls)


def test_short_script_requires_actual_prior_tool_message():
    from deployment.checks.work_state_runtime_canary import short_wire_response

    steps = [
        [{"command": "view", "path": "/memory/index.md"}],
        [{"command": "view", "path": "/memory/handoff.md"}],
        [{"command": "create", "path": "/out/config.json", "file_text": '{"capacity":71}'}],
    ]
    first = short_wire_response(steps, 0, [])
    assert b"tool_calls" in first and b"create" not in first
    with pytest.raises(ValueError, match="observed"):
        short_wire_response(steps, 2, [{"role": "assistant", "content": "I read handoff"}])
    reply = short_wire_response(steps, 2, [{"role": "tool", "tool_call_id": "canary-1-0", "content": "1: capacity=71"}])
    assert b"create" in reply


def test_short_script_never_merges_read_and_write_generation():
    from deployment.checks.work_state_runtime_canary import short_reader_steps

    steps = short_reader_steps(
        "/memory", "/out", {"config.json": b'{"capacity":71}', "plan.json": b"[]"}, mode="positive"
    )
    assert [[c["command"] for c in step] for step in steps] == [["view"], ["view"], ["create", "create"]]
    assert steps[0][0]["path"].endswith("/index.md")
    assert steps[1][0]["path"].endswith("/handoff.md")
    with pytest.raises(ValueError):
        short_reader_steps("/memory", "/out", {}, mode="unknown")


def test_short_response_requires_all_write_results_before_completion():
    from deployment.checks.work_state_runtime_canary import short_wire_response

    steps = [[{"command": "create", "path": "/out/config.json"}, {"command": "create", "path": "/out/plan.json"}]]
    with pytest.raises(ValueError, match="observed"):
        short_wire_response(steps, 1, [{"role": "tool", "tool_call_id": "canary-0-0", "content": "created"}])
    messages = [{"role": "tool", "tool_call_id": f"canary-0-{i}", "content": "created"} for i in (0, 1)]
    assert b'"finish_reason": "stop"' in short_wire_response(steps, 1, messages)
    with pytest.raises(ValueError, match="budget"):
        short_wire_response(steps, 2, messages)


def test_short_negative_scripts_keep_quality_and_safety_distinct():
    from deployment.checks.work_state_runtime_canary import short_reader_steps

    outputs = {"config.json": b'{"capacity": 71}', "plan.json": b"[]"}
    guess = short_reader_steps("/case/b-memory", "/case/b-results", outputs, mode="no-read")
    assert len(guess) == 1 and all(c["command"] == "create" for c in guess[0])
    unsafe = short_reader_steps("/case/b-memory", "/case/b-results", outputs, mode="unsafe")
    assert unsafe == [[{"command": "view", "path": "/case/a-source.json"}]]
    wrong = short_reader_steps("/case/b-memory", "/case/b-results", outputs, mode="wrong-memory")
    assert [s[0]["command"] for s in wrong] == ["view", "view", "create"]


def test_core_cli_runs_all_four_families_and_two_variants(tmp_path, monkeypatch, capsys):
    """CPU dispatch fixture; does not claim SDK runtime execution."""
    import json
    import sys

    from deployment.checks import work_state_runtime_canary as canary

    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"synthetic CPU runtime")
    lock = tmp_path / "deployment/versions/g1-deployment-lock.json"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"dsh": {"runtime_binary_sha256": canary.digest(runtime.read_bytes())}}))
    monkeypatch.setattr(canary, "ROOT", tmp_path)
    monkeypatch.setattr(canary, "sdk_version", lambda: "synthetic-cpu-sdk")
    seen = []

    def scenario(root, exe, family, variant, *, course="work-state-v1"):
        seen.append((family, variant, course))
        return {"task_id": f"{family}-{variant}"}

    monkeypatch.setattr(canary, "scenario", scenario)
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        ["canary", "--output", str(output), "--runtime", str(runtime), "--course", "work-state-memory-core-v1"],
    )
    canary.main()
    assert seen == [
        (family, variant, "work-state-memory-core-v1")
        for family in ("WS01", "WS03", "WS05", "WS06")
        for variant in (0, 1)
    ]
    report = json.loads((output / "result.json").read_text())
    assert report["course_id"] == "work-state-memory-core-v1" and len(report["scenarios"]) == 8
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_scenario_rejects_unknown_course_before_creating_files(tmp_path):
    from deployment.checks.work_state_runtime_canary import scenario

    output = tmp_path / "unused"
    with pytest.raises(ValueError, match="course"):
        scenario(output, tmp_path / "runtime", "WS01", 0, course="unknown")
    assert not output.exists()


@pytest.mark.parametrize("course", ["work-state-v1", "work-state-memory-core-v1"])
@pytest.mark.parametrize("family", ["WS01", "WS03", "WS05", "WS06"])
@pytest.mark.parametrize("variant", [0, 1])
def test_scenario_uses_real_generator_bundle_freeze_and_scoring(tmp_path, monkeypatch, course, family, variant):
    """Only SDK tools are replaced by local writes; this is synthetic CPU evidence."""
    import json
    from pathlib import Path

    from deployment.checks import work_state_runtime_canary as canary

    observed = []

    def cpu_probe(root, role, chain, reads, writes, missing, calls, exe, hidden, session_id=None, **kwargs):
        observed.append((role, kwargs))
        for item in calls:
            args = item["call"]["arguments"]
            if args["command"] == "create" and not item["error"]:
                target = Path(args["path"])
                assert target in writes
                target.parent.mkdir(exist_ok=True)
                target.write_text(args["file_text"])
        return session_id or "synthetic-writer", {"synthetic_cpu_fixture": True}

    monkeypatch.setattr(canary, "probe", cpu_probe)
    root = tmp_path / "scenario"
    report = canary.scenario(root, tmp_path / "runtime", family, variant, course=course)
    assert report["score"]["reward"] == 1
    assert [role for role, _ in observed] == ["writer", "reader"]
    assert (root / "bundle.json").read_bytes() == canary.pack_bundle(
        root / "b-memory", canary.make_task(family, variant, seed=7)["memory_paths"]
    )
    if course == "work-state-memory-core-v1":
        from examples.dsh.capabilities.work_state.core_tasks import make_core_task

        task = make_core_task(family, variant, seed=7)
        generator_path = canary.ROOT / "examples/dsh/capabilities/work_state/core_tasks.py"
        generator_sha = canary.digest(generator_path.read_bytes())
        assert report["task_id"] == task["task_id"]
        assert report["generator"] == {"path": str(generator_path), "sha256": generator_sha}
        assert all(kwargs == {"source_version": generator_sha} for _, kwargs in observed)
        assert report["source_version"] == canary.digest(
            json.dumps({"task": task, "generator_sha256": generator_sha}, sort_keys=True).encode()
        )
        assert generator_sha != canary.digest(
            (canary.ROOT / "examples/dsh/capabilities/work_state/tasks.py").read_bytes()
        )
    else:
        assert report["task_id"] == canary.make_task(family, variant, seed=7)["task_id"]
        assert all(kwargs == {} for _, kwargs in observed)
        assert "generator" not in report and "source_version" not in report


def test_scenario_does_not_return_success_for_bad_oracle_artifacts(tmp_path, monkeypatch):
    """A failed business score stays failed despite successful tool persistence."""
    from pathlib import Path

    from deployment.checks import work_state_runtime_canary as canary

    def cpu_probe(root, role, chain, reads, writes, missing, calls, exe, hidden, session_id=None, **kwargs):
        for item in calls:
            args = item["call"]["arguments"]
            if args["command"] == "create" and not item["error"]:
                Path(args["path"]).write_text(args["file_text"] if role == "writer" else "{}")
        return session_id or "synthetic-writer", {"synthetic_cpu_fixture": True}

    monkeypatch.setattr(canary, "probe", cpu_probe)
    with pytest.raises(ValueError, match="did not solve"):
        canary.scenario(tmp_path / "case", tmp_path / "runtime", "WS01", 0, course="work-state-memory-core-v1")


@pytest.mark.parametrize("explicit_source", [None, "sha256:" + "7" * 64])
def test_probe_binds_explicit_generator_source_without_changing_legacy_default(tmp_path, monkeypatch, explicit_source):
    """Real policy builder; a minimal synthetic SDK boundary emits the probe report."""
    import json
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from deployment.checks import work_state_runtime_canary as canary

    captured = []

    class CpuHarness:
        def __init__(self, config):
            self.config = config

        def __enter__(self):
            patch = json.loads(Path(self.config.patches[0]).read_text())
            captured.append(patch[2]["insert"][0]["config"]["sourceVersion"])
            report_path = patch[-1]["insert"][0]["config"]["report"]
            Path(report_path).write_text(json.dumps({"tools": ["str_replace_editor"], "results": []}))
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setitem(
        sys.modules,
        "deepseek_harness",
        SimpleNamespace(DeepSeekHarness=CpuHarness, DeepSeekHarnessConfig=SimpleNamespace),
    )
    kwargs = {"source_version": explicit_source} if explicit_source is not None else {}
    canary.probe(
        tmp_path, "writer", "synthetic-chain", [], [], [], [], tmp_path / "runtime", "synthetic-secret", **kwargs
    )
    expected = explicit_source or canary.digest(
        (canary.ROOT / "examples/dsh/capabilities/work_state/tasks.py").read_bytes()
    )
    assert captured == [expected]


def test_core_generator_from_other_checkout_cannot_claim_current_source(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deployment.checks import work_state_runtime_canary as canary
    from examples.dsh.capabilities import work_state

    monkeypatch.setattr(
        work_state,
        "core_tasks",
        SimpleNamespace(__file__=str(tmp_path / "other/core_tasks.py"), make_core_task=canary.make_task),
        raising=False,
    )
    output = tmp_path / "case"
    with pytest.raises(ValueError, match="outside canary checkout"):
        canary.scenario(output, tmp_path / "runtime", "WS01", 0, course="work-state-memory-core-v1")
    assert not output.exists()
