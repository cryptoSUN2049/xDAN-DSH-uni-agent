"""Harbor 0.16.1 entrypoint for the existing DSH agent, without another agent loop.

Load with ``--agent uni_agent.agents.dsh.harbor_agent:DshHarborAgent``. Harbor
owns the environment and task verification; this bridge only records execution
evidence. Gateway token trajectories and trusted reward receipts remain external.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from uni_agent import __version__
from uni_agent.agents.base import ModelConfig
from uni_agent.agents.dsh.harbor_release import T2_PATCH_PATH, T2_PATCH_SHA256
from uni_agent.sandbox.harbor import BorrowedHarborSandbox

from .agent import DshAgent, DshAgentConfig, _require_result, _run_key, extract_gateway_session_id

_SETUP_CHECK = """import hashlib, importlib.metadata, json, pathlib, sys
import deepseek_harness, deepseek_harness_runtime
from uni_agent.agents.dsh import runner
assert callable(runner.run)
def digest(path):
    return 'sha256:' + hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
print(json.dumps({
    'sdk_version': importlib.metadata.version('deepseek-harness-sdk'),
    'runtime_version': importlib.metadata.version('deepseek-harness-runtime-bin'),
    'runner_sha256': digest(runner.__file__),
    'patches': [{'path': p, 'sha256': digest(p)} for p in sys.argv[1:]],
}))
"""


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


class DshHarborAgent(BaseAgent):
    """Single-session Linux DSH execution over a preinstalled Harbor environment.

    No ambient host credentials, package installation, token reconstruction, or
    reward computation. A new bridge/Gateway session is required for each run.
    """

    def __init__(
        self,
        logs_dir: Path,
        *,
        gateway_base_url: str,
        model_name: str | None = None,
        gateway_api_key: str = "EMPTY",
        workdir: str = "/app",
        profile: str = "sdk-minimal",
        patches: list[str] | None = None,
        runner_python: str = "python",
        max_tokens_per_turn: int = 4096,
        run_timeout: float = 1800,
        reasoning_effort: str | None = None,
        logger: logging.Logger | None = None,
        extra_env: dict[str, str] | None = None,
        mcp_servers: list[Any] | None = None,
        skills_dir: str | None = None,
    ) -> None:
        if tuple(patches or []) not in {(), (T2_PATCH_PATH,)}:
            raise ValueError("Only the frozen T2 patch path is supported")
        if extra_env or mcp_servers or skills_dir:
            raise ValueError("DSH Harbor bridge does not support extra_env, MCP, or skill injection")
        if not model_name or not model_name.strip() or not gateway_api_key.strip():
            raise ValueError("Explicit model_name and non-empty gateway_api_key are required")
        if max_tokens_per_turn <= 0:
            raise ValueError("max_tokens_per_turn must be positive")
        parsed = urlparse(gateway_base_url)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Gateway URL must not contain credentials")
        self._gateway_session_id = extract_gateway_session_id(gateway_base_url)
        super().__init__(logs_dir=logs_dir, model_name=model_name, logger=logger)
        self._config = DshAgentConfig(
            model=ModelConfig(
                base_url=gateway_base_url,
                api_key=gateway_api_key,
                model_name=model_name,
                max_tokens_per_turn=max_tokens_per_turn,
            ),
            default_workdir=workdir,
            profile=profile,
            patches=list(patches or []),
            runner_python=runner_python,
            run_timeout=run_timeout,
            reasoning_effort=reasoning_effort,
            keep_trace=True,
        )
        self._evidence_dir = Path(logs_dir) / "dsh"
        self._environment: BaseEnvironment | None = None
        self._ran = False

    @staticmethod
    def name() -> str:
        return "uni-agent-dsh"

    def version(self) -> str:
        return __version__

    def _write(self, name: str, data: bytes) -> None:
        # Refuse collisions rather than replacing evidence from another run.
        with (self._evidence_dir / name).open("xb") as output:
            output.write(data)
        (self._evidence_dir / name).chmod(0o600)

    async def setup(self, environment: BaseEnvironment) -> None:
        sandbox = BorrowedHarborSandbox(environment)
        result = await sandbox.exec(
            [self._config.runner_python, "-c", _SETUP_CHECK, *self._config.patches],
            workdir=self._config.default_workdir,
            timeout=30,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"DSH preinstalled SDK/runtime check failed (exit {result.exit_code})")
        probe = json.loads(result.stdout)
        expected = _digest(Path(__file__).with_name("runner.py").read_bytes())
        if not isinstance(probe, dict) or probe.get("runner_sha256") != expected:
            raise RuntimeError("DSH container helper does not match the bridge runner source")
        if any(not isinstance(probe.get(key), str) or not probe[key] for key in ("sdk_version", "runtime_version")):
            raise RuntimeError("DSH preflight did not report SDK/runtime versions")
        expected_patches = [{"path": T2_PATCH_PATH, "sha256": T2_PATCH_SHA256}] if self._config.patches else []
        if probe.get("patches", []) != expected_patches:
            raise RuntimeError("DSH container patch bytes do not match the frozen release")
        self._evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        self._write("setup.json", _json_bytes(probe))
        self._environment = environment

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        if self._environment is None:
            raise RuntimeError("DSH Harbor setup must complete before run")
        if environment is not self._environment:
            raise RuntimeError("DSH Harbor run must use the environment checked by setup")
        if self._ran:
            raise RuntimeError("DSH Harbor bridge may run only once per Gateway session")
        if (context.metadata or {}).get("dsh") is not None:
            raise ValueError("AgentContext already contains DSH execution metadata")
        self._ran = True
        metadata: dict[str, Any] = {
            "schema": "dsh.harbor-agent-execution.v1",
            "status": "running",
            "gateway_session_id": self._gateway_session_id,
            "dsh_session_id": f"dsh-{self._gateway_session_id}",
            "harbor_agent_session_id": self.session_id,
            "harbor_context_id": str(self.context_id) if self.context_id is not None else None,
        }
        context.metadata = {**(context.metadata or {}), "dsh": metadata}
        sandbox = BorrowedHarborSandbox(environment)
        try:
            result = await DshAgent(self._config).run(
                sandbox=sandbox,
                messages=[{"role": "user", "content": instruction}],
                workdir=self._config.default_workdir,
            )
            artifact_dir = f"{self._config.artifact_root.rstrip('/')}/{_run_key(self._gateway_session_id)}"
            trace_path = f"{artifact_dir}/session.jsonl"
            trace = await sandbox.read_file(trace_path)
            raw_run = await sandbox.read_file(f"{artifact_dir}/result.json")
            # Preserve raw bytes for failure investigation as well as success.
            self._write("session.jsonl", trace)
            self._write("run.json", raw_run)
            result_bytes = _json_bytes(dataclasses.asdict(result))
            self._write("agent-result.json", result_bytes)
            helper = _require_result(
                json.loads(raw_run),
                expected_trace_path=trace_path,
                expected_dsh_session_id=metadata["dsh_session_id"],
                require_trace=True,
            )
            if _digest(trace) != helper["trace_sha256"]:
                raise RuntimeError("DSH trace bytes do not match the SDK result")
            try:
                events = [json.loads(line) for line in trace.splitlines()]
            except (ValueError, UnicodeDecodeError) as error:
                raise RuntimeError("DSH trace is not valid event JSONL") from error
            if (
                result.info.get("trace_sha256") != helper["trace_sha256"]
                or result.info.get("gateway_session_id") != self._gateway_session_id
                or result.info.get("dsh_session_id") != helper["dsh_session_id"]
                or result.info.get("trace_path") != trace_path
                or len(events) != helper["event_count"]
                or any(not isinstance(event, dict) for event in events)
                or result.info.get("event_count") != helper["event_count"]
                or result.output.get("response") != helper["final_response"]
                or result.finished is not (helper.get("finish_reason") == "completed")
                or helper.get("profile") != self._config.profile
                or (result.finished and (not events or events[-1].get("type") != "turn/end"))
            ):
                raise RuntimeError("DSH trace/result identity verification failed")
            metadata.update(
                status="completed" if result.finished is True else "unfinished",
                finished=result.finished,
                finish_reason=helper.get("finish_reason"),
                trace_sha256=_digest(trace),
                run_sha256=_digest(raw_run),
                agent_result_sha256=_digest(result_bytes),
                event_count=len(events),
            )
        except BaseException as error:
            metadata.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            self._write("status.json", _json_bytes(metadata))
