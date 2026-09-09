"""Verify or explicitly apply the reviewed overlay to a dedicated fixed VERL checkout.

Never invoke --apply on a checkout used by a running process. No reset/stash,
network, dependency resolution, or implicit source repair is performed.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

BASE = "fefb080262e1c015a0ea05f958822a6a512dc795"
TARGET = "verl/workers/rollout/vllm_rollout/vllm_async_server.py"
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "deployment/versions/verl-runtime-patches.json"


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read(path):
    path = Path(path)
    _require(not path.is_symlink() and path.is_file(), f"Expected regular file: {path.name}")
    return path.read_bytes()


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    _require(result.returncode == 0, f"Git verification failed: {args[0]}")
    return result.stdout


def _spec():
    raw = _read(MANIFEST)
    spec = json.loads(raw)
    deployment = json.loads(_read(ROOT / "deployment/versions/g1-deployment-lock.json"))
    declared = deployment["integration"]["verl_source_overlay"]
    _require(
        declared["manifest"] == "deployment/versions/verl-runtime-patches.json"
        and declared["manifest_sha256"] == _sha(raw)
        and declared["base_revision"] == BASE,
        "Deployment lock does not authorize this source overlay",
    )
    _require(
        spec["schema"] == "dsh.verl-source-overlay.v1"
        and spec["base_revision"] == BASE
        and spec["overlay_id"] == "preserve-finish-reason-v1"
        and set(spec["files"]) == {TARGET},
        "Unexpected overlay contract",
    )
    patch = ROOT / spec["patch_path"]
    _require(
        patch.resolve().is_relative_to((ROOT / "deployment/patches/verl").resolve()),
        "Patch path escapes reviewed directory",
    )
    _require(_sha(_read(patch)) == spec["patch_sha256"], "Patch hash mismatch")
    return spec, raw, patch


def verify_verl_source(repo, require_patched=True):
    """Return a portable effective source identity, rejecting every unauthorized dirty file."""
    repo = Path(repo)
    spec, manifest_raw, _ = _spec()
    _require(_git(repo, "rev-parse", "HEAD").decode().strip() == BASE, "VERL base revision mismatch")
    _require(
        _sha(_git(repo, "show", f"{BASE}:{TARGET}")) == spec["files"][TARGET]["before_sha256"],
        "Pinned original file hash mismatch",
    )
    _require(
        _sha(_read(repo / "uv.lock")) == spec["uv_lock_sha256"] == _sha(_git(repo, "show", f"{BASE}:uv.lock")),
        "Frozen uv.lock changed",
    )
    target_sha = _sha(_read(repo / TARGET))
    expected = spec["files"][TARGET]
    if target_sha == expected["before_sha256"]:
        state, allowed = "baseline", b""
    elif target_sha == expected["after_sha256"]:
        state, allowed = "patched", (" M " + TARGET + "\0").encode()
    else:
        raise ValueError("Unexpected target source bytes; no automatic repair")
    status = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    _require(status == allowed, "Unexpected staged, untracked, or other dirty source files")
    _require(not require_patched or state == "patched", "Reviewed VERL patch is not applied")
    return dict(
        schema=spec["schema"],
        base_revision=BASE,
        overlay_id=spec["overlay_id"],
        state=state,
        patch_sha256=spec["patch_sha256"],
        manifest_sha256=_sha(manifest_raw),
        files={TARGET: target_sha},
    )


def apply_verl_source(repo):
    """Explicit only: apply to baseline or verify an exact prior application; never repair unknown state."""
    identity = verify_verl_source(repo, require_patched=False)
    if identity["state"] == "patched":
        return identity
    _, _, patch = _spec()
    _git(repo, "apply", "--check", "--whitespace=error-all", str(patch))
    _git(repo, "apply", "--whitespace=error-all", str(patch))
    return verify_verl_source(repo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true", help="Explicitly apply only on a new, inactive dedicated checkout"
    )
    args = parser.parse_args()
    result = apply_verl_source(args.repo) if args.apply else verify_verl_source(args.repo)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
