"""Per-process General routing and private controller-side judge setup.

The Ray worker hook must run in every fresh worker. No credential appears in
the composed Hydra config, a student sandbox, or this module's return value.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit


def configure_trusted_judge():
    if not os.environ.get("GA_JUDGE_KEY"):
        location = os.environ.get("MIMO_GENERAL_JUDGE_AUTH_FILE", "")
        if not location:
            raise RuntimeError("A private controller-side General judge credential is required")
        path = Path(location)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("Judge credential must be an absolute regular file")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
            raise PermissionError("Judge credential must be owned by this process with mode 0600")
        auth = json.loads(path.read_text())
        key, url = auth.get("api_key"), auth.get("base_url")
        if not isinstance(key, str) or not key.strip() or not isinstance(url, str):
            raise ValueError("Private judge credential has an invalid contract")
        os.environ["GA_JUDGE_KEY"] = key
        os.environ.setdefault("GA_JUDGE_URL", url)
    url = os.environ.get("GA_JUDGE_URL", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or any((parsed.username, parsed.password, parsed.query, parsed.fragment))
    ):
        raise ValueError("Judge endpoint must be an HTTP base URL without credentials")
    model = os.environ.get("GA_JUDGE_MODEL", "")
    api = os.environ.get("GA_JUDGE_API", "chat")
    if not model or api not in {"chat", "responses"}:
        raise ValueError("Explicit General judge model and supported API selector are required")
    os.environ["GA_JUDGE_API"] = api
    for name in ("VERIFY_DETERMINISTIC", "VERIFY_AGENT_JUDGE"):
        if os.environ.get(name, "1") != "1":
            raise ValueError("General reference tasks require both deterministic and judge rubrics")
        os.environ[name] = "1"
    # Public metadata only. Never return the key or the complete environment.
    return {"authenticated": True, "base_url": url, "model": model, "api": api}


def install():
    """Ray runtime_env.worker_process_setup_hook, also safe for explicit driver use."""
    run_id = os.environ.get("MIMO_GENERAL_RUN_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("General bootstrap requires a valid owned run identity")
    configure_trusted_judge()
    from .general_environment import install_general_environment_routing

    install_general_environment_routing(run_id=run_id)
