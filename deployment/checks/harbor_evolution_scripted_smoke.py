"""Real Harbor/DSH evolution lifecycle smoke; scripted policy, no student or training."""

import argparse
import asyncio
import hashlib
import json
import math
import re
import uuid
from pathlib import Path

from deployment.checks.harbor_t2_scripted_smoke import KEY, MODEL, private_output, start_server
from examples.dsh.prepare_evolution_dataset import _host_code

MODES = ("positive", "partial", "missing_define", "tamper")


class Policy:
    def __init__(self, mode, *, fixture, candidate):
        if mode not in MODES or fixture.get("operation") != "redact_email" or not isinstance(fixture.get("input"), str):
            raise ValueError("Expected explicit evolution mode and redact fixture")
        if not isinstance(candidate, str) or not candidate:
            raise ValueError("Expected fixed candidate tool name")
        self.mode, self.fixture, self.candidate = mode, fixture, candidate
        self.step = 0
        self.plugin = self.package = self.previous = None

    def respond(self, body):
        messages = body.get("messages", [])
        if self.step and (not messages or messages[-1].get("role") != "tool"):
            raise ValueError("Expected real tool result before next scripted action")
        if self.previous == "cordis_define":
            match = re.fullmatch(
                r"Defined ([^/\s]+)/([^\s]+) \([^\n]+\); it is not running yet\. "
                r"Use cordis_run to activate this Package\.",
                messages[-1].get("content", "").strip(),
            )
            if not match:
                raise ValueError("Invalid real define result")
            self.plugin, self.package = match.groups()
        actions = [
            ("str_replace_editor", {"command": "view", "path": "/app/fixture.json"}),
            ("cordis_inspect_list", {}),
        ]
        if self.mode != "missing_define":
            actions += [
                (
                    "cordis_define",
                    {
                        "plugin": {"kind": "new", "idPrefix": "evo"},
                        "name": "Bounded transform",
                        "purpose": "Apply the fixture transformation",
                        "code": {"host": _host_code(candidate_tool_name=self.candidate, operation="redact_email")},
                    },
                ),
                ("cordis_run", {"pluginId": self.plugin, "packageId": self.package, "mode": "run"}),
            ]
            if self.mode != "partial":
                actions.append((self.candidate, {"text": self.fixture["input"]}))
            actions += [("cordis_stop", {"pluginId": self.plugin}), ("cordis_undefine", {"pluginId": self.plugin})]
        if self.step > len(actions):
            raise ValueError("Scripted request budget exhausted")
        if self.step == len(actions):
            self.step += 1
            final = (
                {"status": "abstain"}
                if self.mode == "missing_define"
                else {
                    "status": "promote",
                    "plugin_id": self.plugin,
                    "package_id": self.package,
                    "evidence": ["inspected", "ran", "cleaned"],
                }
            )
            return [
                {"choices": [{"delta": {"role": "assistant", "content": json.dumps(final)}, "finish_reason": "stop"}]}
            ]
        name, arguments = actions[self.step]
        self.previous = name
        self.step += 1
        return [
            {"choices": [{"delta": {"role": "assistant", "content": None, "reasoning_content": ""}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": f"evolution-{self.step}",
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"delta": {"content": ""}, "finish_reason": "tool_calls"}]},
        ]


def check_result(mode, result, verifier_stdout=b"", *, admission_version="v1"):
    if admission_version not in {"v1", "v2"}:
        raise ValueError("Unknown admission version")
    if mode == "tamper":
        if (
            "Bridge trace/status/session identity mismatch" not in str(result.exception_info)
            or result.verifier_result is not None
        ):
            raise RuntimeError("Expected exact bridge tamper rejection without reward")
    elif mode == "missing_define" and admission_version == "v2":
        if (
            result.exception_info is not None
            or result.verifier_result is None
            or result.verifier_result.rewards != {"reward": 0.0}
        ):
            raise RuntimeError("Expected completed policy failure with real zero reward")
    elif mode == "missing_define":
        if (
            result.exception_info is None
            or result.verifier_result is not None
            or b"Evolution hard-veto evidence is not eligible for training" not in verifier_stdout
        ):
            raise RuntimeError("Expected original lifecycle veto without reward")
    elif mode not in {"positive", "partial"} or (
        result.exception_info is not None
        or result.verifier_result is None
        or result.verifier_result.rewards != {"reward": 1.0 if mode == "positive" else 0.25}
    ):
        raise RuntimeError("Unexpected evolution trial exception or reward")


async def run(task_dir, manifest_path, output, *, modes=MODES, timeout=600):
    from harbor.models.trial.config import TrialConfig
    from harbor.trial.hooks import TrialEvent

    from examples.harbor.evolution_verifier import _read
    from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH
    from uni_agent.tasks.harbor_dsh.evolution_scoring import (
        EVOLUTION_KIND,
        EvolutionBinding,
        _json,
        load_evolution_binding,
    )
    from uni_agent.tasks.harbor_dsh.evolution_scoring_v2 import (
        EVOLUTION_V2_KIND,
        EvolutionV2Binding,
        load_evolution_v2_binding,
    )
    from uni_agent.tasks.harbor_dsh.executor import _confirm_cleanup, _task_digest
    from uni_agent.tasks.harbor_dsh.isolated_trial import create_isolated_trial
    from uni_agent.tasks.harbor_dsh.protocol import TaskRef

    if not math.isfinite(timeout) or timeout <= 0 or not modes or any(mode not in MODES for mode in modes):
        raise ValueError("Explicit modes and finite positive timeout required")
    manifest = _json(_read(manifest_path, 1024 * 1024))
    ref = TaskRef.model_validate(manifest["task_ref"])
    if _task_digest(task_dir) != ref.sha256:
        raise ValueError("Frozen package TaskRef mismatch")
    descriptor = _json(_read(task_dir / "evolution.json", 65536))
    is_v2 = descriptor.get("kind") == EVOLUTION_V2_KIND
    fields = {"kind", "fixture_sha256", "metadata_sha256", "source_sha256s"}
    if is_v2:
        fields.add("verifier_bundle_sha256")
    if set(descriptor) != fields or descriptor.get("kind") not in {EVOLUTION_KIND, EVOLUTION_V2_KIND}:
        raise ValueError("Unexpected evolution descriptor")
    binding_type = EvolutionV2Binding if is_v2 else EvolutionBinding
    loader = load_evolution_v2_binding if is_v2 else load_evolution_binding
    binding = binding_type.model_validate(
        {
            **descriptor,
            "task_ref": ref.model_dump(),
            "fixture_path": str(task_dir / "tests/fixture.json"),
            "metadata_path": str(task_dir / "tests/metadata.json"),
        }
    )
    frozen = loader(binding, ref, repository_root=Path(__file__).resolve().parents[2])
    fixture, metadata = _json(frozen.fixture_raw), _json(frozen.metadata_raw)
    mapped = {
        **binding.model_dump(mode="json"),
        "fixture_path": "/tests/fixture.json",
        "metadata_path": "/tests/metadata.json",
    }
    raw_binding = json.dumps(mapped, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    private_output(output)
    report = dict(
        passed=False,
        scope="scripted Harbor/DSH integration; no student, Gateway tokens or training",
        task_ref=ref.model_dump(),
        admission_kind=binding.kind,
        fixture_sha256=binding.fixture_sha256,
        metadata_sha256=binding.metadata_sha256,
        source_sha256s=binding.source_sha256s,
        policy_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=[],
    )
    try:
        for mode in modes:
            session = "evolution-" + uuid.uuid4().hex
            policy = Policy(mode, fixture=fixture, candidate=metadata["candidate_tool_name"])
            server, thread, requests, errors = start_server(policy, session)
            evidence = dict(mode=mode, gateway_session_id=session, cleanup_confirmed=False)
            report["cases"].append(evidence)
            trial = None
            try:
                config = TrialConfig.model_validate(
                    dict(
                        task={"path": str(task_dir)},
                        trials_dir=str(output),
                        trial_name=session,
                        environment={"type": "docker", "delete": True},
                        agent={
                            "import_path": "uni_agent.agents.dsh.harbor_agent:DshHarborAgent",
                            "model_name": MODEL,
                            "kwargs": {
                                "gateway_base_url": f"http://host.docker.internal:{server.server_port}/sessions/{session}/v1",
                                "gateway_api_key": KEY,
                                "patches": [T2_PATCH_PATH],
                                "run_timeout": timeout - min(30, timeout / 2),
                            },
                        },
                    )
                )
                trial = create_isolated_trial(
                    config,
                    allowed_task_dir=task_dir,
                    strategy=binding.kind,
                    gateway_session_id=session,
                    max_trace_bytes=16 * 1024 * 1024,
                    evolution_binding=raw_binding,
                )
                if mode == "tamper":

                    async def tamper(_event, trial=trial):
                        path = trial.paths.agent_dir / "dsh/session.jsonl"
                        path.write_bytes(b" " + path.read_bytes())

                    trial.add_hook(TrialEvent.VERIFICATION_START, tamper)
                result = await asyncio.wait_for(trial.run(), timeout=timeout)
                evidence.update(
                    exception=None if result.exception_info is None else result.exception_info.model_dump(mode="json"),
                    rewards=None if result.verifier_result is None else result.verifier_result.rewards,
                )
                if errors or not requests:
                    raise RuntimeError(f"Scripted server failed: {errors}")
                stdout = trial.paths.test_stdout_path.read_bytes() if trial.paths.test_stdout_path.exists() else b""
                check_result(mode, result, stdout, admission_version="v2" if is_v2 else "v1")
                if _task_digest(task_dir) != ref.sha256:
                    raise ValueError("TaskRef changed during smoke")
                evidence["passed"] = True
            finally:
                await asyncio.to_thread(server.shutdown)
                server.server_close()
                await asyncio.to_thread(thread.join, 5)
                evidence["request_count"], evidence["server_errors"] = len(requests), errors
                if trial is not None:
                    await _confirm_cleanup(trial)
                    evidence["cleanup_confirmed"] = True
        report["passed"] = True
    finally:
        (output / "scripted-smoke.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=MODES, action="append")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                run(
                    args.task_dir.resolve(),
                    args.manifest.resolve(),
                    args.output.absolute(),
                    modes=args.mode or MODES,
                    timeout=args.timeout,
                )
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
