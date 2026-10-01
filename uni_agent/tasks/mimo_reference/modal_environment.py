"""Minimal execution seam for MiMo-Agent 467f0a1's native Modal backend.

The native backend owns command output, file layout and detached execution.
This adapter adds explicit execution users and independently verified cleanup;
it does not replace task tools or scoring. Authentication remains host-side.
"""

from __future__ import annotations

import math
import re
import shlex
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

from mimoagent.environments.modal import ModalEnvironment as NativeModalEnvironment
from mimoagent.environments.modal import ModalEnvironmentConfig as NativeModalEnvironmentConfig

_COPY_USER: ContextVar[str | None] = ContextVar("mimo_reference_copy_user", default=None)


class ModalCleanupError(RuntimeError):
    """An owned sandbox could not be independently confirmed terminated."""


@dataclass
class ModalEnvironmentConfig(NativeModalEnvironmentConfig):
    run_id: str = ""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    exec_user: str | None = None
    max_exec_budget: float = 0
    skip_precheck: bool = False
    cleanup_timeout: float = 30
    cleanup_poll_interval: float = 0.1


class ModalEnvironment(NativeModalEnvironment):
    """Sync mimoagent Environment; execution users are explicit, never global.

    Trusted setup keeps ``as_user=None``. The agent harness must explicitly pass
    its configured ``exec_user`` on commands AND transfers, as MiMo's native
    ``_UserRestrictedEnv`` does. One environment owns exactly one sandbox.
    """

    def __init__(self, *, config_class=ModalEnvironmentConfig, **kwargs):
        super().__init__(config_class=config_class, **kwargs)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", self.config.run_id):
            raise ValueError("Modal reference execution requires a valid owned run_id")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", self.config.session_id):
            raise ValueError("Invalid Modal session_id")
        self._validate_user(self.config.exec_user)
        for name in ("cleanup_timeout", "cleanup_poll_interval"):
            value = getattr(self.config, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if (
            isinstance(self.config.max_exec_budget, bool)
            or not math.isfinite(self.config.max_exec_budget)
            or self.config.max_exec_budget < 0
        ):
            raise ValueError("max_exec_budget must be finite and nonnegative")
        if self.config.gpu or self.config.secrets or self.config.forward_env:
            raise ValueError("Reference task sandboxes require CPU and no forwarded host secrets")
        if type(self.config.block_network) is not bool:
            raise ValueError("block_network must be an explicit boolean")
        self._cumulative_exec_time = 0.0
        self.cleanup_confirmed = False
        self._closed = False
        self._allocation_attempted = False
        self._owned_id: str | None = None
        self._termination_returncode: int | None = None
        self._created_network_blocked = False

    @staticmethod
    def _validate_user(user):
        if user is not None and (not isinstance(user, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", user)):
            raise ValueError("Invalid execution user")

    @property
    def network_blocked(self):
        return self._allocation_attempted and self.sandbox is not None and self._created_network_blocked

    @property
    def evidence(self):
        return {
            "run_id": self.config.run_id,
            "session_id": self.config.session_id,
            "sandbox_id": self._owned_id or self.sandbox_id,
            "allocation_attempted": self._allocation_attempted,
            "cleanup_confirmed": self.cleanup_confirmed,
            "returncode": self._termination_returncode,
        }

    def _sandbox_create_kwargs(self, modal, app, image):
        kwargs = super()._sandbox_create_kwargs(modal, app, image)
        self._created_network_blocked = kwargs["block_network"] is True
        kwargs["tags"] = {
            **self.config.tags,
            "owned_run": self.config.run_id,
            "owned_session": self.config.session_id,
        }
        return kwargs

    def _set_tags(self):
        self._owned_id = self.sandbox_id
        self.config.tags.update(owned_run=self.config.run_id, owned_session=self.config.session_id)
        super()._set_tags()

    @staticmethod
    def _is_permanent_create_error(modal, exc):
        # A lost create acknowledgement may already have allocated a sandbox.
        # Never retry invisibly; the operator must reconcile this session's tags.
        return True

    def start(self):
        if self._closed or self._allocation_attempted:
            raise RuntimeError("Modal environment cannot be restarted or reused")
        self._allocation_attempted = True
        super().start()

    def _exec(self, argv, *, timeout, stdin=None, max_output_bytes=None):
        # Modal's protobuf deadline is integer seconds. Keep native GNU timeout
        # inside argv unchanged, including subsecond command deadlines.
        if timeout is not None:
            if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("Transport timeout must be finite and positive")
            timeout = math.ceil(timeout)
        user = _COPY_USER.get()
        if user is not None:
            argv = ["su", user, "-s", "/bin/sh", "-c", shlex.join(argv)]
        return super()._exec(argv, timeout=timeout, stdin=stdin, max_output_bytes=max_output_bytes)

    def execute(self, command, cwd="", timeout=None, *, as_user=None):
        self._validate_user(as_user)
        if self.sandbox is None or self._closed:
            raise RuntimeError("Modal sandbox is not running")
        if self.config.max_exec_budget > 0 and self._cumulative_exec_time >= self.config.max_exec_budget:
            return {"output": "Exec time budget exhausted", "returncode": 1, "reason": "budget_exhausted"}
        if timeout is not None and (isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("Command timeout must be finite and positive")
        if as_user is not None:
            inner = f"cd {shlex.quote(cwd or self.config.cwd)} && {command}"
            command = f"su {shlex.quote(as_user)} -s /bin/sh -c {shlex.quote(inner)}"
            cwd = "/"
        started = time.monotonic()
        try:
            return super().execute(command, cwd=cwd, timeout=timeout)
        finally:
            self._cumulative_exec_time += time.monotonic() - started

    def copy_to(self, src_path, dest_path, *, timeout=300, max_retries=10, as_user=None):
        self._validate_user(as_user)
        token = _COPY_USER.set(as_user)
        try:
            return super().copy_to(src_path, dest_path, timeout=timeout, max_retries=max_retries)
        finally:
            _COPY_USER.reset(token)

    def copy_out(self, src_path, dest_path, *, timeout=300, max_retries=10, as_user=None):
        self._validate_user(as_user)
        token = _COPY_USER.set(as_user)
        try:
            return super().copy_out(src_path, dest_path, timeout=timeout, max_retries=max_retries)
        finally:
            _COPY_USER.reset(token)

    def cleanup(self):
        if self.cleanup_confirmed:
            return
        if self.sandbox is None:
            if self._allocation_attempted:
                raise ModalCleanupError("Allocation acknowledgement missing; cleanup is indeterminate")
            return
        from modal import Sandbox

        self._owned_id = self._owned_id or self.sandbox_id or self.sandbox.object_id
        deadline = time.monotonic() + self.config.cleanup_timeout
        try:
            self.sandbox.terminate()
            independent = Sandbox.from_id(self._owned_id)
            while True:
                code = independent.poll()
                if type(code) is int:
                    self._termination_returncode = code
                    self.cleanup_confirmed = True
                    self._closed = True
                    self.sandbox = None
                    return
                if code is not None:
                    raise ModalCleanupError("Invalid provider termination status")
                if time.monotonic() >= deadline:
                    raise ModalCleanupError("Owned Modal sandbox termination was not confirmed")
                time.sleep(self.config.cleanup_poll_interval)
        except ModalCleanupError:
            raise
        except Exception as error:
            raise ModalCleanupError("Owned Modal sandbox cleanup failed") from error
