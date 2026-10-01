"""Two isolated Modal environments for the original General/MCP contract.

The sidecar owns tools, SQLite and late verifier material. It receives a
read-only workspace snapshot before each MCP call and grading. The original
MCP schemas, bridge program and task verifier remain authoritative. This is a
reference-compat transport, not proof of live Modal or judge acceptance.
"""

from __future__ import annotations

import functools
import json
import math
import os
import posixpath
import re
import shlex
import tarfile
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .modal_environment import ModalEnvironment, ModalEnvironmentConfig
from .terminal_bench_environment import STUDENT, AgentEnvironmentView

SERVICE = "mimo_service"
WORKSPACE = "/work/workspace"
BRIDGE = "/work/_setup/mcp_bridge.py"
MCP_WHEEL_SHA256 = "f5a075bb611f23d6f4d080c6a1699fa62772eebc562ba9e66b306ddde1c755f7"
MCP_RUNTIME_LOCK_SHA256 = "bae02ecc011e2df4527686c8a0bf13afb1f083e12f5f7edb2d3335e530ccd836"


@dataclass
class GeneralEnvironmentConfig(ModalEnvironmentConfig):
    cwd: str = WORKSPACE
    cpu_request: str = "2"
    memory_request: str = "8Gi"
    labels: dict = field(default_factory=dict)
    shared_volumes: list = field(default_factory=lambda: ["workspace", "system-vol"])
    main_volume_mounts: list = field(default_factory=lambda: [{"name": "workspace", "mount_path": WORKSPACE}])
    sidecars: list = field(default_factory=list)
    mcp_isolation: dict | None = None
    node_selector: dict = field(default_factory=dict)
    mcp_version: str = "1.29.0"
    mcp_runtime_lock: str = field(
        default_factory=lambda: str(
            Path(__file__).resolve().parents[3] / "examples/mimo_multidomain_rl/general-mcp-runtime-requirements.txt"
        )
    )


class McpTransportView:
    """A capability used only by the registered MCP tools, never Bash tools."""

    def __init__(self, environment):
        self._environment = environment

    def execute(self, command, timeout=None):
        environment = self._environment
        argv = shlex.split(command)
        python = getattr(environment, "mcp_bridge_python", "python3")
        script = getattr(environment, "mcp_bridge_script", BRIDGE)
        if len(argv) < 7 or argv[:2] != [python, script] or argv[2] != "--url" or argv[4] != "--name":
            raise PermissionError("Only the fixed MCP bridge command is routable")
        server = argv[5]
        if server not in environment.mcp_servers or argv[3] != environment.mcp_servers[server].get("url"):
            raise PermissionError("Unregistered MCP server or endpoint")
        if argv[6:] != ["--list"]:
            if len(argv) != 10 or argv[6] != "--call" or argv[8] != "--args-json":
                raise PermissionError("Invalid MCP call contract")
            if not isinstance(json.loads(argv[9]), dict):
                raise ValueError("MCP arguments must be a JSON object")
        environment.sync_workspace()
        return environment.execute(shlex.join(argv), timeout=timeout, container="sidecar")


class GeneralEnvironment:
    """mimoagent base-environment interface with explicit container routing."""

    def __init__(self, *, config_class=GeneralEnvironmentConfig, backend_factory=None, **kwargs):
        self.config = config_class(**kwargs)
        self._factory = backend_factory or ModalEnvironment
        self._backends = {}
        self._workspace_initialized = False
        self._student_enabled = False
        self._verifier_phase = None
        self.mcp_servers = {}
        self.mcp_transport_view = McpTransportView(self)
        if self.config.cwd != WORKSPACE:
            raise ValueError("General business tasks require the original workspace root")
        if self.config.mcp_isolation is not None:
            raise ValueError("Shared-pod MCP firewall profile cannot be used for isolated Modal environments")
        if self.config.mcp_version != "1.29.0":
            raise ValueError("Original General MCP assets require the fixed v1 SDK")
        if any(mount.get("name") != "workspace" for mount in self.config.main_volume_mounts):
            raise ValueError("Main container must never mount sidecar state")
        if len(self.config.sidecars) != 1 or self.config.sidecars[0].get("name") != "sidecar":
            raise ValueError("Exactly one isolated sidecar is required")
        mounts = self.config.sidecars[0].get("volume_mounts", [])
        workspace_mount = next((mount for mount in mounts if mount.get("name") == "workspace"), {})
        if workspace_mount.get("read_only") is not True:
            raise ValueError("Sidecar workspace must be read-only")

    def _backend_kwargs(self, role):
        config = asdict(self.config)
        native_fields = ModalEnvironmentConfig.__dataclass_fields__
        result = {name: value for name, value in config.items() if name in native_fields}
        result["session_id"] = f"{self.config.session_id}-{role}"
        result["tags"] = {**result["tags"], "general_role": role, **self.config.labels}
        if result.get("cpu") is None:
            result["cpu"] = float(self.config.cpu_request)
        if result.get("memory") is None:
            memory = self.config.memory_request
            if not memory.endswith("Gi"):
                raise ValueError("Explicit General memory_request must use Gi units")
            result["memory"] = int(float(memory[:-2]) * 1024)
        if role == "sidecar":
            result["image"] = self.config.sidecars[0].get("image") or result["image"]
        return result

    def start(self):
        if self._backends:
            raise RuntimeError("General environments cannot be reused")
        try:
            for role in ("main", "sidecar"):
                backend = self._factory(**self._backend_kwargs(role))
                self._backends[role] = backend
                backend.start()
                user = STUDENT if role == "main" else SERVICE
                script = (
                    "set -eu\n"
                    f"id {user} >/dev/null 2>&1 || useradd -m -s /bin/sh {user}\n"
                    "mkdir -p /work/workspace /work/_setup /logs/verifier\n"
                )
                if role == "sidecar":
                    script += f"chown {SERVICE}:{SERVICE} /work /logs/verifier\n"
                result = backend.execute(script, cwd="/", timeout=120, as_user="root")
                if result.get("returncode") != 0:
                    raise RuntimeError(
                        f"General {role} privilege setup failed "
                        f"(rc={result.get('returncode')}, reason={result.get('reason')}): "
                        f"{result.get('output', '')[-2000:]}"
                    )
        except Exception:
            self.cleanup()
            raise

    def prepare_mcp_python(self):
        """Restore the original assets' v1 runtime inside the owned sidecar only.

        Public env-0 currently ships MCP 2.2, removing FastMCP, and lacks the
        original hardcoded venv. Keep every task byte unchanged; isolate the
        compatible SDK from the global interpreter and the trainer's uv env.
        """
        import hashlib

        lock = Path(self.config.mcp_runtime_lock)
        if lock.is_symlink() or hashlib.sha256(lock.read_bytes()).hexdigest() != MCP_RUNTIME_LOCK_SHA256:
            raise ValueError("Original General MCP runtime lock changed")
        backend = self._backends["sidecar"]
        backend.copy_to(str(lock), "/opt/mimo-general-mcp.lock", as_user="root")
        command = (
            "set -eu\n"
            "python3 -m venv /opt/openai-agents-venv\n"
            "/opt/openai-agents-venv/bin/python -m pip install --no-input --disable-pip-version-check "
            "--require-hashes -r /opt/mimo-general-mcp.lock\n"
            "/opt/openai-agents-venv/bin/python -m pip check\n"
            '/opt/openai-agents-venv/bin/python -c "'
            "from mcp.server.fastmcp import FastMCP; "
            "from mcp.client.streamable_http import streamablehttp_client; import requests; "
            "import importlib.metadata; assert importlib.metadata.version('mcp') == '1.29.0'\"\n"
        )
        result = backend.execute(command, cwd="/", timeout=180, as_user="root")
        if result.get("returncode") != 0 or result.get("reason") not in (None, "ok"):
            raise RuntimeError("Original General v1 MCP runtime setup failed: " + result.get("output", "")[-2000:])

    def execute(self, command, cwd="", timeout=None, *, container=None, as_user=None):
        role = container or "main"
        if role not in self._backends:
            raise ValueError("Unknown or unstarted General container")
        if role == "sidecar" and not self._workspace_initialized:
            self.sync_workspace()
        user = as_user or (SERVICE if role == "sidecar" else "root")
        phase = self._verifier_phase
        if phase and role == "sidecar" and (command == phase[0] or command.endswith(" " + phase[0])):
            return self._execute_trusted_verifier(command, cwd or self.config.cwd, timeout, phase[1])
        return self._backends[role].execute(command, cwd=cwd or self.config.cwd, timeout=timeout, as_user=user)

    @contextmanager
    def verifier_phase(self, command, credentials):
        """Credentials enter only the exact trusted verifier exec, via stdin."""
        if self._verifier_phase is not None or not isinstance(command, str) or not command:
            raise RuntimeError("Invalid or nested trusted verifier phase")
        if set(credentials) - {"GA_JUDGE_KEY", "JUDGE_API_KEY"}:
            raise ValueError("Unexpected trusted verifier credential")
        self._verifier_phase = (command, dict(credentials))
        try:
            yield
        finally:
            self._verifier_phase = None

    def _execute_trusted_verifier(self, command, cwd, timeout, credentials):
        backend = self._backends["sidecar"]
        budget = getattr(backend.config, "max_exec_budget", 0)
        if budget > 0 and backend._cumulative_exec_time >= budget:
            return {"output": "Exec time budget exhausted", "returncode": 1, "reason": "budget_exhausted"}
        timeout = self.config.timeout if timeout is None else timeout
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Invalid trusted verifier timeout")
        # No credential is placed in argv, files, public configuration or logs.
        # The native binary stdin transport is the same one used by file copy.
        helper = (
            "import json,os,sys; p=json.load(sys.stdin); os.environ.update(p['env']); "
            "os.chdir(p['cwd']); os.execvpe('/bin/bash', "
            "['/bin/bash','-lc','exec 2>&1 </dev/null\\n'+p['command']], os.environ)"
        )
        argv = ["timeout", str(timeout), "su", SERVICE, "-s", "/bin/sh", "-c", shlex.join(["python3", "-c", helper])]
        payload = json.dumps({"command": command, "cwd": cwd, "env": credentials}).encode()
        started = time.monotonic()
        try:
            outcome = backend._exec(argv, timeout=timeout + 5, stdin=payload, max_output_bytes=50 * 1024 * 1024)
        finally:
            if hasattr(backend, "_cumulative_exec_time"):
                backend._cumulative_exec_time += time.monotonic() - started
        output = (outcome.stdout + outcome.stderr).decode("utf-8", "replace")
        # Original verify.py prints a truncated judge key in its chain banner.
        # Sanitize before the unchanged parent grader/actor can log stdout.
        for key in credentials.values():
            if key:
                output = output.replace(key, "<redacted>")
        output = re.sub(r"(?i)(\bkey=)\S+", r"\1<redacted>", output)
        reason = "ok"
        if outcome.returncode == 124:
            reason = "pod_timeout"
        elif outcome.returncode == -1:
            reason = "client_timeout"
        elif outcome.returncode is None or outcome.stream_error is not None:
            reason = "transport_error"
        return {"output": output, "returncode": outcome.returncode, "reason": reason}

    def copy_to(self, src_path, dest_path, *, container=None, dereference=False, as_user=None, **kwargs):
        role = container or "main"
        target = posixpath.normpath(dest_path)
        if target != dest_path or not target.startswith("/"):
            raise ValueError("Transfer requires a canonical absolute target")
        if role == "main" and not (target == WORKSPACE or target.startswith(WORKSPACE + "/") or target == BRIDGE):
            raise PermissionError("Hidden payload/state/verifier files cannot be installed in main")
        source = Path(src_path)
        if source.is_symlink() or (source.is_dir() and any(path.is_symlink() for path in source.rglob("*"))):
            raise ValueError("Task asset symlinks are not accepted")
        backend = self._backends[role]
        # Upstream writes a missing final answer from a mode-0600 controller
        # tempfile during grading. Extract it as the workspace owner, otherwise
        # the student's snapshot cannot read it and grading becomes infra.
        workspace = target == WORKSPACE or target.startswith(WORKSPACE + "/")
        user = as_user or (STUDENT if role == "main" and workspace and self._student_enabled else "root")
        backend.copy_to(str(source), dest_path, as_user=user, **kwargs)
        if role == "sidecar" and (target == "/work/system" or target.startswith("/work/system/")):
            result = backend.execute(f"chown -R {SERVICE}:{SERVICE} /work/system", cwd="/", timeout=120, as_user="root")
            if result.get("returncode") != 0:
                raise RuntimeError("MCP state ownership setup failed")
        if role == "main" and target == BRIDGE:
            self._backends["sidecar"].copy_to(str(source), BRIDGE, as_user="root", **kwargs)

    def copy_out(self, src_path, dest_path, *, container=None, as_user=None, **kwargs):
        role = container or "main"
        return self._backends[role].copy_out(src_path, dest_path, as_user=as_user or "root", **kwargs)

    def enable_student(self):
        result = self.execute(f"chown -R {STUDENT}:{STUDENT} {WORKSPACE}", cwd="/", timeout=120)
        if result.get("returncode") != 0:
            raise RuntimeError("Student workspace ownership failed")
        self._student_enabled = True

    def sync_workspace(self):
        """Mirror readable files; reject links and maintain sidecar read-only mode."""
        token = uuid.uuid4().hex
        remote = f"/tmp/.mimo-workspace-{token}.tgz"
        main, sidecar = self._backends["main"], self._backends["sidecar"]
        result = main.execute(f"tar -C {WORKSPACE} -czf {remote} .", cwd="/", timeout=120, as_user=STUDENT)
        if result.get("returncode") != 0:
            raise RuntimeError("Workspace snapshot failed")
        try:
            with tempfile.TemporaryDirectory(prefix="mimo-general-workspace-") as directory:
                local = Path(directory, "workspace.tgz")
                main.copy_out(remote, str(local), as_user=STUDENT)
                if local.stat().st_size > 64 * 1024 * 1024:
                    raise RuntimeError("Workspace snapshot exceeded transfer budget")
                with tarfile.open(local, "r:gz") as archive:
                    size = 0
                    for member in archive:
                        name = member.name.removeprefix("./")
                        if name == "." and member.isdir():
                            continue
                        if name.startswith("/") or ".." in name.split("/") or not (member.isfile() or member.isdir()):
                            raise RuntimeError("Unsafe workspace snapshot member")
                        size += member.size
                        if size > 128 * 1024 * 1024:
                            raise RuntimeError("Workspace snapshot expanded beyond budget")
                sidecar.copy_to(str(local), remote, as_user="root")
                result = sidecar.execute(
                    f"rm -rf -- {WORKSPACE} && mkdir -p {WORKSPACE} && tar -C {WORKSPACE} -xzf {remote} "
                    f"&& chown -R root:root {WORKSPACE} && find {WORKSPACE} -type d -exec chmod 0555 {{}} + "
                    f"&& find {WORKSPACE} -type f -exec chmod 0444 {{}} +",
                    cwd="/",
                    timeout=120,
                    as_user="root",
                )
                if result.get("returncode") != 0:
                    raise RuntimeError("Sidecar read-only workspace mirror failed")
                self._workspace_initialized = True
        finally:
            for backend in (main, sidecar):
                backend.execute(f"rm -f -- {remote}", cwd="/", timeout=30, as_user="root")

    @property
    def evidence(self):
        return {role: backend.evidence for role, backend in self._backends.items()}

    def get_template_vars(self):
        return {"cwd": self.config.cwd}

    def cleanup(self):
        errors = []
        for role, backend in self._backends.items():
            try:
                backend.cleanup()
            except Exception as error:
                errors.append(f"{role}: {type(error).__name__}")
        if errors:
            raise RuntimeError("General owned cleanup incomplete: " + ", ".join(errors))


def register_general_environment():
    """Preserve upstream business verifier, changing only execution transport."""
    from mimoagent.environments.datasets import DATASET_REGISTRY
    from recipes.general.general_agent.environment import GeneralAgentEnvironment

    if getattr(DATASET_REGISTRY.get("general_agent"), "_mimo_general_reference_compat", False):
        return

    class IsolatedGeneralAgentEnvironment(GeneralAgentEnvironment):
        _mimo_general_reference_compat = True

        def _setup_dataset_specific(self):
            self.env.prepare_mcp_python()
            super()._setup_dataset_specific()

        def setup_environment(self):
            trusted = self.env
            super().setup_environment()
            trusted.enable_student()
            self._trusted_env = trusted
            self.env = AgentEnvironmentView(trusted)

        def _do_calculate_reward(self, timeout=None, model_patch=""):
            agent_view = self.env
            self._trusted_env.sync_workspace()
            self.env = self._trusted_env
            try:
                credentials = {
                    name: os.environ[name] for name in ("GA_JUDGE_KEY", "JUDGE_API_KEY") if os.environ.get(name)
                }
                with self._trusted_env.verifier_phase(self.manifest["verifier"]["command"], credentials):
                    return super()._do_calculate_reward(timeout=timeout, model_patch=model_patch)
            finally:
                self.env = agent_view

        def _write_answer_md(self):
            # Upstream materializes the final reply only during grading, after
            # the first mirror. Refresh afterwards so the verifier consumes the
            # same answer.md it would see through the original shared volume.
            super()._write_answer_md()
            self._trusted_env.sync_workspace()

        def _verify_env_prefix(self, passthrough=None, explicit=None):
            # Published task verify.py supports these selectors, but upstream's
            # forwarding list omits them. Retain every original default/key;
            # forward only these explicit host-side public judge controls.
            if any("KEY" in key for key in (explicit or {})):
                raise ValueError("Judge keys must come from private controller credentials")
            phase = self._trusted_env._verifier_phase
            if phase is not None:
                # Original GA_JUDGE_KEY_FILE fallback runs inside the parent
                # verifier hook; capture its resolved key only after that hook.
                phase[1].update(
                    {name: os.environ[name] for name in ("GA_JUDGE_KEY", "JUDGE_API_KEY") if os.environ.get(name)}
                )
            forward = [
                *(name for name in (passthrough or self.VERIFY_ENV_FORWARD) if "KEY" not in name),
                "GA_JUDGE_API",
                "GA_JUDGE_PHASE_BUDGET",
            ]
            return super()._verify_env_prefix(forward, explicit)

    DATASET_REGISTRY["general_agent"] = IsolatedGeneralAgentEnvironment
    install_general_mcp_transport()


def install_general_mcp_transport():
    from recipes.general import mcp_proxy

    original = mcp_proxy.discover_mcp_tools
    if getattr(original, "_mimo_general_reference_compat", False):
        return

    @functools.wraps(original)
    def discover(environment, *args, **kwargs):
        view = getattr(environment, "mcp_transport_view", None)
        if view is None:
            return original(environment, *args, **kwargs)
        tools = original(view, *args, **kwargs)
        for tool in tools:
            tool.execute = _mcp_execute(tool.execute)
        return tools

    discover._mimo_general_reference_compat = True
    mcp_proxy.discover_mcp_tools = discover


def _mcp_execute(original):
    @functools.wraps(original)
    def execute(params, context=None):
        context = dict(context or {})
        environment = context.get("env")
        if environment is not None and hasattr(environment, "mcp_transport_view"):
            context["env"] = environment.mcp_transport_view
        return original(params, context)

    return execute


def general_execution_overrides(instance, *, run_id):
    """Choose execution profiles from declared type, not cwd or source label."""
    dataset_type = instance.get("dataset_type")
    if dataset_type == "general_agent":
        return {"environment_class": GeneralEnvironment, "run_id": run_id}
    if dataset_type != "terminal_bench":
        raise ValueError("Not a supported General task branch")
    numeric = {}
    for name in ("cpus", "memory_mb", "agent_timeout_sec", "verifier_timeout_sec"):
        value = instance.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Published terminal resource field is missing or invalid: {name}")
        numeric[name] = value
    if type(instance.get("allow_internet")) is not bool:
        raise ValueError("Published terminal network policy must be explicit")
    return {
        "environment_class": ModalEnvironment,
        "run_id": run_id,
        "block_network": not instance["allow_internet"],
        "cpu": numeric["cpus"],
        "memory": math.ceil(numeric["memory_mb"]),
        "sandbox_timeout": math.ceil(numeric["agent_timeout_sec"] + numeric["verifier_timeout_sec"] + 120),
    }


def install_general_environment_routing(*, run_id):
    """Thin per-process bootstrap: keep the original actor and factory body.

    Call in the trainer AND each Ray worker process. Original env_actor imports
    make_dataset_env when _create executes, so this wrapper preserves its setup,
    retries, tools and grading without copying or patching the pinned source.
    """
    from mimoagent.environments import utils

    from .terminal_bench_environment import register_terminal_bench_environment

    register_terminal_bench_environment()
    register_general_environment()
    original = utils.make_dataset_env
    if getattr(original, "_mimo_general_routing_run", None) is not None:
        if original._mimo_general_routing_run != run_id:
            raise RuntimeError("General routing is already installed for a different owned run")
        return

    @functools.wraps(original)
    def routed(instance, **kwargs):
        if instance.get("dataset_type") not in {"terminal_bench", "general_agent"}:
            return original(instance, **kwargs)
        changes = general_execution_overrides(instance, run_id=run_id)
        if instance["dataset_type"] == "terminal_bench":
            # The S3K profile's topology applies only to business tasks. Keep
            # factory-owned reward/image kwargs; remove its deployment topology.
            for key in (
                "sidecars",
                "shared_volumes",
                "main_volume_mounts",
                "mcp_isolation",
                "cpu_request",
                "memory_request",
                "node_selector",
                "kubeconfig",
            ):
                kwargs.pop(key, None)
            labels = kwargs.pop("labels", {})
            kwargs["tags"] = {**kwargs.get("tags", {}), **labels}
        kwargs.update(changes)
        return original(instance, **kwargs)

    routed._mimo_general_routing_run = run_id
    utils.make_dataset_env = routed
