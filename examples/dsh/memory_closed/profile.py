"""Operator-generated sdk-minimal overlay; never load evolution.patch alongside it."""

from pathlib import Path


def build_memory_patch(*, role, chain_id, session_id, source_version, read_files, write_file):
    policy = Path(__file__).with_name("policy.mjs").resolve()
    return [
        {"id": "persistent-bash", "disabled": True},
        {"id": "persistent-pwsh", "disabled": True},
        {
            "insert": [
                {
                    "id": "uni-agent-memory-closed-policy",
                    "name": policy.as_uri(),
                    "config": {
                        "role": role,
                        "chainId": chain_id,
                        "sessionId": session_id,
                        "sourceVersion": source_version,
                        "readFiles": [str(p) for p in read_files],
                        "writeFile": None if write_file is None else str(write_file),
                    },
                }
            ]
        },
    ]
