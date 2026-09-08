import json
import subprocess
import sys

import pytest

from uni_agent.tasks.dsh.memory_artifacts import _sha
from uni_agent.tasks.dsh.rsi_candidates import Registry, initialize

pytestmark = [pytest.mark.cpu, pytest.mark.level0]


def spec(tools):
    return {"schema": "dsh.rsi-profile.v1", "profile": "sdk-minimal", "allowed_tools": tools}


@pytest.fixture
def setup_registry(tmp_path):
    pins = {
        key: _sha(key.encode())
        for key in ["model_sha256", "runtime_sha256", "base_harness_sha256", "devset_sha256", "verifier_sha256"]
    }
    pins.update(case_ids=["case-a", "case-b"], max_tokens=4096, evolution_run_id="rsi-test-1")
    initial = initialize(tmp_path / "registry", spec(["str_replace_editor"]), pins)
    registry = Registry(tmp_path / "registry", initial["pins_sha256"])
    child = registry.register(spec(["cordis_inspect_list", "str_replace_editor"]), initial["candidate_sha256"])
    receipt = {
        "schema": "dsh.rsi-development-comparison.v1",
        "pins_sha256": initial["pins_sha256"],
        "parent_sha256": initial["candidate_sha256"],
        "candidate_sha256": child,
        "cases": [
            {
                "case_id": name,
                "parent": {
                    "finished": True,
                    "eligible": True,
                    "reward": 0.0,
                    "tokens": 100,
                    "receipt_sha256": _sha((name + "-parent").encode()),
                },
                "candidate": {
                    "finished": True,
                    "eligible": True,
                    "reward": 1.0,
                    "tokens": 120,
                    "receipt_sha256": _sha((name + "-child").encode()),
                },
            }
            for name in pins["case_ids"]
        ],
    }
    return registry, initial, child, receipt, tmp_path


def promote(setup, receipt=None, active=None):
    registry, initial, child, default, root = setup
    raw = json.dumps(default if receipt is None else receipt).encode()
    path = root / "comparison.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    return registry.promote(child, path, _sha(raw), initial["active_sha256"] if active is None else active)


def test_promotion_fresh_process_load_and_real_rollback(setup_registry):
    registry, initial, child, _, _ = setup_registry
    promoted = promote(setup_registry)
    value = registry.load_active(promoted["active_sha256"])
    assert value["candidate_sha256"] == child
    code = (
        "import json,sys;from pathlib import Path;"
        "from uni_agent.tasks.dsh.rsi_candidates import Registry;"
        "print(json.dumps(Registry(Path(sys.argv[1]),sys.argv[2]).load_active(sys.argv[3])))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(registry.root), initial["pins_sha256"], promoted["active_sha256"]],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["candidate_sha256"] == child
    restored = registry.rollback(promoted["active_sha256"])
    assert registry.load_active(restored["active_sha256"])["candidate_sha256"] == initial["candidate_sha256"]
    assert restored["active_sha256"] != initial["active_sha256"]
    assert registry.load_active(restored["active_sha256"])["spec"]["allowed_tools"] == ["str_replace_editor"]
    fresh_restored = subprocess.run(
        [sys.executable, "-c", code, str(registry.root), initial["pins_sha256"], restored["active_sha256"]],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(fresh_restored.stdout)["candidate_sha256"] == initial["candidate_sha256"]


@pytest.mark.parametrize(
    "mutation",
    [
        "regression",
        "no_gain",
        "unfinished",
        "ineligible",
        "nan",
        "bool",
        "budget",
        "case",
        "duplicate",
        "shared_receipt",
        "parent",
        "pins",
    ],
)
def test_reject_bad_development_evidence(setup_registry, mutation):
    registry, initial, _, receipt, _ = setup_registry
    candidate = receipt["cases"][0]["candidate"]
    if mutation == "regression":
        receipt["cases"][0]["parent"]["reward"] = 1
        candidate["reward"] = 0
    elif mutation == "no_gain":
        for case in receipt["cases"]:
            case["candidate"]["reward"] = 0
    elif mutation == "unfinished":
        candidate["finished"] = False
    elif mutation == "ineligible":
        candidate["eligible"] = False
    elif mutation == "nan":
        candidate["reward"] = float("nan")
    elif mutation == "bool":
        candidate["reward"] = True
    elif mutation == "budget":
        candidate["tokens"] = 4097
    elif mutation == "case":
        receipt["cases"].pop()
    elif mutation == "duplicate":
        receipt["cases"][1]["case_id"] = receipt["cases"][0]["case_id"]
    elif mutation == "shared_receipt":
        candidate["receipt_sha256"] = receipt["cases"][0]["parent"]["receipt_sha256"]
    elif mutation == "parent":
        receipt["parent_sha256"] = _sha(b"wrong")
    else:
        receipt["pins_sha256"] = _sha(b"wrong")
    with pytest.raises((ValueError, RuntimeError)):
        promote(setup_registry, receipt)
    assert registry.load_active(initial["active_sha256"])["candidate_sha256"] == initial["candidate_sha256"]


def test_stale_active_and_wrong_receipt_hash(setup_registry):
    registry, initial, child, _, root = setup_registry
    promoted = promote(setup_registry)
    with pytest.raises(ValueError):
        promote(setup_registry)
    with pytest.raises(ValueError):
        registry.promote(child, root / "comparison.json", _sha(b"wrong"), promoted["active_sha256"])
    assert registry.load_active(promoted["active_sha256"])["candidate_sha256"] == child
    with pytest.raises(ValueError):
        registry.load_active(initial["active_sha256"])


@pytest.mark.parametrize(
    "bad",
    [
        spec(["bash"]),
        {**spec(["str_replace_editor"]), "code": "malicious"},
        {**spec(["str_replace_editor"]), "dataset": "/secret"},
        spec(["str_replace_editor", "str_replace_editor"]),
    ],
)
def test_candidate_is_declarative_only(setup_registry, bad):
    registry, initial, _, _, _ = setup_registry
    with pytest.raises(ValueError):
        registry.register(bad, initial["candidate_sha256"])


def test_no_model_promote_or_symlink_receipt(setup_registry):
    registry, initial, child, _, root = setup_registry
    path = root / "model.json"
    path.write_text('{"status":"promote"}')
    path.chmod(0o600)
    with pytest.raises(ValueError):
        registry.promote(child, path, _sha(path.read_bytes()), initial["active_sha256"])
    link = root / "alias.json"
    link.symlink_to(path)
    with pytest.raises((ValueError, OSError)):
        registry.promote(child, link, _sha(path.read_bytes()), initial["active_sha256"])


def test_receipt_cannot_replay_after_rollback(setup_registry):
    registry, _, _, _, _ = setup_registry
    promoted = promote(setup_registry)
    restored = registry.rollback(promoted["active_sha256"])
    with pytest.raises(ValueError, match="reused"):
        promote(setup_registry, active=restored["active_sha256"])


def test_registry_pins_and_candidate_tamper_rejected(setup_registry):
    registry, initial, child, _, _ = setup_registry
    candidate_path = registry.root / (child[7:] + ".json")
    original = candidate_path.read_bytes()
    candidate_path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="hash"):
        promote(setup_registry)
    candidate_path.write_bytes(original)
    pins = registry.root / "pins.json"
    pins.write_bytes(pins.read_bytes() + b" ")
    with pytest.raises(ValueError, match="pins hash"):
        registry.load_active(initial["active_sha256"])


def test_symlink_registry_and_hardlinked_receipt_rejected(setup_registry):
    import os

    registry, initial, child, receipt, root = setup_registry
    alias = root / "registry-alias"
    alias.symlink_to(registry.root, target_is_directory=True)
    with pytest.raises(OSError):
        Registry(alias, initial["pins_sha256"]).load_active(initial["active_sha256"])
    raw = json.dumps(receipt).encode()
    first, second = root / "first.json", root / "second.json"
    first.write_bytes(raw)
    first.chmod(0o600)
    os.link(first, second)
    with pytest.raises(ValueError, match="single-link"):
        registry.promote(child, first, _sha(raw), initial["active_sha256"])


def test_failed_atomic_replace_preserves_active(setup_registry, monkeypatch):
    import os

    registry, initial, _, _, _ = setup_registry

    def failure(*args, **kwargs):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(os, "replace", failure)
    with pytest.raises(OSError, match="simulated"):
        promote(setup_registry)
    assert registry.load_active(initial["active_sha256"])["candidate_sha256"] == initial["candidate_sha256"]


def test_private_registry_mode_and_reuse(setup_registry):
    registry, initial, _, _, _ = setup_registry
    pins = json.loads((registry.root / "pins.json").read_text())
    with pytest.raises(FileExistsError):
        initialize(registry.root, spec(["str_replace_editor"]), pins)
    registry.root.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        registry.load_active(initial["active_sha256"])


def test_repacked_old_episode_receipts_cannot_promote(setup_registry):
    registry, _, _, receipt, _ = setup_registry
    promoted = promote(setup_registry)
    restored = registry.rollback(promoted["active_sha256"])
    receipt["cases"].reverse()
    with pytest.raises(ValueError, match="episode receipt reused"):
        promote(setup_registry, receipt, active=restored["active_sha256"])


def test_concurrent_promotion_compare_and_swap(setup_registry):
    from concurrent.futures import ThreadPoolExecutor

    registry, initial, child, receipt, root = setup_registry
    raw = json.dumps(receipt).encode()
    path = root / "fixed-comparison.json"
    path.write_bytes(raw)
    path.chmod(0o600)

    def attempt():
        try:
            return registry.promote(child, path, _sha(raw), initial["active_sha256"])
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert any(isinstance(result, str) and "compare-and-swap" in result for result in results)


def test_mixed_registry_candidate_identity_cannot_load(setup_registry):
    registry, initial, child, _, root = setup_registry
    pins = json.loads((registry.root / "pins.json").read_text())
    pins["evolution_run_id"] = "other-run"
    other_root = root / "other-registry"
    other = initialize(other_root, spec(["str_replace_editor"]), pins)
    source = registry.root / (child[7:] + ".json")
    target = other_root / source.name
    target.write_bytes(source.read_bytes())
    target.chmod(0o600)
    with pytest.raises(ValueError, match="identity mismatch"):
        Registry(other_root, other["pins_sha256"]).register(spec(["cordis_inspect_list"]), child)
    assert registry.load_active(initial["active_sha256"])["candidate_sha256"] == initial["candidate_sha256"]


def test_load_registered_is_readonly_bound_to_real_parent(setup_registry):
    registry, initial, child, _, _ = setup_registry
    before = {p.name: p.read_bytes() for p in registry.root.iterdir()}
    value = registry.load_registered(child, initial["active_sha256"])
    assert value["phase"] == "candidate-evaluation"
    assert value["candidate_sha256"] == child
    assert value["parent_candidate_sha256"] == initial["candidate_sha256"]
    assert value["parent_active_sha256"] == initial["active_sha256"]
    assert value["pins_sha256"] == initial["pins_sha256"]
    assert value["promoted"] is False
    assert value["runtime_deployed"] is False
    assert "active_sha256" not in value
    assert before == {p.name: p.read_bytes() for p in registry.root.iterdir()}


@pytest.mark.parametrize("fault", ["pins", "tamper", "stale", "parent", "already-active"])
def test_load_registered_rejects_invalid_snapshot(setup_registry, fault):
    registry, initial, child, _, _ = setup_registry
    active = initial["active_sha256"]
    if fault == "pins":
        registry = Registry(registry.root, _sha(b"wrong"))
    elif fault == "tamper":
        (registry.root / (child[7:] + ".json")).write_text("{}")
    elif fault == "stale":
        promote(setup_registry)
    elif fault == "parent":
        child = registry.register(spec(["cordis_inspect_list"]), child)
    else:
        child = initial["candidate_sha256"]
    before = {p.name: p.read_bytes() for p in registry.root.iterdir()}
    with pytest.raises(ValueError):
        registry.load_registered(child, active)
    assert before == {p.name: p.read_bytes() for p in registry.root.iterdir()}
