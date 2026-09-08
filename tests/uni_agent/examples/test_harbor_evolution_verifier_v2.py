import json

import pytest

from examples.harbor.evolution_verifier import run_verifier as run_v1
from examples.harbor.evolution_verifier_v2 import run_verifier
from tests.uni_agent.examples.test_harbor_evolution_verifier import evidence
from tests.uni_agent.tasks.test_harbor_evolution_scoring_v2 import case as v2_case
from uni_agent.tasks.harbor_dsh.trace_artifacts import validate_evolution_binding


@pytest.fixture
def case(tmp_path):
    return v2_case.__wrapped__(tmp_path)


@pytest.mark.parametrize("variant, reward", [("correct", 1.0), ("partial", 0.25), ("policy_failure", 0.0)])
def test_fixed_v2_cli_and_bridge_preserve_admission(case, tmp_path, variant, reward):
    if variant == "partial":
        del case["events"][8:10]
    elif variant == "policy_failure":
        del case["events"][2:4]
    args = evidence(case, tmp_path)
    binding = validate_evolution_binding((args["input_dir"] / "evolution-binding.json").read_bytes())
    assert binding.kind == "evolution-v2-lifecycle-admission-v2"
    report = run_verifier(**args)
    assert report["reward"] == reward
    assert float((args["output_dir"] / "reward.txt").read_text()) == reward
    assert json.loads((args["output_dir"] / "evolution-v2-report.json").read_text()) == report
    with pytest.raises(ValueError):
        run_verifier(**args)


@pytest.mark.parametrize("bad", ["v1_lane", "bundle", "source", "unsafe", "missing_result", "status", "kind"])
def test_v2_rejects_mixed_or_untrusted_evidence(case, tmp_path, bad):
    if bad == "unsafe":
        case["events"][0]["data"]["arguments"] = json.dumps({"command": "edit"})
    elif bad == "missing_result":
        del case["events"][2:4]
        del case["events"][1]
    args = evidence(case, tmp_path)
    if bad in {"bundle", "source", "kind"}:
        path = args["input_dir"] / "evolution-binding.json"
        obj = json.loads(path.read_text())
        if bad == "bundle":
            obj["verifier_bundle_sha256"] = "sha256:" + "0" * 64
        elif bad == "source":
            obj["source_sha256s"].pop("examples/dsh/evolution_verifier_v2.py")
        else:
            obj["kind"] = "evolution-v2-lifecycle-v1"
        path.write_text(json.dumps(obj))
    elif bad == "status":
        path = args["input_dir"] / "status.json"
        obj = json.loads(path.read_text())
        obj["finished"] = False
        path.write_text(json.dumps(obj))
    with pytest.raises(ValueError):
        (run_v1 if bad == "v1_lane" else run_verifier)(**args)
    assert not (args["output_dir"] / "reward.txt").exists()
