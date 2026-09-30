"""Execute one cloud CPU prepare/preflight under verified frozen import origins."""

import argparse
import json
import os
import runpy
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "preflight"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    operator = runpy.run_path(str(Path(__file__).with_name("mimo_r20_operator.py")))
    source = operator["source_directory"]()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "":
        raise ValueError("CPU-only preparation requires CUDA_VISIBLE_DEVICES=''")
    from deployment.services import harbor_run_controller
    from examples.harbor import prepare_m2_training
    from examples.harbor_opd_rl import launch

    origins = {}
    for module, relative in (
        (harbor_run_controller, "deployment/services/harbor_run_controller.py"),
        (prepare_m2_training, "examples/harbor/prepare_m2_training.py"),
        (launch, "examples/harbor_opd_rl/launch.py"),
    ):
        if Path(module.__file__).resolve() != (source / relative).resolve():
            raise ValueError("Preparation imported a different core source")
        origins[relative] = {"path": module.__file__, "sha256": operator["file_identity"](module.__file__)["sha256"]}
    if launch.ROOT.resolve() != source.resolve():
        raise ValueError("Native Hydra root differs from the frozen runtime")
    plan = json.loads(args.plan.read_bytes())
    if operator["file_identity"](plan["spec_path"])["sha256"] != plan["spec_raw_sha256"]:
        raise ValueError("Actual private RunSpec bytes differ from stage authorization")
    expected = operator["environment"](plan, cpu=True)
    for key in (
        "LD_LIBRARY_PATH",
        "STUDENT_MODEL_PATH",
        "TOOL_PARSER",
        "WANDB_MODE",
        "WANDB_NAME",
        "WANDB_RUN_ID",
        "RAY_TMPDIR",
    ):
        if os.environ.get(key) != expected[key]:
            raise ValueError("Actual CPU environment differs: " + key)
    result = operator[args.action](plan)
    result["import_provenance"] = origins
    result["cpu_runner_sha256"] = operator["file_identity"](__file__)["sha256"]
    result["stage_plan_sha256"] = operator["file_identity"](args.plan)["sha256"]
    operator["write_new"](args.output, result)
    print(
        json.dumps(
            {"status": result["status"], "action": args.action, "output": str(args.output), "cuda_initialized": False}
        )
    )


if __name__ == "__main__":
    sys.exit(main())
