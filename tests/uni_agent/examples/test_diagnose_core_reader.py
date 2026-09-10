import pytest

from examples.dsh.capabilities.diagnose_core_reader import diagnostic_schedule, summarize_pairs


def test_schedule_balances_order_and_uses_neutral_unique_branches():
    schedule = diagnostic_schedule()
    assert len(schedule) == 8
    assert [x["variant"] for x in schedule] == ["original", "revised", "revised", "original"] * 2
    assert len({x["branch_id"] for x in schedule}) == 8
    assert all(x["branch_id"].startswith("b") for x in schedule)
    assert {(x["variant"], x["repetition"]) for x in schedule} == {
        (v, n) for v in ("original", "revised") for n in range(4)
    }


def test_summary_keeps_failed_writer_in_end_to_end_denominator():
    a = {"task_id": "a", "writer": {"eligible": False}, "readers": []}
    b = {
        "task_id": "b",
        "writer": {"eligible": True},
        "readers": [
            {**s, "eligible": True, "finished": True, "reward": float(s["variant"] == "revised")}
            for s in diagnostic_schedule()
        ],
    }
    report = summarize_pairs([a, b], planned_tasks=2)
    assert report["paired_tasks"] == 1
    assert report["writer_rejected_tasks"] == 1
    assert report["variants"]["revised"]["conditional_success_rate"] == 1
    assert report["variants"]["revised"]["end_to_end_success_rate"] == 0.5
    assert report["variants"]["original"]["end_to_end_success_rate"] == 0
    assert report["task_paired_difference"] == 1
    assert report["training_consumed"] is False


def test_partial_or_duplicate_readers_cannot_claim_complete_pair():
    readers = [{**s, "eligible": True, "finished": True, "reward": 1} for s in diagnostic_schedule()]
    partial = summarize_pairs([{"task_id": "a", "writer": {"eligible": True}, "readers": readers[:1]}], planned_tasks=1)
    assert partial["paired_tasks"] == 0
    assert partial["variants"]["revised"]["conditional_success_rate"] is None
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_pairs(
            [{"task_id": "a", "writer": {"eligible": True}, "readers": readers + readers[:1]}], planned_tasks=1
        )


@pytest.mark.asyncio
async def test_real_cpu_artifacts_produce_eight_isolated_readers_without_queue(tmp_path):
    import sys
    from pathlib import Path

    from examples.dsh.capabilities.diagnose_core_reader import run_diagnostic
    from examples.dsh.capabilities.memory_verifier import canonical, sha
    from examples.dsh.capabilities.work_state.stage import WorkStateOperator
    from tests.uni_agent.examples.test_work_state_stage import execute_synthetic_stage

    task_id = "work-state-memory-core-v1-ws01-v1-s2001"
    manifest = tmp_path / "tasks.json"
    manifest.write_bytes(
        canonical(
            {
                "schema": "dsh.work-state-dataset.v1",
                "tasks": {
                    task_id: {
                        "family": "WS01",
                        "variant": 1,
                        "seed": 2001,
                        "split": "validation",
                        "generation": "work-state-memory-core-v1",
                    }
                },
            }
        )
    )
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"runtime")
    runtime.chmod(0o700)
    operator = WorkStateOperator(
        tmp_path / "chains",
        Path(sys.executable),
        runtime,
        sha(b"runtime"),
        "base",
        "work-state-v1",
        manifest,
        sha(manifest.read_bytes()),
        8192,
    )
    operator.root.mkdir()
    seen = []

    async def execute(spec):
        seen.append(spec)
        import asyncio

        return await asyncio.to_thread(execute_synthetic_stage, spec)

    report = await run_diagnostic(
        operator, run_id="diagnostic", task_ids=[task_id], execute=execute, report_path=tmp_path / "report.json"
    )
    assert len(seen) == 9
    assert len({s.gateway_session_id for s in seen}) == 9
    assert report["status"] == "complete"
    assert report["summary"]["paired_tasks"] == 1
    assert report["summary"]["training_consumed"] is False
    assert {r["bundle_sha256"] for r in report["tasks"][0]["readers"]} == {report["tasks"][0]["frozen_content_sha256"]}
    assert not list(tmp_path.rglob("crosswalk.json"))
    with pytest.raises(FileExistsError):
        await run_diagnostic(
            operator, run_id="diagnostic", task_ids=[task_id], execute=execute, report_path=tmp_path / "report.json"
        )


def test_prepare_freezes_public_selection_and_detects_source_drift(tmp_path):
    import sys
    from pathlib import Path

    from examples.dsh.capabilities.diagnose_core_reader import check, prepare

    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    (model / "tokenizer.json").write_text("{}")
    (model / "model.safetensors").write_bytes(b"cpu-fixture-not-a-model")
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"runtime")
    runtime.chmod(0o700)
    path = prepare(
        root=tmp_path / "run",
        model_path=model,
        model_revision="a" * 40,
        runtime_executable=runtime,
        runner_python=Path(sys.executable),
        cuda_visible_devices="0",
        canary=True,
    )
    manifest = check(path)
    assert len(manifest["task_ids"]) == 1
    assert manifest["task_ids"][0] == "work-state-memory-core-v1-ws01-v1-s2001"
    assert not (tmp_path / "run" / "chains").exists()
    assert manifest["training"] is False
    (model / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        check(path)


def test_incomplete_summary_does_not_report_unobserved_as_failure():
    report = summarize_pairs([], planned_tasks=16)
    assert report["variants"]["original"]["end_to_end_success_rate"] is None


def test_cli_help_does_not_import_gpu_stack(capsys):
    from examples.dsh.capabilities.diagnose_core_reader import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "prepare" in capsys.readouterr().out


def test_launch_requires_runtime_probe_before_owning_gpu(tmp_path, monkeypatch):
    import examples.dsh.capabilities.diagnose_core_reader as module

    monkeypatch.setattr(module, "check", lambda p: {"root": str(tmp_path)})

    def reject(manifest):
        raise ValueError("runtime mismatch")

    monkeypatch.setattr(module, "check_execution_environment", reject)
    with pytest.raises(ValueError, match="runtime mismatch"):
        module.launch(tmp_path / "manifest.json")
    assert not (tmp_path / "execution.json").exists()


@pytest.mark.parametrize("mutation", ["model_path", "model_file_added"])
def test_prepared_model_identity_cannot_be_swapped(tmp_path, mutation):
    import json
    import sys

    from examples.dsh.capabilities.diagnose_core_reader import check, prepare

    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    (model / "model.safetensors").write_bytes(b"fixture")
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"fixture")
    path = prepare(
        root=tmp_path / "run",
        model_path=model,
        model_revision="a" * 40,
        runtime_executable=runtime,
        runner_python=sys.executable,
        cuda_visible_devices="0",
    )
    if mutation == "model_path":
        manifest = json.loads(path.read_text())
        manifest["model_path"] = str(tmp_path / "different")
        path.write_text(json.dumps(manifest))
    else:
        (model / "model.safetensors.index.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        check(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", [False, True])
async def test_negative_writer_has_no_fabricated_reader_and_corruption_aborts(tmp_path, corrupt):
    import asyncio
    import json
    import sys
    from pathlib import Path

    from examples.dsh.capabilities.diagnose_core_reader import run_diagnostic
    from examples.dsh.capabilities.memory_verifier import canonical, sha
    from examples.dsh.capabilities.work_state.stage import WorkStateOperator
    from tests.uni_agent.examples.test_work_state_stage import execute_synthetic_stage
    from tests.uni_agent.tasks.test_dsh_evolution_verifier import _call, _result

    task_id = "work-state-memory-core-v1-ws01-v1-s2001"
    manifest = tmp_path / "tasks.json"
    manifest.write_bytes(
        canonical(
            {
                "schema": "dsh.work-state-dataset.v1",
                "tasks": {
                    task_id: dict(
                        family="WS01", variant=1, seed=2001, split="validation", generation="work-state-memory-core-v1"
                    )
                },
            }
        )
    )
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"runtime")
    runtime.chmod(0o700)
    operator = WorkStateOperator(
        tmp_path / "chains",
        Path(sys.executable),
        runtime,
        sha(b"runtime"),
        "base",
        "work-state-v1",
        manifest,
        sha(manifest.read_bytes()),
        8192,
    )
    operator.root.mkdir()
    seen = []

    async def execute(spec):
        seen.append(spec)

        def unsafe(fixture, events):
            return events + [_call("unsafe", "bash", {"command": "true"}, seq=99), _result("unsafe", "")]

        execution = await asyncio.to_thread(execute_synthetic_stage, spec, transform_events=unsafe)
        if corrupt:
            next(spec.result_root.rglob("verifier-receipt.json")).write_text("{}")
        return execution

    async def run():
        return await run_diagnostic(
            operator, run_id="negative", task_ids=[task_id], execute=execute, report_path=tmp_path / "report.json"
        )

    if corrupt:
        with pytest.raises(ValueError):
            await run()
    else:
        await run()
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(seen) == 1
    assert report["status"] == ("aborted" if corrupt else "complete")
    assert report["summary"]["paired_tasks"] == 0
    assert report["summary"]["writer_rejected_tasks"] == (0 if corrupt else 1)
    if not corrupt:
        assert report["tasks"][0]["readers"] == []
        assert report["summary"]["variants"]["original"]["end_to_end_success_rate"] == 0
