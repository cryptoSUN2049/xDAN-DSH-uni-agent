"""Published MiMo terminal tasks: late-upload exact tests and read reward.txt.

Compatibility seam for the terminal_bench type missing from MiMo-Agent 467f0a.
The published tbench-terminal-bench.v1 files contain base64 bytes, not source
text. The original test.sh, including its anti-hack guard, remains unchanged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import posixpath
import shlex
import tempfile
from pathlib import Path, PurePosixPath

from mimoagent.environments.datasets.base import REWARD_TESTBED_CORRUPTED, DatasetEnvironment

STUDENT = "mimo_student"
REWARD_FILE = "/logs/verifier/reward.txt"
SCHEMA = "tbench-terminal-bench.v1"


def decode_tests_files(instance: dict) -> dict[str, bytes]:
    """Validate the published contract before touching a sandbox."""
    if instance.get("dataset_type") != "terminal_bench" or instance.get("schema_version") != SCHEMA:
        raise ValueError("Expected the published terminal_bench v1 instance")
    payload = instance.get("tests_files")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict) or not payload:
        raise ValueError("tests_files must be a nonempty base64 file mapping")
    decoded = {}
    for name, encoded in payload.items():
        if not isinstance(name, str) or not isinstance(encoded, str):
            raise ValueError("tests_files names and base64 values must be strings")
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or path.is_absolute()
            or any(part in {".", ".."} for part in name.split("/"))
            or str(path) != name
        ):
            raise ValueError("Unsafe or noncanonical tests_files path")
        try:
            decoded[name] = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError(f"Invalid base64 test file: {name}") from error
    required = {"test.sh", "anti_hack_guard.py", "fixtures/pristine_env_manifest.json"}
    if not required <= decoded.keys():
        raise ValueError("Published verifier or anti-hack materials missing")
    if REWARD_FILE.encode() not in decoded["test.sh"]:
        raise ValueError("Unknown test.sh reward protocol; refusing to guess")
    return decoded


class AgentEnvironmentView:
    """Agent tools can execute only as a student in the main environment."""

    def __init__(self, environment, *, user=STUDENT):
        self._environment = environment
        self._user = user

    def __getattr__(self, name):
        if name in {"execute", "copy_to", "copy_out", "copy_from"}:
            raise AttributeError(name)
        return getattr(self._environment, name)

    def execute(self, command, cwd="", timeout=None, *, container=None, as_user=None):
        if container not in (None, "main") or as_user not in (None, self._user):
            raise PermissionError("Agent cannot select a trusted container or execution user")
        return self._environment.execute(command, cwd=cwd, timeout=timeout, as_user=self._user)

    def copy_to(self, src_path, dest_path, **kwargs):
        self._check_transfer(kwargs)
        return self._environment.copy_to(src_path, dest_path, as_user=self._user, **kwargs)

    def copy_out(self, src_path, dest_path, **kwargs):
        self._check_transfer(kwargs)
        return self._environment.copy_out(src_path, dest_path, as_user=self._user, **kwargs)

    def _check_transfer(self, kwargs):
        if kwargs.pop("container", None) not in (None, "main"):
            raise PermissionError("Agent cannot transfer trusted-container files")
        if kwargs.pop("as_user", None) not in (None, self._user):
            raise PermissionError("Agent cannot transfer files as another user")


class TerminalBenchEnvironment(DatasetEnvironment):
    HAS_VERIFIER = True
    _ANTI_HACK_CLEANUP_DEFAULT = False
    _GIT_LEAK_PREVENTION_DEFAULT = "none"

    def __init__(self, base_env, instance):
        super().__init__(base_env, instance)
        self._trusted_env = base_env
        self._test_files = decode_tests_files(instance)
        self._test_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in self._test_files.items()}
        self._timeout = instance.get("verifier_timeout_sec")
        if isinstance(self._timeout, bool) or not isinstance(self._timeout, (int, float)):
            raise ValueError("verifier_timeout_sec must be explicitly supplied")
        if not math.isfinite(self._timeout) or self._timeout <= 0:
            raise ValueError("verifier_timeout_sec must be positive and finite")
        cwd = instance.get("cwd")
        if not isinstance(cwd, str) or not cwd.startswith("/") or posixpath.normpath(cwd) != cwd or cwd == "/":
            raise ValueError("terminal cwd must be a canonical absolute task directory")

    @property
    def repo_path(self):
        return self.instance["cwd"]

    def setup_environment(self):
        super().setup_environment()
        self.env = AgentEnvironmentView(self._trusted_env)

    def _setup_dataset_specific(self):
        # A no-internet row needs a backend with actually enforced network policy.
        # Tags or an unused config flag are not proof of enforcement.
        if self.instance.get("allow_internet") is False and not getattr(self._trusted_env, "network_blocked", False):
            raise RuntimeError("terminal task requires an enforced no-internet sandbox")
        command = (
            "set -eu\n"
            f"id {STUDENT} >/dev/null 2>&1 || useradd -m -s /bin/sh {STUDENT}\n"
            "rm -rf -- /tests /logs/verifier\n"
            "mkdir -p /tests /logs/verifier\n"
            "chown root:root /tests /logs /logs/verifier\n"
            "chmod 0700 /tests /logs /logs/verifier\n"
            f"chown -R {STUDENT}:{STUDENT} {shlex.quote(self.repo_path)}\n"
            f"su {STUDENT} -s /bin/sh -c 'test ! -r /tests/test.sh && test ! -r /logs/verifier/reward.txt'\n"
        )
        result = self._trusted_env.execute(command, cwd="/", timeout=120, as_user="root")
        if result.get("returncode") != 0:
            raise RuntimeError("terminal student/verifier isolation setup failed")

    def _capture_model_diff(self):
        # Terminal tasks need not be Git worktrees. Do not introduce git add.
        return "", ""

    def _infra(self, reason, output="", **extra):
        return 0.0, output, {"error_category": REWARD_TESTBED_CORRUPTED, "reward_error": reason, **extra}

    def _do_calculate_reward(self, timeout=None, model_patch=""):
        budget = self._timeout if timeout is None else min(self._timeout, timeout)
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
            raise ValueError("Verifier timeout must be positive and finite")
        trusted = self._trusted_env
        cleared = trusted.execute(
            "rm -rf -- /tests && mkdir -p /tests /logs/verifier && chmod 0700 /tests /logs/verifier "
            f"&& rm -f -- {REWARD_FILE} /logs/verifier/ctrf.json",
            cwd="/",
            timeout=60,
            as_user="root",
        )
        if cleared.get("returncode") != 0:
            return self._infra("clear_verifier_failed")
        with tempfile.TemporaryDirectory(prefix="mimo-terminal-tests-") as directory:
            for name, data in self._test_files.items():
                local = Path(directory, name)
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
                trusted.copy_to(str(local), f"/tests/{name}", as_user="root")
        # Published numeric seconds may be a JSON float, while Modal's exec
        # timeout field accepts integer seconds. Preserve the source limit at
        # the provider's whole-second resolution rather than failing grading.
        result = trusted.execute(
            "/bin/sh /tests/test.sh", cwd=self.repo_path, timeout=math.ceil(budget), as_user="root"
        )
        output = result.get("output", "")
        if result.get("reason") not in (None, "", "ok") or result.get("returncode") in (None, 124, 137):
            return self._infra("verifier_incomplete", output, verifier_returncode=result.get("returncode"))
        read = trusted.execute(f"cat -- {REWARD_FILE}", cwd="/", timeout=30, as_user="root")
        raw = (read.get("output") or "").strip()
        if read.get("returncode") != 0 or raw not in ("0", "1"):
            return self._infra("missing_or_invalid_reward_txt", output, verifier_returncode=result.get("returncode"))
        # In the published script a guard rejection writes 0 and exits 0.
        # Conversely pytest failure writes 0 and exits nonzero. Read the file.
        reward = float(raw)
        return (
            reward,
            output,
            {
                "verifier_returncode": result.get("returncode"),
                "resolved": reward == 1.0,
                "reward_protocol": REWARD_FILE,
                "tests_files_sha256": self._test_hashes,
                "reference_compat": "terminal_bench_v1_missing_registry",
            },
        )


def register_terminal_bench_environment():
    from mimoagent.environments.datasets import DATASET_REGISTRY

    current = DATASET_REGISTRY.get("terminal_bench")
    if current is not None and current is not TerminalBenchEnvironment:
        raise RuntimeError("terminal_bench already has a different registered environment")
    DATASET_REGISTRY["terminal_bench"] = TerminalBenchEnvironment
