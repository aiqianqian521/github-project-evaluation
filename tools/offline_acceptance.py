"""Reproduce frozen public evidence without network or third-party code execution."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/github-project-evaluation/scripts"))
if sys.platform == "win32":
    import _wincompat  # noqa: F401  (POSIX-equivalents for chmod/stat/subprocess on Windows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error("output must be fresh and outside release")
    output.mkdir(parents=True)
    cache = output / "cache"
    shutil.copytree(ROOT / "evidence/search-cache", cache)
    cache.chmod(0o700)
    scripts = ROOT / "skills/github-project-evaluation/scripts"
    commands = [
        ("github", [sys.executable, "-B", str(scripts / "discover.py"), "markupsafe", "--source", "github",
                    "--max-pages", "2", "--verify-top", "0", "--offline", "--cache-dir", str(cache),
                    "--output-dir", str(output / "github")], 2),
        ("reporank", [sys.executable, "-B", str(scripts / "discover.py"), "markupsafe", "--source", "reporank",
                      "--max-pages", "2", "--verify-top", "0", "--offline", "--cache-dir", str(cache),
                      "--output-dir", str(output / "reporank")], 0),
        ("clone", ["git", "-c", "core.hooksPath=/dev/null", "clone", "--quiet",
                   str(ROOT / "evidence/repository/github-markupsafe-4e111271.bundle"), str(output / "checkout")], 0),
        ("first-pass", [sys.executable, "-B", str(scripts / "evaluate_first_pass.py"), str(output / "checkout"),
                        "--expected-repo", "pallets/markupsafe", "--output-dir", str(output / "first-pass")], 0),
        ("design", [sys.executable, "-B", str(ROOT / "skills/github-project-evaluation/scripts/validate_design.py"),
                    str(ROOT / "examples/markupsafe")], 0),
    ]
    records = []
    environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                   "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    for name, argv, expected in commands:
        result = subprocess.run(argv, capture_output=True, timeout=60, env=environment)
        (output / (name + ".stdout")).write_bytes(result.stdout)
        (output / (name + ".stderr")).write_bytes(result.stderr)
        records.append({"name": name, "exit": result.returncode, "expected_exit": expected})
        if result.returncode != expected:
            report = {"status": "FAIL", "commands": records}
            (output / "summary.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
            return 1
    github = json.loads((output / "github/candidates.json").read_text())
    reporank = json.loads((output / "reporank/candidates.json").read_text())
    first = json.loads((output / "first-pass/FIRST-PASS.json").read_text())
    head = subprocess.check_output(["git", "-C", str(output / "checkout"), "rev-parse", "HEAD"], env=environment).decode().strip()
    tracked = subprocess.check_output(["git", "-C", str(output / "checkout"), "ls-files", "-z"], env=environment)
    checks = {"github_partial_30": github["status"] == "PARTIAL" and github["rows_seen"] == 30,
              "reporank_complete_0": reporank["status"] == "COMPLETE" and reporank["rows_seen"] == 0,
              "head_pinned": head == "4e111271b1494995708a9e878a10829b5e10c7ba",
              "tracked_47": len(tracked.split(b"\0")) - 1 == 47,
              "offline_identity_block": first["identity_gate"] == "BLOCK",
              "deployment_block": first["deployment_test_gate"] == "BLOCK",
              "offline_score_62": first["evidence_score"] == 62}
    source_map = json.loads((ROOT / "examples/markupsafe/SOURCE-MAP.json").read_text())
    checks["source_map_matches"] = all(
        hashlib.sha256((output / "checkout" / name).read_bytes()).hexdigest() == digest
        for name, digest in source_map["files"].items())
    # Negative control: tamper the GitHub cached bytes but retain the old digest.
    for meta in cache.glob("*.json"):
        info = json.loads(meta.read_text())
        data = meta.with_suffix(".data")
        if b'"total_count"' in data.read_bytes():
            data.write_bytes(data.read_bytes() + b"tampered")
    result = subprocess.run(commands[0][1][:-1] + [str(output / "tampered")], capture_output=True,
                            timeout=60, env=environment)
    (output / "tampered.stdout").write_bytes(result.stdout)
    (output / "tampered.stderr").write_bytes(result.stderr)
    tampered = json.loads((output / "tampered/candidates.json").read_text())
    checks["tampered_cache_partial_zero"] = result.returncode == 2 and tampered["rows_seen"] == 0 and tampered["status"] == "PARTIAL"
    report = {"schema": "handoff.offline-acceptance.v1", "status": "PASS" if all(checks.values()) else "FAIL",
              "checks": checks, "commands": records, "third_party_code_executed": False,
              "upstream_identity": "NOT_REVERIFIED", "project_acceptance": "NOT_GRANTED"}
    (output / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
