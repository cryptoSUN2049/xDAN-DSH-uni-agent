"""Cloud CPU contract tests. Fake transports never prove live task acceptance."""

import base64
import hashlib
import importlib
import importlib.util
import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("mimoagent") is None:
    pytest.importorskip("mimoagent", reason="Fixed MiMo-Agent reference source is only installed in cloud execution")

_general = importlib.import_module("uni_agent.tasks.mimo_reference.general_environment")
_terminal = importlib.import_module("uni_agent.tasks.mimo_reference.terminal_bench_environment")
BRIDGE, SERVICE, WORKSPACE = _general.BRIDGE, _general.SERVICE, _general.WORKSPACE
GeneralEnvironment, McpTransportView, _mcp_execute = (
    _general.GeneralEnvironment,
    _general.McpTransportView,
    _general._mcp_execute,
)
REWARD_FILE, SCHEMA, STUDENT = _terminal.REWARD_FILE, _terminal.SCHEMA, _terminal.STUDENT
AgentEnvironmentView, TerminalBenchEnvironment = _terminal.AgentEnvironmentView, _terminal.TerminalBenchEnvironment
decode_tests_files = _terminal.decode_tests_files
register_terminal_bench_environment = _terminal.register_terminal_bench_environment


def instance(**changes):
    files = {
        "test.sh": f"#!/bin/sh\n# anti_hack_guard.py\nprintf '0\\n' > {REWARD_FILE}\n".encode(),
        "anti_hack_guard.py": b"# original guard bytes\n",
        "fixtures/pristine_env_manifest.json": b'{"files":{}}\n',
        "test_outputs.py": b"# original pytest bytes\n",
    }
    result = {
        "instance_id": "contract-only",
        "dataset_type": "terminal_bench",
        "schema_version": SCHEMA,
        "cwd": "/app",
        "allow_internet": False,
        "problem_statement": "contract fixture",
        "verifier_timeout_sec": 120,
        "tests_files": json.dumps({name: base64.b64encode(data).decode() for name, data in files.items()}),
    }
    result.update(changes)
    return result


class Transport:
    def __init__(self, **kwargs):
        self.config = SimpleNamespace(**kwargs)
        self.commands = []
        self.transfers = []
        self.network_blocked = True
        self.reward = "0\n"
        self.verifier_rc = 0
        self.verifier_reason = "ok"
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def cleanup(self):
        self.closed = True

    def execute(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if command == "/bin/sh /tests/test.sh":
            return {"output": "real-script-contract", "returncode": self.verifier_rc, "reason": self.verifier_reason}
        if command == f"cat -- {REWARD_FILE}":
            return {"output": self.reward, "returncode": 0, "reason": "ok"}
        return {"output": "", "returncode": 0, "reason": "ok"}

    def copy_to(self, src, dest, **kwargs):
        self.transfers.append((dest, Path(src).read_bytes() if Path(src).is_file() else None, kwargs))

    def copy_out(self, src, dest, **kwargs):
        with tarfile.open(dest, "w:gz") as archive:
            entry = tarfile.TarInfo("./answer.md")
            entry.size = 6
            archive.addfile(entry, io.BytesIO(b"answer"))

    @property
    def evidence(self):
        return {"contract_mock": True, "started": self.started, "closed": self.closed}


def general_config(**changes):
    result = {
        "image": "fixed-test-image",
        "run_id": "contract-only",
        "sidecars": [
            {
                "name": "sidecar",
                "volume_mounts": [
                    {"name": "workspace", "mount_path": WORKSPACE, "read_only": True},
                    {"name": "system-vol", "mount_path": "/work/system"},
                ],
            }
        ],
    }
    result.update(changes)
    return result


def test_base64_files_remain_exact():
    decoded = decode_tests_files(instance())
    assert decoded["test_outputs.py"] == b"# original pytest bytes\n"
    environment = TerminalBenchEnvironment(Transport(), instance())
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in decoded.items()}
    assert environment._test_hashes == expected


@pytest.mark.parametrize(
    "path", ["/test.sh", "../test.sh", "a/../test.sh", "a//test.sh", "./test.sh", "a\\b", "a\x00b"]
)
def test_test_file_traversal_rejected(path):
    value = instance()
    files = json.loads(value["tests_files"])
    files[path] = base64.b64encode(b"payload").decode()
    with pytest.raises(ValueError):
        decode_tests_files({**value, "tests_files": files})


@pytest.mark.parametrize("payload", [None, [], {}, {"test.sh": "not base64"}, {"test.sh": 1}])
def test_invalid_file_mapping_rejected(payload):
    with pytest.raises(ValueError):
        decode_tests_files(instance(tests_files=payload))


def test_unknown_reward_protocol_and_missing_guard_rejected():
    files = json.loads(instance()["tests_files"])
    files["test.sh"] = base64.b64encode(b"exit 0\n").decode()
    with pytest.raises(ValueError, match="protocol"):
        decode_tests_files(instance(tests_files=files))
    del files["anti_hack_guard.py"]
    with pytest.raises(ValueError, match="materials"):
        decode_tests_files(instance(tests_files=files))


@pytest.mark.parametrize("timeout", [None, False, 0, -1, float("nan"), float("inf"), "120"])
def test_bad_timeout_rejected(timeout):
    with pytest.raises(ValueError):
        TerminalBenchEnvironment(Transport(), instance(verifier_timeout_sec=timeout))


def test_no_network_policy_no_rollout():
    transport = Transport()
    transport.network_blocked = False
    environment = TerminalBenchEnvironment(transport, instance())
    with pytest.raises(RuntimeError, match="no-internet"):
        environment.setup_environment()
    assert transport.transfers == []


def test_hidden_tests_only_uploaded_after_rollout_and_student_is_restricted():
    transport = Transport()
    environment = TerminalBenchEnvironment(transport, instance())
    environment.setup_environment()
    assert transport.transfers == []
    environment.env.execute("cat /app/output.json", timeout=10)
    assert transport.commands[-1][1]["as_user"] == STUDENT
    reward, _, extra = environment._do_calculate_reward()
    assert reward == 0 and "error_category" not in extra
    assert all(transfer[2]["as_user"] == "root" for transfer in transport.transfers)
    assert {dest.removeprefix("/tests/"): data for dest, data, _ in transport.transfers} == decode_tests_files(
        instance()
    )
    verify = next(kwargs for command, kwargs in transport.commands if command == "/bin/sh /tests/test.sh")
    assert verify["timeout"] == 120 and verify["as_user"] == "root"


@pytest.mark.parametrize("rc,reward,expected", [(0, "0\n", 0), (1, "0\n", 0), (0, "1\n", 1)])
def test_score_comes_from_reward_file_not_exit_code(rc, reward, expected):
    transport = Transport()
    transport.verifier_rc, transport.reward = rc, reward
    score, _, extra = TerminalBenchEnvironment(transport, instance())._do_calculate_reward()
    assert score == expected and "error_category" not in extra


@pytest.mark.parametrize("raw", ["", "nan", "inf", "0.5", "2", "1\n0", "True"])
def test_invalid_reward_is_infra(raw):
    transport = Transport()
    transport.reward = raw
    score, _, extra = TerminalBenchEnvironment(transport, instance())._do_calculate_reward()
    assert score == 0 and extra["reward_error"] == "missing_or_invalid_reward_txt"


def test_timeout_does_not_accept_a_stale_reward():
    transport = Transport()
    transport.reward, transport.verifier_reason = "1\n", "timeout"
    score, _, extra = TerminalBenchEnvironment(transport, instance())._do_calculate_reward()
    assert score == 0 and extra["reward_error"] == "verifier_incomplete"
    assert not any(command.startswith("cat -- ") for command, _ in transport.commands)


@pytest.mark.parametrize("kwargs", [{"as_user": "root"}, {"container": "sidecar"}])
def test_agent_cannot_select_privileges(kwargs):
    view = AgentEnvironmentView(Transport())
    with pytest.raises(PermissionError):
        view.execute("cat /work/system/state.db", **kwargs)
    with pytest.raises(PermissionError):
        view.copy_to("unused", "unused", **kwargs)


def test_register_missing_type_without_relabel():
    from mimoagent.environments.datasets import DATASET_REGISTRY

    previous = DATASET_REGISTRY.pop("terminal_bench", None)
    try:
        register_terminal_bench_environment()
        assert DATASET_REGISTRY["terminal_bench"] is TerminalBenchEnvironment
        DATASET_REGISTRY["terminal_bench"] = object
        with pytest.raises(RuntimeError):
            register_terminal_bench_environment()
    finally:
        DATASET_REGISTRY.pop("terminal_bench", None)
        if previous is not None:
            DATASET_REGISTRY["terminal_bench"] = previous


def test_two_environments_keep_hidden_state_separate(tmp_path):
    environment = GeneralEnvironment(backend_factory=Transport, **general_config())
    environment.start()
    assert environment._backends["main"] is not environment._backends["sidecar"]
    assert environment._backends["main"].config.session_id != environment._backends["sidecar"].config.session_id
    source = tmp_path / "state.db"
    source.write_bytes(b"initial-state")
    with pytest.raises(PermissionError):
        environment.copy_to(str(source), "/work/system/state.db")
    environment.copy_to(str(source), "/work/system/state.db", container="sidecar")
    assert not environment._backends["main"].transfers
    assert environment._backends["sidecar"].transfers[0][0] == "/work/system/state.db"
    environment.cleanup()
    assert all(backend.closed for backend in environment._backends.values())


@pytest.mark.parametrize(
    "changes",
    [{"cwd": "/app"}, {"main_volume_mounts": [{"name": "system-vol"}]}, {"sidecars": []}],
)
def test_bad_general_topology_rejected(changes):
    with pytest.raises(ValueError):
        GeneralEnvironment(backend_factory=Transport, **general_config(**changes))


def test_workspace_snapshot_is_readonly_and_mcp_keeps_original_command():
    environment = GeneralEnvironment(backend_factory=Transport, **general_config())
    environment.start()
    environment.mcp_bridge_python = "python3"
    environment.mcp_bridge_script = BRIDGE
    environment.mcp_servers = {"registry": {"url": "http://127.0.0.1:39101/mcp"}}
    command = f"python3 {BRIDGE} --url http://127.0.0.1:39101/mcp --name registry --call get --args-json '{{}}'"
    environment.mcp_transport_view.execute(command, timeout=120)
    sidecar = environment._backends["sidecar"]
    assert any("chmod 0444" in script and kwargs["as_user"] == "root" for script, kwargs in sidecar.commands)
    assert sidecar.commands[-1][1]["as_user"] == SERVICE
    assert "--call get" in sidecar.commands[-1][0]
    with pytest.raises(PermissionError):
        environment.mcp_transport_view.execute("cat /work/system/state.db")
    with pytest.raises(PermissionError):
        environment.mcp_transport_view.execute(command.replace("--name registry", "--name other"))


def test_only_mcp_tool_context_routes_to_sidecar():
    environment = SimpleNamespace(mcp_transport_view=McpTransportView(None))
    observed = []

    def tool(params, context):
        observed.append(context)
        return "original-result"

    wrapped = _mcp_execute(tool)
    context = {"env": environment, "other": 1}
    assert wrapped({"a": 1}, context) == "original-result"
    assert context["env"] is environment
    assert observed[0]["env"] is environment.mcp_transport_view


def test_original_general_verifier_stays_sidecar_only(tmp_path, monkeypatch):
    from mimoagent.environments.datasets import DATASET_REGISTRY
    from recipes.general import mcp_proxy

    monkeypatch.setitem(DATASET_REGISTRY, "general_agent", object)
    monkeypatch.setattr(mcp_proxy, "discover_mcp_tools", lambda *args, **kwargs: [])
    _general.register_general_environment()
    registered = DATASET_REGISTRY["general_agent"]
    from recipes.general.general_agent import register_general_agent_env

    # The original _create calls this function. It uses setdefault, so our
    # registered narrow subclass survives that real registration order.
    register_general_agent_env()
    assert DATASET_REGISTRY["general_agent"] is registered
    _general.register_general_environment()
    assert DATASET_REGISTRY["general_agent"] is registered
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "input.csv").write_text("initial data")
    (tmp_path / "system").mkdir()
    (tmp_path / "system" / "state.db").write_bytes(b"contract-state")
    (tmp_path / "run_verify.py").write_text("# verifier is never uploaded to main")
    (tmp_path / "answer_key.json").write_text('{"hidden":true}')
    transport = GeneralEnvironment(backend_factory=Transport, **general_config())
    business = registered(
        transport,
        {
            "instance_id": "business-contract",
            "dataset_type": "general_agent",
            "env_task_dir": str(tmp_path),
            "cwd": WORKSPACE,
            "problem_statement": "contract only",
        },
    )
    business.setup_environment()
    assert isinstance(business.env, AgentEnvironmentView)
    assert not any("answer_key" in dest for backend in transport._backends.values() for dest, _, _ in backend.transfers)
    monkeypatch.delenv("GA_JUDGE_KEY", raising=False)
    monkeypatch.delenv("GA_JUDGE_KEY_FILE", raising=False)
    reward, _, extra = business._do_calculate_reward()
    assert reward == 0 and extra["reward_error"] == "judge_key_missing"
    assert isinstance(business.env, AgentEnvironmentView)
    monkeypatch.setenv("GA_JUDGE_KEY", "EMPTY")
    reward, _, extra = business._do_calculate_reward()
    assert reward == 0 and extra["reward_error"] == "missing_or_invalid_reward_json"
    assert any(dest == "/work/answer_key.json" for dest, _, _ in transport._backends["sidecar"].transfers)
    assert not any("answer_key" in dest for dest, _, _ in transport._backends["main"].transfers)
    assert isinstance(business.env, AgentEnvironmentView)
    # Upstream creates a missing answer.md while grading, after our initial
    # snapshot. The transport must mirror again after that original hook.
    from recipes.general.general_agent.environment import GeneralAgentEnvironment

    calls = []
    monkeypatch.setattr(GeneralAgentEnvironment, "_write_answer_md", lambda self: calls.append("original-final-reply"))
    monkeypatch.setattr(transport, "sync_workspace", lambda: calls.append("mirror"))
    business._write_answer_md()
    assert calls == ["original-final-reply", "mirror"]
    monkeypatch.setenv("GA_JUDGE_API", "chat")
    monkeypatch.setenv("GA_JUDGE_PHASE_BUDGET", "600")
    prefix = business._verify_env_prefix()
    assert "GA_JUDGE_API=chat" in prefix and "GA_JUDGE_PHASE_BUDGET=600" in prefix
    assert "VERIFY_AGENT_JUDGE=1" in prefix and "VERIFY_DETERMINISTIC=1" in prefix


def test_partial_start_cleanup_is_not_ignored():
    backends = []

    class Broken(Transport):
        def start(self):
            if "sidecar" in self.config.session_id:
                raise RuntimeError("simulated allocation failure")
            super().start()

    def factory(**kwargs):
        backend = Broken(**kwargs)
        backends.append(backend)
        return backend

    environment = GeneralEnvironment(backend_factory=factory, **general_config())
    with pytest.raises(RuntimeError, match="allocation"):
        environment.start()
    assert len(backends) == 2 and all(backend.closed for backend in backends)
    with pytest.raises(RuntimeError, match="reused"):
        environment.start()


def test_cleanup_reports_each_failed_owned_backend():
    class Broken(Transport):
        def cleanup(self):
            raise RuntimeError("termination not confirmed")

    environment = GeneralEnvironment(backend_factory=Broken, **general_config())
    environment.start()
    with pytest.raises(RuntimeError, match="main: RuntimeError, sidecar: RuntimeError"):
        environment.cleanup()


def test_snapshot_symlink_cannot_escape_into_sidecar():
    class Unsafe(Transport):
        def copy_out(self, src, dest, **kwargs):
            with tarfile.open(dest, "w:gz") as archive:
                entry = tarfile.TarInfo("./escape")
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/work/system"
                archive.addfile(entry)

    environment = GeneralEnvironment(backend_factory=Unsafe, **general_config())
    environment.start()
    with pytest.raises(RuntimeError, match="Unsafe workspace"):
        environment.sync_workspace()
    assert not environment._backends["sidecar"].transfers


@pytest.mark.parametrize("path", ["/", "relative", "/app/../root", "/app/"])
def test_invalid_terminal_cwd(path):
    with pytest.raises(ValueError, match="cwd"):
        TerminalBenchEnvironment(Transport(), instance(cwd=path))


def test_transfer_user_is_also_enforced(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"data")
    transport = Transport()
    view = AgentEnvironmentView(transport)
    view.copy_to(str(path), "/app/file")
    assert transport.transfers[-1][2]["as_user"] == STUDENT
    view.copy_out("/app/file", str(tmp_path / "copied"))


@pytest.mark.parametrize(
    "suffix", ["--url http://wrong --name registry --list", "--url http://127.0.0.1:39101/mcp --name registry --shell"]
)
def test_bridge_endpoint_and_argv_are_not_shell_backdoors(suffix):
    environment = GeneralEnvironment(backend_factory=Transport, **general_config())
    environment.mcp_bridge_python = "python3"
    environment.mcp_bridge_script = BRIDGE
    environment.mcp_servers = {"registry": {"url": "http://127.0.0.1:39101/mcp"}}
    with pytest.raises(PermissionError):
        environment.mcp_transport_view.execute(f"python3 {BRIDGE} {suffix}")


def test_copy_rejects_asset_symlinks_and_normalization(tmp_path):
    source = tmp_path / "file"
    source.write_text("data")
    link = tmp_path / "link"
    link.symlink_to(source)
    environment = GeneralEnvironment(backend_factory=Transport, **general_config())
    environment.start()
    with pytest.raises(ValueError, match="symlinks"):
        environment.copy_to(str(link), WORKSPACE + "/file")
    with pytest.raises(ValueError, match="canonical"):
        environment.copy_to(str(source), WORKSPACE + "/../system/file")


def test_explicit_general_branches_select_different_execution_profiles():
    terminal = instance(cpus=1, memory_mb=2048, agent_timeout_sec=900)
    overrides = _general.general_execution_overrides(terminal, run_id="owned-contract")
    assert overrides["environment_class"] is _general.ModalEnvironment
    assert overrides["block_network"] is True
    assert overrides["cpu"] == 1 and overrides["memory"] == 2048
    assert overrides["sandbox_timeout"] == 1140
    business = _general.general_execution_overrides({"dataset_type": "general_agent"}, run_id="owned-contract")
    assert business["environment_class"] is GeneralEnvironment
    with pytest.raises(ValueError):
        _general.general_execution_overrides({"dataset_type": "generic"}, run_id="owned-contract")


def test_shared_pod_firewall_profile_cannot_silently_apply_to_separate_vms():
    with pytest.raises(ValueError, match="Shared-pod"):
        GeneralEnvironment(backend_factory=Transport, **general_config(mcp_isolation={"agent_uid": 500}))


def test_real_pinned_factory_constructs_both_general_types_without_allocation(tmp_path, monkeypatch):
    from mimoagent.environments import utils
    from mimoagent.environments.datasets import DATASET_REGISTRY
    from recipes.general import mcp_proxy

    # Exercise the real fixed factory/filter/registry, not a second imitation.
    monkeypatch.setattr(utils, "make_dataset_env", utils.make_dataset_env)
    monkeypatch.setattr(mcp_proxy, "discover_mcp_tools", mcp_proxy.discover_mcp_tools)
    monkeypatch.setitem(DATASET_REGISTRY, "terminal_bench", TerminalBenchEnvironment)
    monkeypatch.setitem(DATASET_REGISTRY, "general_agent", object)
    _general.install_general_environment_routing(run_id="factory-contract")
    value = instance(cpus=1, memory_mb=2048, agent_timeout_sec=900, docker_image="fixed-terminal-image")
    terminal = utils.make_dataset_env(value, **general_config(), image_prefix="docker.io/reference")
    assert isinstance(terminal, TerminalBenchEnvironment)
    assert terminal.env.config.image == "docker.io/reference/fixed-terminal-image"
    assert terminal.env.config.cwd == "/app" and terminal.env.config.run_id == "factory-contract"
    assert terminal.env.config.block_network is True and terminal.env.sandbox is None
    value = {
        "dataset_type": "general_agent",
        "instance_id": "factory-business",
        "env_task_dir": str(tmp_path),
        "docker_image": "fixed-business-image",
        "cwd": WORKSPACE,
    }
    business = utils.make_dataset_env(value, **general_config())
    assert isinstance(business.env, GeneralEnvironment)
    assert business.env.config.image == "fixed-business-image" and not business.env._backends


def test_factory_dispatch_keeps_original_non_general_routes(monkeypatch):
    from mimoagent.environments import utils
    from mimoagent.environments.datasets import DATASET_REGISTRY
    from recipes.general import mcp_proxy

    observed = []

    def original(value, **kwargs):
        observed.append((value, kwargs))
        return "original-result"

    monkeypatch.setattr(utils, "make_dataset_env", original)
    monkeypatch.setattr(mcp_proxy, "discover_mcp_tools", lambda *args, **kwargs: [])
    monkeypatch.setitem(DATASET_REGISTRY, "terminal_bench", TerminalBenchEnvironment)
    monkeypatch.setitem(DATASET_REGISTRY, "general_agent", object)
    _general.install_general_environment_routing(run_id="owned-contract")
    _general.install_general_environment_routing(run_id="owned-contract")
    value = instance(cpus=1, memory_mb=2048, agent_timeout_sec=900)
    result = utils.make_dataset_env(value, **general_config(), labels={"exp": "contract"}, reward_mode="programmatic")
    assert result == "original-result"
    assert observed[-1][0] is value
    kwargs = observed[-1][1]
    assert kwargs["environment_class"] is _general.ModalEnvironment
    assert "sidecars" not in kwargs and kwargs["tags"]["exp"] == "contract"
    assert kwargs["reward_mode"] == "programmatic"
    value = {"dataset_type": "general_agent"}
    utils.make_dataset_env(value, **general_config())
    assert observed[-1][1]["environment_class"] is GeneralEnvironment
    assert observed[-1][1]["sidecars"] == general_config()["sidecars"]
    value = {"dataset_type": "arvo"}
    utils.make_dataset_env(value, environment_class="original-arvo")
    assert observed[-1] == (value, {"environment_class": "original-arvo"})
    with pytest.raises(RuntimeError, match="different"):
        _general.install_general_environment_routing(run_id="another-run")


def test_fixed_published_parquet_contract_when_available():
    source = os.environ.get("MIMO_REFERENCE_GENERAL_PARQUET")
    if not source:
        pytest.skip("Cloud-only fixed Parquet contract check was not requested")
    import pyarrow.parquet as pq

    data = Path(source).read_bytes()
    assert hashlib.sha256(data).hexdigest() == "9bfdc8b05d2bf2cb9e89815443d35507e4be30368aebf70928421795c10259b9"
    count = 0
    for row in pq.read_table(io.BytesIO(data)).to_pylist():
        value = json.loads(row["extra_info"]["instance_json"])
        if value["dataset_type"] != "terminal_bench":
            continue
        files = decode_tests_files(value)
        assert b"/tests/anti_hack_guard.py" in files["test.sh"]
        assert b"/logs/verifier/reward.txt" in files["test.sh"]
        count += 1
    assert count == 64
