"""Controller-only exact file policy; legacy memory profile is unchanged."""

from pathlib import Path


def build_work_state_patch(*, role, chain_id, session_id, source_version, read_files, write_files, read_missing=()):
    return [
        {"id": "persistent-bash", "disabled": True},
        {"id": "persistent-pwsh", "disabled": True},
        {
            "insert": [
                {
                    "id": "uni-agent-work-state-closed-policy",
                    "name": Path(__file__).with_name("policy.mjs").as_uri(),
                    "config": dict(
                        role=role,
                        chainId=chain_id,
                        sessionId=session_id,
                        sourceVersion=source_version,
                        readFiles=[str(p) for p in read_files],
                        writeFiles=[str(p) for p in write_files],
                        readMissing=[str(p) for p in read_missing],
                    ),
                }
            ]
        },
    ]
