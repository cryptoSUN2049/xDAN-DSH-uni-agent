"""Provider policy selected by the operator, never by an agent job request."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

TRACKED_MODAL_IMPORT = "uni_agent.tasks.harbor_dsh.modal_environment:TrackedModalEnvironment"


def validate_gateway_origin(origin: str, *, backend: str = "docker") -> str:
    route = urlsplit(origin)
    if (
        not route.hostname
        or route.path not in ("", "/")
        or route.query
        or route.fragment
        or route.username is not None
        or route.password is not None
    ):
        raise ValueError("Expected an operator-owned Gateway origin without path or credentials")
    if backend == "docker":
        if route.scheme != "http" or route.hostname != "host.docker.internal" or not route.port:
            raise ValueError("Expected operator-owned Docker-to-host HTTP tunnel origin")
    elif backend == "modal":
        hostname = route.hostname
        if (
            route.scheme != "https"
            or "." not in hostname
            or hostname.endswith((".localhost", ".local", ".internal"))
            or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in hostname.split("."))
        ):
            raise ValueError("Modal requires a public HTTPS Gateway hostname")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("Modal Gateway must use a public DNS hostname")
        # Accessing port also rejects malformed/out-of-range ports.
        if route.port is not None and route.port <= 0:
            raise ValueError("Invalid Gateway port")
    else:
        raise ValueError("Unsupported environment backend")
    return origin.rstrip("/")


def validate_modal_task(task_dir: Path, task: dict, *, gateway_origin: str, release_digest: str) -> None:
    """Freeze the initial Direct-mode, host-trace-only execution contract."""
    origin = validate_gateway_origin(gateway_origin, backend="modal")
    if any(task_dir.rglob("*compose*.y*ml")):
        raise ValueError("Modal Direct tasks cannot contain Compose definitions")
    if task.get("artifacts") or task.get("steps"):
        raise ValueError("Modal initially supports single-step host trace artifacts only")
    environment = task.get("environment", {})
    verifier = task.get("verifier", {})
    verifier_env = verifier.get("environment", {})
    image = environment.get("docker_image", "")
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}", image)
        or image.rsplit("@", 1)[-1] != release_digest
    ):
        raise ValueError("Modal requires a registry image pinned to the approved release digest")
    if environment.get("network_mode") != "allowlist" or environment.get("allowed_hosts") != [
        urlsplit(origin).hostname
    ]:
        raise ValueError("Modal agent network must allow only the exact Gateway hostname")
    if (
        verifier.get("environment_mode") != "separate"
        or verifier_env.get("network_mode") != "no-network"
        or verifier_env.get("allowed_hosts")
    ):
        raise ValueError("Modal requires an explicit independent no-network verifier")
    for role in (task.get("agent", {}), verifier):
        if role.get("network_mode") is not None or role.get("allowed_hosts") is not None:
            raise ValueError("Modal task cannot override phase network policies")
    for env in (environment, verifier_env):
        if env.get("gpus") or env.get("gpu_types") or env.get("tpu"):
            raise ValueError("Modal task sandbox must not allocate accelerators")
