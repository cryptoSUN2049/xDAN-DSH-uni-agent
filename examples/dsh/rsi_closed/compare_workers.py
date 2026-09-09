"""Read-only, bounded comparison of real H0/H1 workers and registered student P."""

import argparse
import json
import math
import subprocess
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from examples.dsh.rsi_closed import prepare_worker_eval as prep
from examples.dsh.rsi_closed import proposal
from examples.dsh.rsi_closed import proposal_registration as registration
from examples.dsh.rsi_closed.launch_worker_eval import _live_inputs, result_binding
from examples.dsh.rsi_closed.profile import build_patch
from uni_agent.tasks.dsh.rsi_candidates import Registry, _comparison, _digest


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def read(path):
    def invalid(value):
        raise ValueError("Non-finite JSON value: " + value)

    return json.loads(Path(path).read_text(), object_pairs_hook=_pairs, parse_constant=invalid)


def load(path, sha):
    if prep.digest(path) != sha:
        raise ValueError("External manifest hash mismatch")
    return read(path)


def assemble(pins_sha, parent_sha, candidate_sha, parents, candidates, max_tokens):
    """No selection writes. Business rejection is an ordinary, truthful result."""
    if set(parents) != set(prep.CASES) or set(candidates) != set(prep.CASES):
        raise ValueError("Incomplete/unknown comparison cases")
    seen = {key: set() for key in ("uid", "dsh_session_id", "transfer_queue_key", "receipt_sha256")}
    cases, gains = [], []
    for case_id in prep.CASES:
        case = {"case_id": case_id}
        for arm, episodes in (("parent", parents), ("candidate", candidates)):
            episode = episodes[case_id]
            proof = episode["proof"]
            for key, used in seen.items():
                if not proof[key] or proof[key] in used:
                    raise ValueError("Duplicate/missing worker " + key)
                used.add(proof[key])
            _digest(proof["receipt_sha256"])
            reward, tokens = episode["reward"], proof["model_tokens"]
            if type(reward) not in (int, float) or not math.isfinite(reward) or reward not in (0, 1):
                raise ValueError("Invalid worker business reward")
            if type(tokens) is not int or not 0 < tokens <= max_tokens:
                raise ValueError("Invalid actual worker token budget")
            case[arm] = dict(
                finished=True, eligible=True, reward=reward, tokens=tokens, receipt_sha256=proof["receipt_sha256"]
            )
        gain = case["candidate"]["reward"] - case["parent"]["reward"]
        gains.append({"case_id": case_id, "gain": gain})
        cases.append(case)
    comparison = dict(
        schema="dsh.rsi-development-comparison.v1",
        pins_sha256=pins_sha,
        parent_sha256=parent_sha,
        candidate_sha256=candidate_sha,
        cases=cases,
    )
    outcome = (
        "regression"
        if any(item["gain"] < 0 for item in gains)
        else "gain"
        if sum(item["gain"] for item in gains) > 0
        else "no-gain"
    )
    verdict = dict(outcome=outcome, gains=gains, automatic_promotion=False, promoted=False, training=False)
    if outcome == "gain":
        _comparison(comparison, pins_sha, candidate_sha, parent_sha, {"case_ids": prep.CASES, "max_tokens": max_tokens})
    return comparison, verdict


def check_controller_source():
    relative = "examples/dsh/rsi_closed/compare_workers.py"
    if Path(__file__).resolve() != (prep.ROOT / relative).resolve():
        raise ValueError("Controller loaded outside audit checkout")
    committed = subprocess.run(
        ["git", "show", "HEAD:" + relative], cwd=prep.ROOT, check=True, capture_output=True, timeout=15
    ).stdout
    if committed != Path(__file__).read_bytes():
        raise ValueError("Commit controller source before auditing production evidence")


def source_audit(manifest):
    """Keep execution HEAD intact; only the new audit controller may extend code."""
    check_controller_source()
    prep.checked_files(prep.ROOT, manifest["sources"])
    prep.check_verl_source(manifest)
    checkout = {"integration": prep.git_state(prep.ROOT), "verl": prep.git_state(prep.ROOT / "verl")}
    if checkout["verl"] != manifest["checkout"]["verl"]:
        raise ValueError("Audit VERL checkout differs from execution")
    old, new = manifest["checkout"]["integration"]["head"], checkout["integration"]["head"]
    changed = subprocess.run(
        ["git", "diff", "--name-status", old, new, "--"],
        cwd=prep.ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout
    additions = {"examples/dsh/rsi_closed/compare_workers.py", "tests/uni_agent/examples/test_compare_rsi_workers.py"}
    for line in changed.splitlines():
        status, name = line.split("\t", 1)
        if name.startswith(("docs/", "tasks/")):
            continue
        if status != "A" or name not in additions:
            raise ValueError("Unapproved audit execution-source drift: " + name)
    # Include the raw auditor and proposal parser dependencies, even if not all are
    # present in a worker's narrower execution inventory.
    dependencies = [
        "examples/dsh/ops/audit_qwen3_4b_online_rl.py",
        "examples/dsh/rsi_closed/proposal_registration.py",
        "examples/dsh/rsi_closed/proposal.py",
    ]
    for relative in dependencies:
        original = subprocess.run(
            ["git", "show", f"{old}:{relative}"], cwd=prep.ROOT, check=True, capture_output=True, timeout=15
        ).stdout
        if original != (prep.ROOT / relative).read_bytes():
            raise ValueError("Audit dependency differs from original execution: " + relative)
    return {
        "execution_checkout": manifest["checkout"],
        "audit_checkout": checkout,
        "execution_sources": manifest["sources"],
        "audit_sources": {
            relative: prep.digest(prep.ROOT / relative)
            for relative in dependencies + sorted(additions)
            if (prep.ROOT / relative).is_file()
        },
    }


def _inventory(path, manifest):
    actual = {str(p.relative_to(path.parent)) for p in path.parent.rglob("*") if p.is_file() and p != path}
    if actual != set(manifest["files"]):
        raise ValueError("Preparation file inventory mismatch")
    prep.checked_files(path.parent, manifest["files"])


def _command(manifest, data, run, *, proposal_run=False):
    command = prep.command_for(data, run, manifest["runtime"]["python"], Path(manifest["model_path"]))
    # Preserve the real execution checkout's absolute path, never relabel it as audit HEAD.
    root = Path(manifest["environment"]["PYTHONPATH"].split(":")[0])
    if not root.is_absolute() or manifest["environment"] != {
        "DSH_RUNTIME_MODE": "exe",
        "PYTHONPATH": f"{root}:{root / 'verl'}",
    }:
        raise ValueError("Invalid execution environment")
    command[1] = str(root / "examples/inference/parallel_infer_verl.py")
    if proposal_run:
        command[command.index("--limit") + 1] = "1"
    return command


def _supervised(run, expected):
    if read(run / "launch-manifest.json") != expected:
        raise ValueError("Actual launch differs from frozen command/budget")
    result = read(run / "supervisor-result.json")
    if type(result.get("exit_code")) is not int or result["exit_code"] != 0:
        raise ValueError("Supervisor failed or incomplete")
    return {
        "launch_manifest_sha256": prep.digest(run / "launch-manifest.json"),
        "supervisor_result_sha256": prep.digest(run / "supervisor-result.json"),
    }


def runtime_audit(manifest):
    frozen = manifest["runtime"]
    actual = prep.runtime_info(frozen["python"], frozen["path"])
    relative = "examples/dsh/rsi_closed/worker_verifier.py"
    execution_root = Path(manifest["environment"]["PYTHONPATH"].split(":")[0])
    if (
        frozen.get("module") != str(execution_root / relative)
        or actual.get("module") != str(prep.ROOT / relative)
        or {k: v for k, v in actual.items() if k != "module"} != {k: v for k, v in frozen.items() if k != "module"}
        or prep.digest(prep.ROOT / relative) != manifest["sources"][relative]
    ):
        raise ValueError("Runtime/verifier identity changed")
    return {"execution_runtime": frozen, "audit_runtime": actual}


def worker_side(path, sha, manifest, side):
    _inventory(path, manifest)
    _live_inputs(manifest, path.parent, side)
    source = source_audit(manifest)
    runtime = manifest["runtime"]
    runtime_proof = runtime_audit(manifest)
    if prep.model_files(manifest["model_path"]) != manifest["model_files"]:
        raise ValueError("Runtime/model bytes changed")
    rows = pq.read_table(path.parent / side / "eval.parquet").to_pylist()
    frozen, files = prep.frozen_cases(manifest["cases_root"])
    if files != manifest["case_files"]:
        raise ValueError("Frozen case inventory changed")
    item = manifest["sides"][side]
    for row, original in zip(rows, frozen, strict=True):
        expected_meta = {
            **original["metadata"],
            "rsi_pair_id": manifest["pair_id"],
            "rsi_side": side,
            "rsi_evaluation_mode": manifest["mode"],
            "rsi_parent_active_sha256": manifest["parent_active_sha256"],
            "rsi_candidate_sha256": item["selection"]["candidate_sha256"],
            "rsi_content_sha256": item["selection"]["content_sha256"],
            "rsi_overlay_sha256": item["overlay_sha256"],
            "rsi_policy_sha256": prep.POLICY_SHA256,
        }
        if row["prompt"] != original["messages"] or row["extra_info"]["tools_kwargs"]["task"] != {
            "name": "dsh_architecture",
            "metadata": expected_meta,
        }:
            raise ValueError("Worker prompt/metadata differs from fixed case")
    run = Path(item["run_root"])
    command = _command(manifest, path.parent / side, run)
    if command != item["command"]:
        raise ValueError("Worker strict command mismatch")
    config = yaml.safe_load((path.parent / side / "task.yaml").read_text())[0]
    expected_config = yaml.safe_load((prep.ROOT / "examples/dsh/evolution_task_config_v3_live.yaml").read_text())[0]
    expected_config.update(
        environment_digest=prep.RUNTIME_SHA256,
        verifier_id=prep.VERIFIER_ID,
        verifier_version="1",
        verifier_code_digest=prep.bundle_digest(),
        workdir=manifest["cases_root"],
        result_root=str(run / "artifacts/results"),
        verifier_command=[runtime["python"], "-m", prep.MODULE],
    )
    expected_config["agent"].update(
        runner_python=runtime["python"],
        default_workdir=manifest["cases_root"],
        patches=[str(path.parent / side / "overlay.json")],
        profile="sdk-minimal",
        run_timeout=manifest["wall_seconds"],
    )
    expected_config["agent"]["model"].update(
        max_total_tokens=manifest["max_tokens"], max_tokens_per_turn=manifest["per_turn"]
    )
    if config != expected_config:
        raise ValueError("Worker task configuration/budget mismatch")
    environment = {
        **manifest["environment"],
        "RAY_TMPDIR": str(Path("/tmp") / ("rsi-worker-" + prep.canonical_hash(str(run))[7:19])),
    }
    launch = _supervised(
        run,
        dict(
            schema="dsh.rsi-worker-launch.v1",
            mode=manifest["mode"],
            prepared_manifest_sha256=sha,
            side=side,
            command=command,
            environment=environment,
            wall_seconds=manifest["wall_seconds"],
        ),
    )
    result_binding(dict(manifest=manifest, run=run, rows=rows), side)
    episodes = {
        row["extra_info"]["tools_kwargs"]["task"]["metadata"]["task_id"].rsplit("/", 1)[-1]: registration.audit_episode(
            run, row["extra_info"]["tools_kwargs"]["task"]["metadata"], max_tokens=manifest["max_tokens"]
        )
        for row in rows
    }
    return episodes, {"source": source, "runtime": runtime_proof, **launch}


def audit_proposal(path, sha, sidecar_path, sidecar_sha, parent_path, parent_sha, baseline, diagnostics):
    manifest, sidecar = load(path, sha), load(sidecar_path, sidecar_sha)
    if manifest.get("schema") != "dsh.rsi-proposal-preparation.v1" or set(manifest["sources"]) != {
        "examples/dsh/rsi_closed/proposal_registration.py",
        "examples/dsh/rsi_closed/proposal.py",
    }:
        raise ValueError("Proposal schema/source inventory mismatch")
    source = source_audit(manifest)
    _inventory(path, manifest)
    if manifest["parent_manifest"] != str(parent_path) or manifest["parent_manifest_sha256"] != parent_sha:
        raise ValueError("Proposal belongs to another baseline")
    contract = read(path.parent / "contract.json")
    proposal.validate_contract(contract)
    if (
        contract != manifest["contract"]
        or contract["diagnostics"] != diagnostics
        or read(path.parent / "diagnostics.json") != diagnostics
    ):
        raise ValueError("Proposal original parent diagnostics mismatch")
    registry = Registry(baseline["registry_root"], baseline["pins_sha256"])
    active = registry.load_active(baseline["parent_active_sha256"])
    with registry._locked() as (_, pins):
        if (
            contract["pins_sha256"] != baseline["pins_sha256"]
            or contract["model_sha256"] != pins["model_sha256"]
            or contract["worker_devset_sha256"] != pins["devset_sha256"]
            or contract["pair_id"] != pins["evolution_run_id"]
            or contract["parent_active_sha256"] != baseline["parent_active_sha256"]
            or contract["parent_candidate_sha256"] != active["candidate_sha256"]
            or contract["parent_spec"] != active["spec"]
        ):
            raise ValueError("Proposal pins/parent mismatch")
    render = build_patch(
        baseline["registry_root"],
        baseline["pins_sha256"],
        baseline["parent_active_sha256"],
        [path.parent / "diagnostics.json"],
    )
    if render != manifest["render"] or prep.digest(path.parent / "overlay.json") != prep.canonical_hash(
        render["patch"]
    ):
        raise ValueError("Proposal overlay changed")
    metadata = manifest["metadata"]
    expected_metadata = dict(
        task_id="dsh/rsi-proposal/" + baseline["pair_id"],
        task_version="1",
        verifier_id=proposal.VERIFIER_ID,
        verifier_version="1",
        verifier_code_digest=proposal.bundle_digest(),
        environment_digest=proposal.RUNTIME_SHA256,
        fixture_path=str(path.parent / "contract.json"),
        fixture_sha256=prep.digest(path.parent / "contract.json"),
        split="validation",
        dataset_role="development",
        phase="proposal",
    )
    rows = pq.read_table(path.parent / "eval.parquet").to_pylist()
    if (
        metadata != expected_metadata
        or len(rows) != 1
        or rows[0]["prompt"] != contract["messages"]
        or rows[0]["extra_info"]["tools_kwargs"]["task"] != {"name": "dsh_architecture", "metadata": metadata}
    ):
        raise ValueError("Proposal original row/metadata mismatch")
    run = Path(manifest["run_root"])
    command = _command(baseline, path.parent, run, proposal_run=True)
    if (
        manifest["command"] != command
        or manifest["environment"] != baseline["environment"]
        or manifest["wall_seconds"] != baseline["wall_seconds"]
    ):
        raise ValueError("Proposal command/environment/budget mismatch")
    config = yaml.safe_load((parent_path.parent / "H0/task.yaml").read_text())[0]
    config.update(
        verifier_id=proposal.VERIFIER_ID,
        verifier_code_digest=proposal.bundle_digest(),
        verifier_command=[baseline["runtime"]["python"], "-m", "examples.dsh.rsi_closed.proposal"],
        workdir=str(path.parent),
        result_root=str(run / "artifacts/results"),
    )
    config["agent"].update(patches=[str(path.parent / "overlay.json")], default_workdir=str(path.parent))
    if yaml.safe_load((path.parent / "task.yaml").read_text()) != [config]:
        raise ValueError("Proposal task configuration mismatch")
    launch = _supervised(
        run,
        dict(
            schema="dsh.rsi-proposal-launch.v1",
            prepared_manifest_sha256=sha,
            command=command,
            environment=manifest["environment"],
            wall_seconds=manifest["wall_seconds"],
        ),
    )
    if len(read(run / "inference-evidence.json")["samples"]) != 1:
        raise ValueError("Require unique proposal attempt")
    episode = registration.audit_episode(run, metadata, max_tokens=baseline["max_tokens"])
    patch_paths = json.dumps([str(path.parent / "overlay.json")], ensure_ascii=False, separators=(",", ":")).encode()
    if episode["envelope"]["dsh"].get("profile") != "sdk-minimal" or episode["envelope"]["dsh"].get(
        "patches_sha256"
    ) != proposal.parent._sha256_bytes(patch_paths):
        raise ValueError("Proposal actual SDK policy mismatch")
    scored = proposal.score(contract, episode["envelope"], episode["events"])
    if scored["eligible"] is not True or scored["reward"] != 1 or episode["reward"] != 1:
        raise ValueError("Proposal raw receipt/score mismatch")
    parsed = proposal.parse_response(episode["envelope"]["response"], active["spec"])
    candidate = registry.load_registered(sidecar["candidate_sha256"], baseline["parent_active_sha256"])
    if parsed["spec"] != candidate["spec"] or parsed["content_sha256"] != candidate["content_sha256"]:
        raise ValueError("Registered candidate differs from original student proposal")
    expected_sidecar = dict(
        schema="dsh.rsi-student-registration.v1",
        proposal_manifest_sha256=sha,
        parent_active_sha256=baseline["parent_active_sha256"],
        candidate_sha256=candidate["candidate_sha256"],
        parent_candidate_sha256=active["candidate_sha256"],
        diagnostics_sha256=contract["diagnostics_sha256"],
        model_sha256=contract["model_sha256"],
        runtime_sha256=contract["runtime_sha256"],
        proof=episode["proof"],
        **launch,
        **parsed,
        promoted=False,
        training=False,
    )
    if sidecar != expected_sidecar:
        raise ValueError("Original student registration sidecar mismatch")
    return candidate, episode, source


def compare(
    parent_manifest,
    parent_sha256,
    candidate_manifest,
    candidate_sha256,
    proposal_manifest,
    proposal_sha256,
    registration_path,
    registration_sha256,
):
    paths = [Path(p).absolute() for p in (parent_manifest, candidate_manifest, proposal_manifest, registration_path)]
    hashes = [parent_sha256, candidate_sha256, proposal_sha256, registration_sha256]
    parent_path, child_path, proposal_path, sidecar_path = paths
    baseline, child = load(parent_path, parent_sha256), load(child_path, candidate_sha256)
    if (
        baseline.get("schema") != "dsh.rsi-worker-evaluation.v1"
        or child.get("schema") != baseline["schema"]
        or baseline.get("mode") != "parent-baseline"
        or child.get("mode") != "paired"
    ):
        raise ValueError("Require independent baseline H0 and paired H1")
    shared = (
        "pair_id",
        "pins_sha256",
        "parent_active_sha256",
        "registry_root",
        "cases_root",
        "case_files",
        "model_path",
        "model_files",
        "runtime",
        "max_tokens",
        "per_turn",
        "wall_seconds",
        "sources",
        "checkout",
        "environment",
        "verl_effective_source",
    )
    for key in shared:
        if baseline[key] != child[key]:
            raise ValueError("Worker comparison drift: " + key)
    registry = Registry(baseline["registry_root"], baseline["pins_sha256"])
    active = registry.load_active(baseline["parent_active_sha256"])
    expected_pins = prep._input_pins(
        baseline["case_files"], baseline["model_files"], baseline["pair_id"], baseline["max_tokens"], active["spec"]
    )
    with registry._locked() as (_, pins):
        if pins != expected_pins:
            raise ValueError("Comparison Registry pins mismatch")
    parents, parent_proof = worker_side(parent_path, parent_sha256, baseline, "H0")
    _, diagnostics = registration.audit_parent(parent_path, parent_sha256)
    candidate, p_episode, p_source = audit_proposal(
        proposal_path,
        proposal_sha256,
        sidecar_path,
        registration_sha256,
        parent_path,
        parent_sha256,
        baseline,
        diagnostics,
    )
    if child["candidate_sha256"] != candidate["candidate_sha256"]:
        raise ValueError("H1 differs from registered student candidate")
    candidates, child_proof = worker_side(child_path, candidate_sha256, child, "H1")
    for ep in [*parents.values(), *candidates.values()]:
        if any(
            ep["proof"][key] == p_episode["proof"][key]
            for key in ("uid", "dsh_session_id", "receipt_sha256", "transfer_queue_key")
        ):
            raise ValueError("Proposal/worker identity reused")
    comparison, verdict = assemble(
        baseline["pins_sha256"],
        active["candidate_sha256"],
        candidate["candidate_sha256"],
        parents,
        candidates,
        baseline["max_tokens"],
    )
    # Recheck active and every externally bound input after the complete read-only audit.
    registry.load_registered(candidate["candidate_sha256"], baseline["parent_active_sha256"])
    for path, sha in zip(paths, hashes, strict=True):
        load(path, sha)
    _live_inputs(baseline, parent_path.parent, "H0")
    _live_inputs(child, child_path.parent, "H1")
    provenance = dict(
        schema="dsh.rsi-comparison-evidence.v1",
        **verdict,
        model_evaluation=True,
        synthetic_selection_comparison=False,
        comparison_sha256=prep.canonical_hash(comparison),
        parent_active_sha256=baseline["parent_active_sha256"],
        inputs=[{"path": str(path), "sha256": sha} for path, sha in zip(paths, hashes, strict=True)],
        parent={"audit": parent_proof, "episodes": {k: v["proof"] for k, v in parents.items()}},
        candidate={"audit": child_proof, "episodes": {k: v["proof"] for k, v in candidates.items()}},
        proposal={"source": p_source, "episode": p_episode["proof"]},
    )
    return {"comparison": comparison, "provenance": provenance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for prefix in ("parent", "candidate", "proposal", "registration"):
        parser.add_argument("--" + prefix, type=Path, required=True)
        parser.add_argument("--" + prefix + "-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("Comparison output must be new")
    result = compare(
        args.parent,
        args.parent_sha256,
        args.candidate,
        args.candidate_sha256,
        args.proposal,
        args.proposal_sha256,
        args.registration,
        args.registration_sha256,
    )
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, value in result.items():
        prep.write_json(args.output / (name + ".json"), value)
    print(
        json.dumps(
            {
                "outcome": result["provenance"]["outcome"],
                "comparison_sha256": result["provenance"]["comparison_sha256"],
                "provenance_sha256": prep.digest(args.output / "provenance.json"),
                "automatic_promotion": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
