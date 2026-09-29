import hashlib
import importlib
import json
import subprocess
import sys
from copy import deepcopy

import pytest

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def module():
    return importlib.import_module("deployment.checks.effective_update_audit")


def case(step=2):
    before = f"/runs/r8/rl-training/checkpoints/global_step_{step - 1}"
    run = "r8" if step == 2 else "r9"
    after = f"/runs/{run}/rl-training/checkpoints/global_step_{step}"
    uid = f"{run}-group"
    keys = [f"{uid}_{i}_0" for i in range(4)]
    launch = {
        "schema": "dsh.harbor-m2-launch.v1",
        "environment": {"RUN_ROOT": f"/runs/{run}"},
        "postprocessor": {"run_id": run, "run_spec_sha256": "sha256:" + "a" * 64},
    }
    launch_sha = "sha256:" + hashlib.sha256(json.dumps(launch).encode()).hexdigest()
    files = lambda kind: {
        name: {"path": f"{path}/actor/{kind}_world_size_1_rank_0.pt", "sha256": value * 64}
        for name, path, value in (("before", before, "1"), ("after", after, "2"))
    }
    group = dict(
        partition_id="train",
        global_steps=step,
        group_uid=uid,
        session_indexes=list(range(4)),
        rewards=[0.0, 1.0, 0.0, 1.0],
        transfer_queue_keys=keys,
        consumed_transfer_queue_keys=keys,
        status="admitted-and-training-batch-matched",
    )
    model = dict(
        schema="dsh.single-rank-lora-delta.v1",
        passed=True,
        adapter_count=1,
        adapter_changed=1,
        base_count=1,
        base_changed=0,
        tensors=[
            dict(name="base", adapter=False, finite=True, changed=False, max_abs_delta=0.0),
            dict(name="lora_A", adapter=True, finite=True, changed=True, max_abs_delta=0.01),
        ],
        **files("model"),
    )
    optim = dict(
        schema="dsh.native-optimizer-delta.v1",
        passed=True,
        errors=[],
        optimizer_step_advanced=True,
        active_state_count=1,
        empty_state_count=1,
        changed_moment_tensors=1,
        files=files("optim"),
    )
    for name, count in (("before", step - 1), ("after", step)):
        optim[name] = dict(
            steps=[count],
            active_state_count=1,
            empty_state_count=1,
            tensor_count=3,
            all_finite=True,
            nonzero_moment_tensors=2,
        )
    return dict(
        run_id=run,
        run_spec_sha256=launch["postprocessor"]["run_spec_sha256"],
        step=step,
        group_uid=uid,
        launch=launch,
        launch_sha256=launch_sha,
        batch_audit=dict(
            schema="dsh.harbor-training-batch-audit.v1",
            passed=True,
            errors=[],
            launch_sha256=launch_sha,
            groups=[group],
            unconsumed_groups=[],
        ),
        metrics_rows=[
            {
                "training/global_step": step,
                "critic/score/min": 0.0,
                "critic/score/max": 1.0,
                "critic/advantages/min": -1.0,
                "critic/advantages/max": 1.0,
                "actor/grad_norm": 0.2,
                "actor/pg_loss": 0.0,
            }
        ],
        model_delta=model,
        optimizer_delta=optim,
        before_checkpoint=before,
        after_checkpoint=after,
    )


@pytest.mark.parametrize("step", [2, 3])
def test_same_step_updates_pass_without_claiming_reload(step):
    data = case(step)
    before = deepcopy(data)
    report = module().audit_effective_update(**data)
    assert report["passed"] and report["effective_update_verified"]
    assert report["resume_verified"] is False
    assert report["restore_evidence"]["status"] == "unknown"
    assert data == before


@pytest.mark.parametrize(
    "attack",
    [
        "run",
        "spec",
        "launch-hash",
        "step",
        "uid",
        "prefetch",
        "member",
        "duplicate-key",
        "unconsumed",
        "constant-reward",
        "score",
        "cross-step-metrics",
        "duplicate-metrics",
        "positive-only",
        "zero-grad",
        "nan-grad",
        "inf-loss",
        "base",
        "adapter",
        "model-path",
        "model-hash",
        "same-hash-alias",
        "model-counter",
        "optimizer-path",
        "optimizer-step",
        "optimizer-reset",
        "optimizer-moments",
        "optimizer-finite",
        "bool-step",
    ],
)
def test_evidence_cannot_be_spliced_or_soft_passed(attack):
    data = case()
    group = data["batch_audit"]["groups"][0]
    metrics = data["metrics_rows"][0]
    if attack == "run":
        data["run_id"] = "other"
    elif attack == "spec":
        data["run_spec_sha256"] = "sha256:" + "b" * 64
    elif attack == "launch-hash":
        data["batch_audit"]["launch_sha256"] = "sha256:" + "b" * 64
    elif attack == "step":
        data["step"] = 3
    elif attack == "uid":
        data["group_uid"] = "other"
    elif attack == "prefetch":
        data["batch_audit"]["unconsumed_groups"] = data["batch_audit"].pop("groups")
    elif attack == "member":
        group["session_indexes"].pop()
    elif attack == "duplicate-key":
        group["transfer_queue_keys"] = [group["transfer_queue_keys"][0]] * 4
    elif attack == "unconsumed":
        group["consumed_transfer_queue_keys"] = []
    elif attack == "constant-reward":
        group["rewards"] = [0.0] * 4
    elif attack == "score":
        metrics["critic/score/max"] = 2.0
    elif attack == "cross-step-metrics":
        metrics["training/global_step"] = 1
    elif attack == "duplicate-metrics":
        data["metrics_rows"] *= 2
    elif attack == "positive-only":
        metrics["critic/advantages/min"] = 0.0
    elif attack == "zero-grad":
        metrics["actor/grad_norm"] = 0.0
    elif attack == "nan-grad":
        metrics["actor/grad_norm"] = float("nan")
    elif attack == "inf-loss":
        metrics["actor/pg_loss"] = float("inf")
    elif attack == "base":
        data["model_delta"]["tensors"][0]["changed"] = True
    elif attack == "adapter":
        data["model_delta"]["tensors"][1]["changed"] = False
    elif attack == "model-path":
        data["model_delta"]["after"]["path"] = "/other/model.pt"
    elif attack == "model-hash":
        data["model_delta"]["after"]["sha256"] = "invalid"
    elif attack == "same-hash-alias":
        data["model_delta"]["after"]["sha256"] = "sha256:" + data["model_delta"]["before"]["sha256"]
    elif attack == "model-counter":
        data["model_delta"]["adapter_changed"] = 99
    elif attack == "optimizer-path":
        data["optimizer_delta"]["files"]["before"]["path"] = "/other/optim.pt"
    elif attack == "optimizer-step":
        data["optimizer_delta"]["after"]["steps"] = [3]
    elif attack == "optimizer-reset":
        data["optimizer_delta"]["before"]["steps"] = [0]
    elif attack == "optimizer-moments":
        data["optimizer_delta"]["changed_moment_tensors"] = 0
    elif attack == "optimizer-finite":
        data["optimizer_delta"]["after"]["all_finite"] = False
    else:
        data["step"] = True
    report = module().audit_effective_update(**data)
    assert not report["passed"] and not report["effective_update_verified"]
    assert report["errors"]


def test_conservative_zero_moment_report_requests_fresh_evidence_without_passing():
    data = case()
    data["optimizer_delta"] = {
        "schema": "dsh.native-optimizer-delta.v1",
        "passed": False,
        "errors": ["ValueError: All optimizer moments are zero"],
    }
    report = module().audit_effective_update(**data)
    assert not report["passed"]
    assert report["needs_fresh_after_check"] is True


def test_console_parser_preserves_zero_loss_and_rejects_mismatched_step():
    text = "noise\n\x1b[32mstep:2 - training/global_step:2 - actor/grad_norm:1e-3 - actor/pg_loss:0\x1b[0m\n"
    assert module().parse_console_metrics(text) == [
        {"training/global_step": 2, "actor/grad_norm": 0.001, "actor/pg_loss": 0}
    ]
    with pytest.raises(ValueError):
        module().parse_console_metrics("step:2 - training/global_step:3 - actor/grad_norm:1")


def test_cli_reads_only_reports_and_returns_nonzero_for_failed_gate(tmp_path, monkeypatch, capsys):
    data = case()
    argv = []
    for name, key in [
        ("launch", "launch"),
        ("batch-audit", "batch_audit"),
        ("model-delta", "model_delta"),
        ("optimizer-delta", "optimizer_delta"),
    ]:
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(data[key]))
        argv += ["--" + name, str(path)]
    path = tmp_path / "metrics.log"
    path.write_text("step:2 - " + " - ".join(f"{k}:{v}" for k, v in data["metrics_rows"][0].items()) + "\n")
    argv += ["--console-metrics", str(path)]
    for name in ("run_id", "run_spec_sha256", "step", "group_uid", "before_checkpoint", "after_checkpoint"):
        argv += ["--" + name.replace("_", "-"), str(data[name])]
    result = subprocess.run(
        [sys.executable, "-m", "deployment.checks.effective_update_audit", *argv],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["resume_verified"] is False
    originals = {p: p.read_bytes() for p in tmp_path.iterdir()}
    monkeypatch.setattr(sys, "argv", ["effective_update_audit", *argv])
    assert module().main() == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["input_artifacts"]) == 5
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == originals
    path.write_text("no metrics\n")
    result = subprocess.run(
        [sys.executable, "-m", "deployment.checks.effective_update_audit", *argv],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert not json.loads(result.stdout)["passed"]
    assert module().main() == 1
    assert not json.loads(capsys.readouterr().out)["passed"]
    (tmp_path / "launch.json").write_text('{"schema":1,"schema":2}')
    assert module().main() == 1
    assert "Duplicate JSON key" in json.loads(capsys.readouterr().out)["errors"][0]


@pytest.mark.parametrize("raw", [b"[]", b'{"value":NaN}', b"invalid"])
def test_json_input_rejects_invalid_reports(raw):
    with pytest.raises(ValueError):
        module()._json_object(raw)
