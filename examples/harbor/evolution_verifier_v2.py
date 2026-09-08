"""Independent Harbor verifier pinned to native evolution admission v2."""

import argparse
import json
import sys
from pathlib import Path

from examples.harbor.evolution_verifier import _run_verifier
from uni_agent.tasks.harbor_dsh.evolution_scoring_v2 import (
    EvolutionV2Binding,
    load_evolution_v2_binding,
    require_evolution_v2_admission,
    score_evolution_v2,
)


def run_verifier(
    *,
    input_dir=Path("/audit-input"),
    output_dir=Path("/logs/verifier"),
    fixture_path=Path("/tests/fixture.json"),
    metadata_path=Path("/tests/metadata.json"),
    repository_root=None,
):
    return _run_verifier(
        input_dir=input_dir,
        output_dir=output_dir,
        fixture_path=fixture_path,
        metadata_path=metadata_path,
        repository_root=repository_root,
        binding_model=EvolutionV2Binding,
        loader=load_evolution_v2_binding,
        scorer=score_evolution_v2,
        admission=require_evolution_v2_admission,
        report_name="evolution-v2-report.json",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("/audit-input"))
    parser.add_argument("--output-dir", type=Path, default=Path("/logs/verifier"))
    try:
        report = run_verifier(**vars(parser.parse_args()))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        print(f"Evolution v2 Harbor verifier rejected evidence: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
