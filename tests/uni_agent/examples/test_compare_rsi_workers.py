"""Synthetic CPU fixtures only; never production development evidence."""

import pytest

from examples.dsh.rsi_closed import compare_workers as compare


def episode(tag, reward):
    return {
        "reward": reward,
        "proof": {
            "uid": tag,
            "dsh_session_id": tag,
            "transfer_queue_key": tag,
            "receipt_sha256": "sha256:" + tag * 64,
            "model_tokens": 2,
        },
    }


@pytest.mark.parametrize(
    "parent,candidate,status", [([0, 0], [1, 0], "gain"), ([0, 0], [0, 0], "no-gain"), ([1, 0], [0, 1], "regression")]
)
def test_real_registry_shape_and_business_outcomes(parent, candidate, status):
    a = {
        case: episode(str(i + 1), reward)
        for i, (case, reward) in enumerate(zip(compare.prep.CASES, parent, strict=False))
    }
    b = {
        case: episode(str(i + 3), reward)
        for i, (case, reward) in enumerate(zip(compare.prep.CASES, candidate, strict=False))
    }
    result, verdict = compare.assemble("sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64, a, b, 10)
    assert verdict["outcome"] == status
    assert verdict["automatic_promotion"] is False
    assert set(result) == {"schema", "pins_sha256", "parent_sha256", "candidate_sha256", "cases"}


def test_duplicate_receipt_refused():
    a = {case: episode("1", 0) for case in compare.prep.CASES}
    with pytest.raises(ValueError, match="Duplicate"):
        compare.assemble("a", "b", "c", a, a, 10)


def test_unbound_manifest_refused(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        compare.load(path, "sha256:" + "0" * 64)


from tests.uni_agent.examples.test_prepare_rsi_worker_eval import parent_inputs  # noqa: E402,F401
from tests.uni_agent.examples.test_rsi_proposal_registration import proposal_run  # noqa: E402,F401


@pytest.mark.parametrize(
    "fault", [None, "sidecar-proof", "sidecar-extra", "candidate", "response", "budget", "missing-launch"]
)
def test_proposal_reaudit_matches_real_registry_without_writes(proposal_run, monkeypatch, fault):  # noqa: F811
    """Real Registry/parser/scorer; synthetic parent/raw episode and SDK boundary."""
    path, sha, sidecar, registry, ep, baseline = proposal_run
    registration = compare.registration
    registered = registration.register_verified_proposal(path, sha, sidecar)
    before = {p.name: p.read_bytes() for p in sidecar.parent.joinpath("registry").iterdir() if p.is_file()}
    manifest = compare.read(path)
    parent_path = compare.Path(manifest["parent_manifest"])
    monkeypatch.setattr(compare, "source_audit", lambda m: {"synthetic_cpu_source": True})
    if fault == "sidecar-proof":
        registered["proof"] = {"fake": True}
        sidecar.write_text(compare.json.dumps(registered))
    elif fault == "sidecar-extra":
        registered["self_attested"] = True
        sidecar.write_text(compare.json.dumps(registered))
    elif fault == "candidate":
        registered["candidate_sha256"] = registered["parent_candidate_sha256"]
        sidecar.write_text(compare.json.dumps(registered))
    elif fault == "response":
        ep["envelope"]["response"] += " "
    elif fault == "budget":
        manifest["wall_seconds"] += 1
        path.write_text(compare.json.dumps(manifest))
    elif fault == "missing-launch":
        compare.Path(manifest["run_root"]).joinpath("launch-manifest.json").unlink()

    def forbidden(*a, **k):
        raise AssertionError("Read-only comparison may not mutate Registry")

    for method in ("register", "promote", "rollback"):
        monkeypatch.setattr(type(registry), method, forbidden)
    call = lambda: compare.audit_proposal(
        path,
        compare.prep.digest(path),
        sidecar,
        compare.prep.digest(sidecar),
        parent_path,
        manifest["parent_manifest_sha256"],
        baseline,
        manifest["contract"]["diagnostics"],
    )
    if fault:
        with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
            call()
    else:
        candidate, _, _ = call()
        assert candidate["candidate_sha256"] == registered["candidate_sha256"]
    after = {p.name: p.read_bytes() for p in sidecar.parent.joinpath("registry").iterdir() if p.is_file()}
    assert before == after


@pytest.mark.parametrize("fault", [None, "launch", "config", "prompt", "missing-raw"])
def test_worker_reaudit_does_not_accept_receipts_without_raw_tokens(parent_inputs, monkeypatch, fault):  # noqa: F811
    """Real preparation, renderer, Registry, canonical receipt/result gate; no GPU."""
    from tests.uni_agent.examples.test_prepare_rsi_worker_eval import make_unit_results

    original_runtime = compare.prep.runtime_info
    monkeypatch.setattr(
        compare.prep,
        "runtime_info",
        lambda *a: {
            **original_runtime(*a),
            "module": str(compare.prep.ROOT / "examples/dsh/rsi_closed/worker_verifier.py"),
        },
    )
    manifest = compare.prep.prepare(**parent_inputs, mode="parent-baseline")
    path = parent_inputs["output_dir"] / "preparation-manifest.json"
    sha = compare.prep.digest(path)
    prepared = make_unit_results((parent_inputs, manifest, path, sha), "H0")
    run = prepared["run"]
    compare.prep.write_json(
        run / "launch-manifest.json",
        dict(
            schema="dsh.rsi-worker-launch.v1",
            mode="parent-baseline",
            prepared_manifest_sha256=sha,
            side="H0",
            command=manifest["sides"]["H0"]["command"],
            environment={
                **manifest["environment"],
                "RAY_TMPDIR": str(compare.Path("/tmp") / ("rsi-worker-" + compare.prep.canonical_hash(str(run))[7:19])),
            },
            wall_seconds=manifest["wall_seconds"],
        ),
    )
    compare.prep.write_json(run / "supervisor-result.json", {"exit_code": 0})
    monkeypatch.setattr(compare, "source_audit", lambda m: {"synthetic_cpu_source": True})
    if fault == "launch":
        (run / "launch-manifest.json").write_text("{}")
    elif fault in ("config", "prompt"):
        target = path.parent / "H0" / ("task.yaml" if fault == "config" else "eval.parquet")
        target.write_bytes(b"tampered")
    if fault is None:
        # Only raw episode loading is replaced in this integration slice. It is
        # independently exercised below with real NPZ/trace/receipt fixtures.
        monkeypatch.setattr(compare.registration, "audit_episode", lambda *a, **k: episode("1", 0))
        episodes, _ = compare.worker_side(path, sha, manifest, "H0")
        assert set(episodes) == set(compare.prep.CASES)
    else:
        with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
            compare.worker_side(path, sha, manifest, "H0")


@pytest.mark.parametrize("fault", [None, "npz", "readback", "trace"])
def test_existing_raw_auditor_remains_real(tmp_path, fault):
    from tests.uni_agent.examples.test_rsi_proposal_registration import actual_format_episode

    run, dump, metadata = actual_format_episode(tmp_path)
    if fault == "npz":
        (dump / "trajectory.npz").write_bytes(b"tampered")
    elif fault == "readback":
        path = run / "inference-evidence.json"
        evidence = compare.read(path)
        evidence["readback"]["scores"] = [0]
        path.write_text(compare.json.dumps(evidence))
    elif fault == "trace":
        next((run / "artifacts/traces").glob("*/session.jsonl")).write_text("{}")
    if fault:
        with pytest.raises(ValueError):
            compare.registration.audit_episode(run, metadata, max_tokens=2)
    else:
        assert compare.registration.audit_episode(run, metadata, max_tokens=2)["proof"]["model_tokens"] == 2


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}'])
def test_unknown_json_ambiguity_rejected(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        compare.load(path, compare.prep.digest(path))


@pytest.mark.parametrize("fault", [None, "old-module", "new-module", "sdk", "source"])
def test_distinct_audit_checkout_runtime_path_preserves_original_identity(monkeypatch, fault):
    relative = "examples/dsh/rsi_closed/worker_verifier.py"
    frozen = {"python": "/pin/python", "path": "/pin/dsh", "module": "/execution/" + relative, "sdk": "0.1.3a2"}
    actual = {**frozen, "module": str(compare.prep.ROOT / relative)}
    manifest = {
        "runtime": frozen,
        "environment": {"PYTHONPATH": "/execution:/execution/verl"},
        "sources": {relative: compare.prep.digest(compare.prep.ROOT / relative)},
    }
    if fault == "old-module":
        frozen["module"] = "/wrong/module.py"
    elif fault == "new-module":
        actual["module"] = "/wrong/module.py"
    elif fault == "sdk":
        actual["sdk"] = "different"
    elif fault == "source":
        manifest["sources"][relative] = "sha256:" + "0" * 64
    monkeypatch.setattr(compare.prep, "runtime_info", lambda *a: actual)
    if fault:
        with pytest.raises(ValueError):
            compare.runtime_audit(manifest)
    else:
        proof = compare.runtime_audit(manifest)
        assert proof["execution_runtime"]["module"] != proof["audit_runtime"]["module"]
        assert frozen["module"] == "/execution/" + relative


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "max_tokens",
        "per_turn",
        "model_files",
        "runtime",
        "sources",
        "pair_id",
        "duplicate-session",
        "wrong-candidate",
    ],
)
def test_total_comparison_binds_student_origin_and_two_actual_arms(proposal_run, parent_inputs, monkeypatch, fault):  # noqa: F811
    """Composition test: real proposal/Registry binding; explicit synthetic worker episodes."""
    path, sha, sidecar, registry, ep, baseline = proposal_run
    report = compare.registration.register_verified_proposal(path, sha, sidecar)
    ep["proof"].update(episode("5", 1)["proof"])
    report["proof"] = ep["proof"]
    sidecar.write_text(compare.json.dumps(report))
    args = {
        **parent_inputs,
        "output_dir": sidecar.parent / "paired",
        "run_root": sidecar.parent / "paired-run",
        "candidate_sha256": report["candidate_sha256"],
    }
    child = compare.prep.prepare(**args)
    child_path = args["output_dir"] / "preparation-manifest.json"
    parent_path = compare.Path(compare.read(path)["parent_manifest"])
    observed_sides = []

    def worker_fixture(path, sha, manifest, side):
        observed_sides.append((path, side))
        episodes = {
            case: episode(str(i + (1 if side == "H0" else 3)), i == 0 and side == "H1")
            for i, case in enumerate(compare.prep.CASES)
        }
        for value in episodes.values():
            value["reward"] = int(value["reward"])
        if fault == "duplicate-session" and side == "H1":
            episodes[compare.prep.CASES[0]]["proof"]["dsh_session_id"] = "1"
        return episodes, {"synthetic_cpu_fixture": True}

    monkeypatch.setattr(compare, "worker_side", worker_fixture)
    monkeypatch.setattr(compare, "source_audit", lambda m: {"synthetic_cpu_source": True})
    if fault in ("max_tokens", "per_turn"):
        child[fault] += 1
    elif fault in ("model_files", "runtime", "sources"):
        child[fault] = {}
    elif fault == "pair_id":
        child[fault] = "another-pair"
    elif fault == "wrong-candidate":
        child["candidate_sha256"] = report["parent_candidate_sha256"]
    child_path.write_text(compare.json.dumps(child))

    def forbidden(*a, **k):
        raise AssertionError("Unexpected Registry mutation")

    for method in ("register", "promote", "rollback"):
        monkeypatch.setattr(type(registry), method, forbidden)
    invoke = lambda: compare.compare(
        parent_path,
        compare.prep.digest(parent_path),
        child_path,
        compare.prep.digest(child_path),
        path,
        sha,
        sidecar,
        compare.prep.digest(sidecar),
    )
    if fault:
        with pytest.raises(ValueError):
            invoke()
    else:
        result = invoke()
        assert result["provenance"]["outcome"] == "gain"
        assert observed_sides == [(parent_path, "H0"), (child_path, "H1")]
        assert result["comparison"]["candidate_sha256"] == report["candidate_sha256"]
        assert (
            registry.load_active(baseline["parent_active_sha256"])["candidate_sha256"]
            == report["parent_candidate_sha256"]
        )


@pytest.mark.parametrize(
    "change",
    [
        "M\tdocs/report.md",
        "M\ttasks/run/handoff.md",
        "A\texamples/dsh/rsi_closed/compare_workers.py",
        "M\tuni_agent/framework/framework.py",
        "M\texamples/dsh/rsi_closed/compare_workers.py",
    ],
)
def test_source_audit_allows_documentation_but_refuses_execution_changes(monkeypatch, change):
    """Real Git show and on-disk dependency byte checks; only diff listing is a test double."""
    from types import SimpleNamespace

    state = {
        "integration": compare.prep.git_state(compare.prep.ROOT),
        "verl": compare.prep.git_state(compare.prep.ROOT / "verl"),
    }
    manifest = {
        "checkout": state,
        "sources": {p: compare.prep.digest(compare.prep.ROOT / p) for p in compare.prep.SOURCES},
    }
    monkeypatch.setattr(compare.prep, "check_verl_source", lambda m: None)
    monkeypatch.setattr(compare, "check_controller_source", lambda: None)
    original = compare.subprocess.run

    def git_command(command, **kwargs):
        if command[:3] == ["git", "diff", "--name-status"]:
            return SimpleNamespace(stdout=change + "\n")
        return original(command, **kwargs)

    monkeypatch.setattr(compare.subprocess, "run", git_command)
    if change.startswith("M\tuni_agent") or change == "M\texamples/dsh/rsi_closed/compare_workers.py":
        with pytest.raises(ValueError, match="drift"):
            compare.source_audit(manifest)
    else:
        report = compare.source_audit(manifest)
        assert report["execution_checkout"] == state
        assert report["audit_checkout"] == state


@pytest.mark.parametrize("fault", [None, "dirty", "untracked"])
def test_controller_must_match_actual_committed_git_bytes(tmp_path, monkeypatch, fault):
    """An actual temporary Git repository; no Git/source-check mocks."""
    root = tmp_path / "audit"
    root.mkdir()
    relative = "examples/dsh/rsi_closed/compare_workers.py"
    controller = root / relative
    controller.parent.mkdir(parents=True)
    controller.write_text("# synthetic CPU controller source\n")
    (root / "anchor.txt").write_text("synthetic repository\n")

    def git(*args):
        return compare.subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init")
    git("add", "anchor.txt")
    if fault != "untracked":
        git("add", relative)
    git("-c", "user.name=CPU Test", "-c", "user.email=cpu@example.invalid", "commit", "-m", "synthetic test fixture")
    if fault == "dirty":
        controller.write_text("# changed\n")
    monkeypatch.setattr(compare.prep, "ROOT", root)
    monkeypatch.setattr(compare, "__file__", str(controller))
    if fault:
        with pytest.raises((ValueError, compare.subprocess.CalledProcessError)):
            compare.check_controller_source()
    else:
        compare.check_controller_source()
        (root / "docs").mkdir()
        (root / "docs/report.md").write_text("new non-executable report")
        compare.check_controller_source()
