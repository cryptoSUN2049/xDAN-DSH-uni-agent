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
import posixpath
import shlex
import tarfile
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .modal_environment import ModalEnvironment, ModalEnvironmentConfig
from .terminal_bench_environment import STUDENT, AgentEnvironmentView

SERVICE = "mimo_service"
WORKSPACE = "/work/workspace"
BRIDGE = "/work/_setup/mcp_bridge.py"


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
        self.mcp_servers = {}
        self.mcp_transport_view = McpTransportView(self)
        if self.config.cwd != WORKSPACE:
            raise ValueError("General business tasks require the original workspace root")
        if self.config.mcp_isolation is not None:
            raise ValueError("Shared-pod MCP firewall profile cannot be used for isolated Modal environments")
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
                    raise RuntimeError(f"General {role} privilege setup failed")
        except Exception:
            self.cleanup()
            raise

    def execute(self, command, cwd="", timeout=None, *, container=None, as_user=None):
        role = container or "main"
        if role not in self._backends:
            raise ValueError("Unknown or unstarted General container")
        if role == "sidecar" and not self._workspace_initialized:
            self.sync_workspace()
        user = as_user or (SERVICE if role == "sidecar" else "root")
        return self._backends[role].execute(command, cwd=cwd or self.config.cwd, timeout=timeout, as_user=user)

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
        backend.copy_to(str(source), dest_path, as_user=as_user or "root", **kwargs)
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
            forward = [*(passthrough or self.VERIFY_ENV_FORWARD), "GA_JUDGE_API", "GA_JUDGE_PHASE_BUDGET"]
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
