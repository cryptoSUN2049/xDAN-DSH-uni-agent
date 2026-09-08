"""Load a registry selection and render a fixed operator policy, without launching DSH."""

import argparse
import json
import os
from pathlib import Path

from uni_agent.tasks.dsh.memory_artifacts import _directory, _read, _sha
from uni_agent.tasks.dsh.rsi_candidates import Registry

POLICY_SHA256 = "sha256:a81e65c97bfe4ee111d810d060e5921f496a0cab0a92ec8be8f7af619e50c935"
SUPPORTED_TOOLS = {"str_replace_editor", "cordis_inspect_list"}


def build_patch(registry_root, pins_sha256, active_sha256, read_files):
    selection = Registry(registry_root, pins_sha256).load_active(active_sha256)
    if not set(selection["spec"]["allowed_tools"]) <= SUPPORTED_TOOLS:
        raise ValueError("Candidate contains tools outside the canary execution subset")
    policy = Path(__file__).with_name("policy.mjs")
    source = _directory(policy.parent)
    try:
        raw = _read(source, policy.name, 65536)
    finally:
        os.close(source)
    if _sha(raw) != POLICY_SHA256:
        raise ValueError("Pinned RSI policy source mismatch")
    sources = {}
    for value in read_files:
        path = Path(value).absolute()
        directory = _directory(path.parent)
        try:
            raw = _read(directory, path.name, 65536)
        finally:
            os.close(directory)
        if str(path) in sources:
            raise ValueError("Duplicate read file")
        sources[str(path)] = _sha(raw)
    if not sources:
        raise ValueError("Require operator read files")
    patch = [
        {"id": "persistent-bash", "disabled": True},
        {"id": "persistent-pwsh", "disabled": True},
        {
            "insert": [
                {
                    "id": "cordis-host-runner",
                    "name": "@deepseek-ai/dsh-cordis-host-runner",
                    "config": {"vmTimeoutMs": 5000},
                },
                {"id": "tool-cordis", "name": "@deepseek-ai/dsh-tool-cordis"},
            ]
        },
        {
            "insert": [
                {
                    "id": "uni-agent-rsi-closed-policy",
                    "name": policy.as_uri(),
                    "config": {
                        "candidateSha256": selection["candidate_sha256"],
                        "contentSha256": selection["content_sha256"],
                        "activeSha256": active_sha256,
                        "policySha256": POLICY_SHA256,
                        "allowedTools": selection["spec"]["allowed_tools"],
                        "readFiles": list(sources),
                    },
                }
            ]
        },
    ]
    return {
        "patch": patch,
        "selection": selection,
        "policy_sha256": POLICY_SHA256,
        "read_files": sources,
        "profile": "sdk-minimal",
        "runtime_started": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--pins-sha256", required=True)
    parser.add_argument("--active-sha256", required=True)
    parser.add_argument("--read-file", type=Path, action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(build_patch(args.registry, args.pins_sha256, args.active_sha256, args.read_file)))


if __name__ == "__main__":
    main()
