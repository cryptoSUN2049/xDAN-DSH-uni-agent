"""Thin Harbor overrides on the existing Qwen3-4B online RL training recipe."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

PREFIX = "actor_rollout_ref.rollout.custom.agent_framework"


def _hydra(value):
    if isinstance(value, dict):
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in value):
            raise ValueError("Unexpected Hydra configuration key")
        return "{" + ",".join(key + ":" + _hydra(item) for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_hydra(item) for item in value) + "]"
    if isinstance(value, str):
        # Hydra quoted values preserve literal newlines, not JSON \n escapes.
        # Only backslashes adjacent to a quote/closing quote need doubling.
        escaped = re.sub(r'(\\*)"', lambda match: match.group(1) * 2 + '\\"', value)
        escaped = re.sub(r"\\+$", lambda match: match.group() * 2, escaped)
        return '"' + escaped + '"'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def build_overrides(launch: dict) -> list[str]:
    if launch.get("schema") != "dsh.harbor-m2-launch.v1":
        raise ValueError("Unknown prepared launch schema")
    return [
        "++"
        + PREFIX
        + ".agent_runners.task.runner_kwargs.task_config_path="
        + _hydra(launch["environment"]["TASK_CONFIG"]),
        "++" + PREFIX + ".agent_runners.task.runner_kwargs.harbor_route_registration=" + _hydra(launch["registration"]),
        "++"
        + PREFIX
        + ".trajectory_postprocessor_fqn=uni_agent.tasks.harbor_dsh.registration.validate_registered_trajectories",
        "~" + PREFIX + ".trajectory_postprocessor_kwargs",
        "++" + PREFIX + ".trajectory_postprocessor_kwargs=" + _hydra(launch["postprocessor"]),
        "++" + PREFIX + ".trajectory_postprocessor_pass_context=True",
        "++" + PREFIX + ".gateway_count=1",
        "++" + PREFIX + ".agent_runners.task.max_concurrent_sessions=1",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    launch = json.loads(args.launch.read_bytes())
    overrides = build_overrides(launch)
    environment = {**os.environ, **launch["environment"]}
    base = Path(__file__).resolve().parents[1] / "dsh" / "train_qwen3_4b_online_rl.sh"
    if args.print_command or os.environ.get("PRINT_COMMAND") == "1":
        # The base print branch omits "$@". Preserve its command and append the
        # exact same overrides used below for real execution.
        output = subprocess.run(
            ["bash", str(base)],
            env={**environment, "PRINT_COMMAND": "1"},
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        print(output.stdout.rstrip() + " " + shlex.join(overrides))
        return
    os.execvpe("bash", ["bash", str(base), *overrides], environment)


if __name__ == "__main__":
    main()
