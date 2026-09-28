"""Operator r5 draft: retain the supervisor and resume r4 C2 to absolute step 3."""

from pathlib import Path

from deployment.services import harbor_training_supervisor as supervisor

CHECKPOINT = "/workspace/mimo-dsh-rl-20260928/runs/r4/rl-training/checkpoints/global_step_2"


def native_training_command(manifest, launch_path, python_bin):
    if "lora_adapter" in manifest:
        raise ValueError("Native MiMo smoke requires its explicit STUDENT_MODEL_PATH, not a legacy adapter manifest")
    recipe = Path.cwd() / "examples/mimo_dsh_rl/mimo-9b-smoke.yaml"
    if not recipe.is_file():
        raise ValueError("Run from the frozen source root containing the MiMo smoke recipe")
    return [
        python_bin,
        "-m",
        "examples.harbor_opd_rl.launch",
        "--mode",
        "rl",
        "--launch",
        str(launch_path),
        "--recipe-config",
        str(recipe),
        "--resume-from-path",
        CHECKPOINT,
        "--total-training-steps",
        "3",
        "--save-freq",
        "1",
    ]


if __name__ == "__main__":
    supervisor.training_command = native_training_command
    supervisor.main()
