"""Frozen Harbor patch mapping; file-byte identity differs from ordered-path identity.

Only the operator-selected empty composition or this reviewed T2 patch is allowed.
No runtime, training, Harbor or model dependencies belong in this module.
"""

import hashlib
import json

T2_PATCH_PATH = "/opt/dsh-patches/evolution.patch.yml"
T2_PATCH_SHA256 = "sha256:edace17a8096ec41e572c10fc7ad96f0d9a62c0a6ff9c8271694b4c1b1024aeb"
T2_STRATEGY = "t2-log-tool"


def release_patch_paths(release) -> tuple[str, ...]:
    if release.profile != "sdk-minimal":
        raise ValueError("Harbor release requires sdk-minimal profile")
    hashes = tuple(release.patch_sha256s)
    if not hashes:
        return ()
    if hashes == (T2_PATCH_SHA256,):
        return (T2_PATCH_PATH,)
    raise ValueError("Harbor release patch hashes are not approved")


def release_patch_paths_digest(release) -> str:
    raw = json.dumps(list(release_patch_paths(release)), separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()
