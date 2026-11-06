"""One-command technical handoff acceptance; never grants project deployment."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/github-project-evaluation/scripts"))
if sys.platform == "win32":
    import _wincompat  # noqa: F401  (POSIX-equivalents for chmod/stat/subprocess on Windows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error("output must be fresh and outside release tree")
    output.mkdir(parents=True)
    timeout = int(os.environ.get("HANDOFF_COMMAND_TIMEOUT", "240"))
    commands = [
        ("integrity", "verify_release.py", [], 0),
        ("portable-tests", "run_tests.py", ["--profile", "portable", "--output", str(output / "tests")], 0),
        ("offline", "offline_acceptance.py", ["--output", str(output / "offline")], 0),
    ]
    results = []
    for name, script, flags, expected in commands:
        try:
            result = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / script), *flags],
                                    capture_output=True, timeout=timeout,
                                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            # a slow host must still produce an honest FAIL record, not a traceback
            stdout = error.stdout or b""
            stderr = (error.stderr or b"") + f"\n[handoff] timed out after {timeout}s\n".encode()
            code = None
        (output / (name + ".stdout")).write_bytes(stdout)
        (output / (name + ".stderr")).write_bytes(stderr)
        results.append({"check": name, "exit": code,
                        "status": "PASS" if code == expected else "FAIL"})
    full = subprocess.run([sys.executable, "-B", str(ROOT / "tools/doctor.py"), "--profile", "full"],
                          capture_output=True, timeout=timeout)
    (output / "full-profile-doctor.json").write_bytes(full.stdout)
    ready = all(item["status"] == "PASS" for item in results)
    report = {"schema": "handoff.acceptance.v1", "technical_handoff": "READY" if ready else "BLOCK",
              "checks": results, "full_profile_environment": "AVAILABLE_NOT_E2E_VERIFIED" if full.returncode == 0 else "BLOCK",
              "external_scheduler_e2e": "NOT_RUN", "third_party_business_tests": "NOT_RUN",
              "publisher_signature": "NOT_PROVIDED", "human_signoff": "PENDING",
              "permission_to_execute_third_party_code": "NOT_GRANTED", "production_deployment": "BLOCK"}
    (output / "HANDOFF-ACCEPTANCE.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
