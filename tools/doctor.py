"""Read-only capability checks. READY means available, never independently audited."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/github-project-evaluation/scripts"))
from crypto_runtime import openssl_capability


def inspect():
    engine = os.environ.get("LOOP_TEST_ENGINE_ROOT")
    contract = Path(engine) / "adapters/task_runner.py" if engine else None
    loop = {"status": "AVAILABLE_NOT_INTEGRATION_VERIFIED" if contract and contract.is_file() else "BLOCK",
            "reason": "external_engine_required", "path": engine}
    if contract and contract.is_file():
        loop["contract_sha256"] = hashlib.sha256(contract.read_bytes()).hexdigest()
        pin = os.environ.get("LOOP_CONTRACT_SHA256")
        loop["pin_status"] = "MATCH" if pin == loop["contract_sha256"] else "MISSING_OR_MISMATCH"
        if loop["pin_status"] != "MATCH":
            loop["status"] = "BLOCK"
    selected = os.environ.get("BWRAP_BINARY")
    bwrap = {"status": "BLOCK", "reason": "Linux and explicit trusted BWRAP_BINARY required"}
    if sys.platform == "linux" and selected and Path(selected).is_absolute() and Path(selected).is_file():
        try:
            result = subprocess.run([selected, "--version"], capture_output=True, timeout=5)
            bwrap = {"status": "AVAILABLE_NOT_SECURITY_AUDITED" if result.returncode == 0 else "BLOCK",
                     "path": selected, "version": result.stdout.decode(errors="replace").strip()}
        except (OSError, subprocess.TimeoutExpired) as error:
            bwrap["reason"] = type(error).__name__
    python_ok = sys.version_info >= (3, 11) and sys.platform in {"darwin", "linux", "win32"}
    git_ok = shutil.which("git") is not None
    crypto = openssl_capability()
    windows_compat = {"status": "NOT_APPLICABLE"}
    if sys.platform == "win32":
        try:
            import _wincompat
            windows_compat = {"status": "EMULATED_NOT_AUDITED",
                              "preserved": len(_wincompat.REPORT["PRESERVED"]),
                              "equivalent": len(_wincompat.REPORT["EQUIVALENT"]),
                              "not_enforced": _wincompat.REPORT["NOT_ENFORCED"],
                              "remap": _wincompat.REPORT["REMAP"]}
        except ImportError as error:
            windows_compat = {"status": "MISSING", "reason": type(error).__name__}
    return {"schema": "handoff.doctor.v1", "python": sys.version, "platform": platform.platform(),
            "core": {"status": "READY" if python_ok and git_ok else "BLOCK", "git": shutil.which("git")},
            "crypto": crypto, "loop": loop, "linux_isolation": bwrap,
            "windows_compat": windows_compat,
            "portable_unit_ready": python_ok and git_ok and crypto["status"] == "READY",
            "full_integration_ready": (python_ok and git_ok and crypto["status"] == "READY"
                                       and loop["status"] != "BLOCK" and bwrap["status"] != "BLOCK"),
            "project_acceptance": "NOT_GRANTED"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("core", "portable", "full"), default="portable")
    arguments = parser.parse_args()
    report = inspect()
    print(json.dumps(report, indent=2))
    ready = {"core": report["core"]["status"] == "READY", "portable": report["portable_unit_ready"],
             "full": report["full_integration_ready"]}[arguments.profile]
    raise SystemExit(0 if ready else 2)
