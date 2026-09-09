"""Read-only EOS evidence for consumed native memory trajectories; never infer finish_reason."""

import argparse
import io
import json
from pathlib import Path

import numpy as np

from examples.dsh.capabilities.audit_memory_training import _require, audit_memory_training
from examples.dsh.capabilities.memory_verifier import read_regular, sha


def generation_segments(
    prompt_ids, response_ids, response_mask, *, eos_ids, vocab_size, generation_count, capacity_tokens
):
    _require(type(vocab_size) is int and vocab_size > 0, "Invalid vocabulary size")
    _require(type(capacity_tokens) is int and capacity_tokens > 0, "Invalid trajectory capacity")
    _require(type(generation_count) is int and generation_count > 0, "Missing actual generation count")
    _require(bool(eos_ids) and all(type(t) is int and 0 <= t < vocab_size for t in eos_ids), "Invalid EOS tokens")
    _require(bool(prompt_ids) and bool(response_ids), "Empty original tokens")
    _require(all(type(t) is int and 0 <= t < vocab_size for t in prompt_ids + response_ids), "Invalid original token")
    _require(
        len(response_mask) == len(response_ids) and all(type(m) is int and m in (0, 1) for m in response_mask),
        "Invalid response mask",
    )
    _require(len(prompt_ids) + len(response_ids) <= capacity_tokens, "Trajectory exceeds declared capacity")
    spans, start = [], None
    for index, mask in enumerate([*response_mask, 0]):
        if mask == 1 and start is None:
            start = index
        elif mask == 0 and start is not None:
            end = index
            token = response_ids[end - 1]
            eos = token in eos_ids
            capacity = len(prompt_ids) + end == capacity_tokens
            spans.append(
                dict(
                    start_response_offset=start,
                    end_response_offset=end,
                    generated_tokens=end - start,
                    last_token_id=token,
                    ends_with_eos=eos,
                    at_capacity=capacity,
                    eos_capacity_tie=eos and capacity,
                    original_finish_reason=None,
                    status="eos-token-observed" if eos else "no-eos-boundary-uncertain",
                )
            )
            start = None
    _require(len(spans) == generation_count, "Mask spans do not identify every actual generation; boundaries uncertain")
    return dict(
        prompt_tokens=len(prompt_ids),
        response_tokens=len(response_ids),
        total_tokens=len(prompt_ids) + len(response_ids),
        segments=spans,
        all_segments_end_eos=all(s["ends_with_eos"] for s in spans),
    )


def _model_source(model_config, model_config_sha256, generation_config, generation_config_sha256, eos_token_ids):
    config_raw = read_regular(model_config)
    _require(sha(config_raw) == model_config_sha256, "Model config hash mismatch")
    config = json.loads(config_raw)
    _require(isinstance(config, dict), "Expected model config object")
    source = dict(model_config_path=str(model_config), model_config_sha256=model_config_sha256)
    effective = config
    if generation_config is not None:
        raw = read_regular(generation_config)
        _require(sha(raw) == generation_config_sha256, "Generation config hash mismatch")
        effective = json.loads(raw)
        _require(isinstance(effective, dict), "Expected generation config object")
        source.update(generation_config_path=str(generation_config), generation_config_sha256=generation_config_sha256)
    else:
        _require(generation_config_sha256 is None, "Generation config path required with hash")
    eos = effective.get("eos_token_id")
    eos = [eos] if type(eos) is int else eos
    vocab = config.get("vocab_size")
    _require(type(vocab) is int and vocab > 0, "Model config missing valid vocab_size")
    _require(
        isinstance(eos, list) and eos and all(type(t) is int and 0 <= t < vocab for t in eos),
        "Invalid model EOS whitelist",
    )
    _require(
        isinstance(eos_token_ids, list) and eos_token_ids and all(type(t) is int for t in eos_token_ids),
        "Explicit EOS token IDs required",
    )
    _require(
        len(set(eos_token_ids)) == len(eos_token_ids) and set(eos_token_ids) == set(eos),
        "Explicit EOS IDs must match effective model config",
    )
    source.update(eos_token_ids=sorted(eos), vocab_size=vocab, checkpoint_binding="operator-supplied-config-hashes")
    return source


def audit_generation_boundaries(
    run_root,
    *,
    memory_root,
    expected_run_id,
    model_config,
    model_config_sha256,
    eos_token_ids,
    capacity_tokens,
    generation_config=None,
    generation_config_sha256=None,
):
    source = _model_source(
        model_config, model_config_sha256, generation_config, generation_config_sha256, eos_token_ids
    )
    consumption = audit_memory_training(Path(run_root), memory_root=Path(memory_root), expected_run_id=expected_run_id)
    trajectories, errors = [], []
    for group in consumption["groups"]:
        if not group["consumption_verified"]:
            continue
        try:
            raw = read_regular(group["path"], 8_000_000)
            _require(sha(raw) == group["crosswalk_sha256"], "Crosswalk changed after consumption audit")
            record = json.loads(raw)
            for item in record["items"]:
                raw_npz = read_regular(item["stage_npz_path"], 64_000_000)
                _require(sha(raw_npz) == item["stage_npz_sha256"], "NPZ changed after consumption audit")
                meta_raw = read_regular(item["stage_json_path"], 8_000_000)
                _require(sha(meta_raw) == item["stage_json_sha256"], "Version metadata changed after consumption audit")
                with np.load(io.BytesIO(raw_npz), allow_pickle=False) as arrays:
                    prefix = f"traj{item['stage_index']}_"
                    values = [
                        arrays[prefix + field].tolist() for field in ("prompt_ids", "response_ids", "response_mask")
                    ]
                result = generation_segments(
                    *values,
                    eos_ids=set(source["eos_token_ids"]),
                    vocab_size=source["vocab_size"],
                    generation_count=item["version_evidence"]["generation_count"],
                    capacity_tokens=capacity_tokens,
                )
                trajectories.append(
                    dict(
                        tq_key=item["tq_key"],
                        chain_id=item["chain_id"],
                        role=item["role"],
                        partition=record["partition"],
                        global_steps=record["global_steps"],
                        gateway_session_id=item["gateway_session_id"],
                        version_evidence=item["version_evidence"],
                        stage_npz_sha256=item["stage_npz_sha256"],
                        stage_json_sha256=item["stage_json_sha256"],
                        crosswalk_sha256=group["crosswalk_sha256"],
                        consumption_verified=True,
                        **result,
                    )
                )
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            errors.append(dict(crosswalk_path=group["path"], reason=str(error)))
    segments = [s for t in trajectories for s in t["segments"]]
    passed = consumption["passed"] and bool(segments) and not errors and all(s["ends_with_eos"] for s in segments)
    return dict(
        schema="dsh.memory-generation-boundaries.v1",
        run_id=expected_run_id,
        passed=passed,
        model_source=source,
        capacity_tokens=capacity_tokens,
        capacity_source="operator-declared",
        consumption_audit=consumption,
        trajectories=trajectories,
        errors=errors,
        summary=dict(
            consumed_trajectories_checked=len(trajectories),
            generation_segments=len(segments),
            verified_eos_segments=sum(s["ends_with_eos"] for s in segments),
            uncertain_non_eos_segments=sum(not s["ends_with_eos"] for s in segments),
            eos_capacity_ties=sum(s["eos_capacity_tie"] for s in segments),
        ),
        limitations=[
            "EOS IDs are original-token evidence, not recovered backend finish_reason.",
            "EOS at capacity is a tie; original termination precedence is unknown.",
            "No EOS does not prove length; budget is operator-declared, not inferred.",
            "Fixed VERL still loses length/stop distinctions; this audit does not repair it.",
            "No optimizer update, model improvement or historical receipt rewriting is certified.",
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-root", "memory-root", "model-config", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model-config-sha256", required=True, help="sha256:<hex> from pinned model config")
    parser.add_argument("--generation-config", type=Path)
    parser.add_argument("--generation-config-sha256")
    parser.add_argument("--eos-token-id", type=int, action="append", required=True)
    parser.add_argument("--capacity-tokens", type=int, required=True)
    args = parser.parse_args()
    report = audit_generation_boundaries(
        args.run_root,
        memory_root=args.memory_root,
        expected_run_id=args.run_id,
        model_config=args.model_config,
        model_config_sha256=args.model_config_sha256,
        generation_config=args.generation_config,
        generation_config_sha256=args.generation_config_sha256,
        eos_token_ids=args.eos_token_id,
        capacity_tokens=args.capacity_tokens,
    )
    with args.output.open("x") as file:
        json.dump(report, file, indent=2)
        file.write("\n")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
