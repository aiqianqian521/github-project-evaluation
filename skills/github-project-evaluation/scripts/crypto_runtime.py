"""Resolve an explicitly selected or PATH OpenSSL; do not mutate system binaries."""

import os
from pathlib import Path
import shutil
import subprocess


def openssl_binary():
    configured = os.environ.get("OPENSSL_BINARY")
    if configured and not Path(configured).is_absolute():
        raise ValueError("OPENSSL_BINARY must be an absolute trusted executable path")
    selected = configured or shutil.which("openssl")
    if not selected or not Path(selected).is_file() or not os.access(selected, os.X_OK):
        raise ValueError("OpenSSL unavailable; select a trusted OpenSSL 3 with OPENSSL_BINARY")
    return str(Path(selected).resolve())


def openssl_capability():
    try:
        binary = openssl_binary()
        result = subprocess.run([binary, "list", "-signature-algorithms"],
                                capture_output=True, timeout=5, check=False)
        version = subprocess.run([binary, "version"], capture_output=True, timeout=5, check=False)
        ok = result.returncode == 0 and b"ED25519" in result.stdout.upper()
        return {"status": "READY" if ok else "BLOCK", "path": binary,
                "version": version.stdout.decode(errors="replace").strip(),
                "reason": None if ok else "ed25519_unavailable"}
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {"status": "BLOCK", "reason": type(error).__name__}
