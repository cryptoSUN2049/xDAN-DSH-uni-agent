"""Encrypt this recovery's private material before writing to the network volume."""

import argparse
import hashlib
import io
import json
import os
import stat
import tarfile
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PRIVATE = Path("/root/mimo-private")
DESTINATION = Path("/workspace/mimo-dsh-rl-20260928/recovery-encrypted-r21")
POD = "vo6u0t8x398bnm"
AAD = b"mimo.private-recovery-backup.v1:vo6u0t8x398bnm"


def backup():
    if os.environ.get("RUNPOD_POD_ID") != POD:
        raise ValueError("Refuse another Pod")
    info = PRIVATE.stat()
    if PRIVATE.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private root must be local, owned and protected")
    key_path = PRIVATE / "backup-key.bin"
    fd = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        key_info = os.fstat(source.fileno())
        if not stat.S_ISREG(key_info.st_mode) or key_info.st_uid != os.getuid() or key_info.st_mode & 0o077:
            raise ValueError("Backup key permissions differ")
        key = source.read(33)
    if len(key) != 32:
        raise ValueError("Expected a dedicated 256-bit backup key")
    buffer = io.BytesIO()
    count = 0
    # Traverse owned files, never deserialize or print credential JSON contents.
    # Skip sockets, binaries, the encryption key, and large live logs/journals.
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(PRIVATE.rglob("*")):
            relative = path.relative_to(PRIVATE)
            if relative.parts[0] == "bin" or "token-journal" in relative.parts or path == key_path:
                continue
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                continue
            info = path.stat()
            if (info.st_dev, info.st_ino) == (key_info.st_dev, key_info.st_ino):
                continue
            archive.add(path, arcname="private/" + str(relative), recursive=False)
            count += 1
        netrc = Path("/root/.netrc")
        if netrc.is_file() and not netrc.is_symlink():
            archive.add(netrc, arcname="root-netrc", recursive=False)
            count += 1
    raw = buffer.getvalue()
    nonce = os.urandom(12)
    sealed = nonce + AESGCM(key).encrypt(nonce, raw, AAD)
    # Verify authentication and the exact plaintext before publishing ciphertext.
    if AESGCM(key).decrypt(sealed[:12], sealed[12:], AAD) != raw:
        raise ValueError("Encryption roundtrip failed")
    DESTINATION.mkdir(exist_ok=True)
    output = DESTINATION / f"private-{time.time_ns()}.aesgcm"
    sidecar = output.with_suffix(".public.json")
    if sidecar.exists():
        raise FileExistsError("Refuse an existing backup receipt")
    with output.open("xb") as target:
        target.write(sealed)
        target.flush()
        os.fsync(target.fileno())
    report = {
        "schema": "mimo.encrypted-recovery-backup.v1",
        "at": time.time(),
        "pod_id": POD,
        "path": str(output),
        "sha256": hashlib.sha256(sealed).hexdigest(),
        "bytes": len(sealed),
        "files": count,
        "encryption": "AES-256-GCM",
        "authentication_roundtrip_passed": True,
        "key_in_archive": False,
        "plaintext_on_network_volume": False,
    }
    with sidecar.open("x") as target:
        target.write(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval-seconds", type=int, default=0)
    args = parser.parse_args()
    if args.interval_seconds and args.interval_seconds < 60:
        parser.error("Backup interval must be at least sixty seconds")
    while True:
        print(json.dumps(backup()), flush=True)
        if not args.interval_seconds:
            return
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
