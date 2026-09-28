"""MiMo Code verifier, runnable with Python's standard library in a trusted environment.

The operator freezes base_ref before the agent starts. Only hidden-test paths are
reset; the candidate's source changes remain. Transport, patch and timeout errors
produce no reward, while a completed test command's nonzero exit earns zero.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath


class VerificationError(RuntimeError):
    """A verifier/testbed failure that must not become a model reward."""


def _run(command, cwd, timeout=60):
    """Bound captured output and kill the whole process group on a timeout."""
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
            )
        except OSError as exc:
            raise VerificationError(f"command_start_failed: {exc}") from exc
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise VerificationError("verifier_timeout") from exc
        output.seek(0, os.SEEK_END)
        output.seek(max(0, output.tell() - 65536))
        return process.returncode, output.read().decode("utf-8", errors="replace")


def _git(cwd, *args):
    return _run(["git", "-c", f"safe.directory={cwd}", "-c", "core.hooksPath=/dev/null", "-C", str(cwd), *args], cwd)


def _checked_git(cwd, *args):
    code, output = _git(cwd, *args)
    if code != 0:
        raise VerificationError(f"git_failed: {output[-1000:]}")
    return output.strip()


def freeze_baseline(cwd: Path | str) -> str:
    """Capture the real image HEAD before rollout and reject reachable future fixes."""
    cwd = Path(cwd).resolve(strict=True)
    if _git(cwd, "rev-parse", "--git-dir")[0] != 0:
        _checked_git(cwd, "init", "-q")
        _checked_git(cwd, "add", "-A")
        _checked_git(
            cwd,
            "-c",
            "user.name=MiMo verifier",
            "-c",
            "user.email=mimo@example.invalid",
            "commit",
            "-q",
            "-m",
            "baseline",
            "--allow-empty",
        )
    ref = _checked_git(cwd, "rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}", ref) is None:
        raise VerificationError("invalid_base_ref")
    if _checked_git(cwd, "rev-list", "--all", "--not", ref):
        raise VerificationError("image_history_not_truncated")
    return ref


def _safe_patch_path(raw: str, *, prefix: bool = True) -> str | None:
    """Decode Git's quoted UTF-8 octal paths before checking traversal boundaries."""
    if raw.startswith('"'):
        encoded = raw
        try:
            raw = ast.literal_eval(encoded)
            if re.search(r"\\[0-7]{1,3}", encoded):
                raw = raw.encode("latin-1").decode("utf-8")
        except (ValueError, SyntaxError, UnicodeError) as exc:
            raise VerificationError("invalid_patch_path") from exc
    if raw == "/dev/null":
        return None
    if not isinstance(raw, str):
        raise VerificationError("invalid_patch_path")
    if prefix:
        # git apply's default -p1 strips one component, not specifically a/ or
        # b/. One real MiMo row uses ab/ in its source header.
        leading, separator, relative = raw.partition("/")
        if not separator or not leading or leading in {".", ".."}:
            raise VerificationError("invalid_patch_path")
    else:
        relative = raw
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or path.as_posix() != relative
        or any(part in {"..", ".git"} for part in path.parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in relative)
    ):
        raise VerificationError("invalid_patch_path")
    return relative


def _diff_header_paths(header: str) -> tuple[str, str]:
    """Get both paths, including binary/mode-only changes with no ---/+++ headers."""
    if header.startswith('"'):
        match = re.fullmatch(r'("(?:\\.|[^"\\])*") (.+)', header)
        if match is None:
            raise VerificationError("invalid_patch_path_header")
        return match[1], match[2]
    if ' "' in header:
        old, _, new = header.partition(' "')
        return old, '"' + new
    candidates = [
        (header[: match.start()], header[match.start() + 1 :]) for match in re.finditer(r' (?=[^ /\t"]+/)', header)
    ]
    if len(candidates) == 1:
        return candidates[0]
    # Git leaves ordinary spaces unquoted. Same-path changes can still be
    # disambiguated exactly; ambiguous rename headers fail closed.
    identical = [(old, new) for old, new in candidates if old.partition("/")[2] == new.partition("/")[2]]
    if len(identical) == 1:
        return identical[0]
    raise VerificationError("ambiguous_patch_path_header")


def patch_paths(test_patch: str) -> list[str]:
    """Collect every touched path without applying or rewriting the original patch.

    Hunk counters distinguish file headers from test contents. Git headers cover
    binary, rename and mode-only changes; traditional unified diffs need no Git
    prefix. Actual applicability remains the responsibility of original git apply.
    """
    paths = set()
    old_remaining = new_remaining = 0
    for line in test_patch.splitlines():
        if line.startswith("diff --git "):
            old_remaining = new_remaining = 0
            for raw in _diff_header_paths(line[len("diff --git ") :]):
                if (path := _safe_patch_path(raw)) is not None:
                    paths.add(path)
            continue
        if old_remaining or new_remaining:
            if line.startswith((" ", "-")):
                old_remaining = max(0, old_remaining - 1)
            if line.startswith((" ", "+")):
                new_remaining = max(0, new_remaining - 1)
            continue
        hunk = re.match(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
        if hunk is not None:
            old_remaining = int(hunk[1]) if hunk[1] is not None else 1
            new_remaining = int(hunk[2]) if hunk[2] is not None else 1
            continue
        if line.startswith(("--- ", "+++ ")):
            if (path := _safe_patch_path(line[4:].split("\t", 1)[0])) is not None:
                paths.add(path)
        for prefix in ("rename from ", "rename to ", "copy from ", "copy to "):
            if line.startswith(prefix):
                if (path := _safe_patch_path(line[len(prefix) :], prefix=False)) is not None:
                    paths.add(path)
    if not paths:
        raise VerificationError("missing_patch_paths")
    return sorted(paths)


def _reset_tests(cwd: Path, base_ref: str, paths: list[str]) -> None:
    for relative in paths:
        destination = cwd / relative
        if any(parent.is_symlink() for parent in destination.parents if parent != cwd and cwd in parent.parents):
            raise VerificationError("reset_tests_failed: symlink parent")
        exists = _git(cwd, "cat-file", "-e", f"{base_ref}:{relative}")[0] == 0
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)
        if exists:
            code, output = _git(cwd, "checkout", base_ref, "--", relative)
            if code != 0:
                raise VerificationError(f"reset_tests_failed: {output[-1000:]}")
        else:
            code, output = _git(cwd, "rm", "--cached", "--ignore-unmatch", "--", relative)
            if code != 0:
                raise VerificationError(f"reset_tests_failed: {output[-1000:]}")


def verify(*, cwd: Path | str, base_ref: str, test_patch: str, test_command: str, timeout: int | float) -> dict:
    """Reset touched tests to frozen base, apply full patch, execute original command."""
    cwd = Path(cwd).resolve(strict=True)
    if not isinstance(base_ref, str) or re.fullmatch(r"[0-9a-f]{40}", base_ref) is None:
        raise VerificationError("invalid_base_ref")
    if _git(cwd, "cat-file", "-e", f"{base_ref}^{{commit}}")[0] != 0:
        raise VerificationError("missing_base_ref")
    if (
        not isinstance(test_command, str)
        or not test_command.strip()
        or not isinstance(timeout, int | float)
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        raise VerificationError("invalid_verifier_config")
    paths = patch_paths(test_patch)
    try:
        _reset_tests(cwd, base_ref, paths)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".patch") as patch:
            patch.write(test_patch)
            patch.flush()
            code, output = _git(cwd, "apply", "--verbose", patch.name)
        if code != 0:
            raise VerificationError(f"apply_test_patch_failed: {output[-1000:]}")
        started = time.monotonic()
        code, output = _run(["bash", "-lc", test_command], cwd, timeout=timeout)
        return {
            "status": "graded",
            "reward": float(code == 0),
            "resolved": code == 0,
            "verifier_returncode": code,
            "test_duration": time.monotonic() - started,
            "test_output": output,
        }
    finally:
        _reset_tests(cwd, base_ref, paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--base-ref-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    reward_file = args.output_dir / "reward.json"
    reward_file.unlink(missing_ok=True)
    receipt = {"schema": "dsh.mimo-verifier-receipt.v1", "status": "infra_error"}
    try:
        config = json.loads(args.config.read_text())
        state = json.loads(args.base_ref_file.read_text())
        if (
            state["cwd"] != config["cwd"]
            or re.fullmatch(r"sha256:[0-9a-f]{64}", state["snapshot_sha256"]) is None
            or not isinstance(state["gateway_session_id"], str)
            or not state["gateway_session_id"]
        ):
            raise VerificationError("invalid_operator_state")
        receipt.update({key: state[key] for key in ("base_ref", "snapshot_sha256", "gateway_session_id")})
        patch = args.patch.read_bytes()
        patch_hash = "sha256:" + hashlib.sha256(patch).hexdigest()
        if patch_hash != config["test_patch_sha256"]:
            raise VerificationError("test_patch_digest_mismatch")
        result = verify(
            cwd=config["cwd"],
            base_ref=state["base_ref"],
            test_patch=patch.decode("utf-8"),
            test_command=config["test_command"],
            timeout=config["verifier_timeout_sec"],
        )
        receipt.update(result, test_patch_sha256=patch_hash)
        (args.output_dir / "test-output.txt").write_text(receipt.pop("test_output"))
        reward_file.write_text(json.dumps({"reward": result["reward"]}) + "\n")
        code = 0
    except (VerificationError, OSError, KeyError, TypeError, ValueError) as exc:
        receipt["error"] = str(exc)[-2000:]
        code = 2
    (args.output_dir / "mimo-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
