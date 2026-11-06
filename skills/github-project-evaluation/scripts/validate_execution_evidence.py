"""Validate bounded local artifact integrity, never project acceptance."""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40,64}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
CASE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
MAX_ARTIFACT = 2_000_000


def local_file(root, name, limit=MAX_ARTIFACT):
    if not isinstance(name, str) or not name or len(name) > 240:
        raise ValueError("invalid artifact path")
    relative = Path(name)
    if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("invalid artifact path")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ValueError("artifact parent is not a plain directory")
    file = current / relative.name
    descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > limit:
            raise ValueError("artifact is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError("artifact exceeds limit")
        return content
    finally:
        os.close(descriptor)


def check_evidence(manifest, root, manifest_sha256=None):
    reasons = []
    repository = manifest.get("repository") if isinstance(manifest, dict) else None
    commit = manifest.get("commit") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict) or manifest.get("schema") != "project-tests.evidence.v2":
        raise ValueError("unexpected evidence schema")
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise ValueError("invalid commit")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        raise ValueError("expected 1-20 cases")
    seen = set()
    paths = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not CASE.fullmatch(case["case_id"]):
            raise ValueError("invalid case id")
        if case["case_id"] in seen:
            raise ValueError("duplicate case")
        seen.add(case["case_id"])
        artifacts = case.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != {"stdout", "stderr", "exit"}:
            raise ValueError("missing case artifacts")
        if type(case.get("expected_exit_code")) is not int or not 0 <= case["expected_exit_code"] <= 255:
            raise ValueError("invalid expected exit code")
        for role, entry in artifacts.items():
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"} or not isinstance(entry["sha256"], str) or not SHA.fullmatch(entry["sha256"]):
                raise ValueError("invalid artifact declaration")
            if entry["path"] in paths:
                raise ValueError("artifact reused across cases")
            paths.add(entry["path"])
            try:
                content = local_file(root, entry["path"])
            except (OSError, ValueError) as error:
                reasons.append(f"{case['case_id']}/{role}: {type(error).__name__}")
                continue
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                reasons.append(f"{case['case_id']}/{role}: digest_mismatch")
            if role == "exit":
                try:
                    observed = int(content.decode("ascii").strip())
                except (UnicodeError, ValueError):
                    reasons.append(f"{case['case_id']}/exit: invalid_exit_code")
                else:
                    if observed != case["expected_exit_code"]:
                        reasons.append(f"{case['case_id']}/exit: unexpected_exit_code")
    return {"schema": "project-tests.evidence-check.v2", "repository": repository, "commit": commit,
            "manifest_sha256": manifest_sha256,
            "local_integrity": "INTACT_LOCAL" if not reasons else "BLOCK",
            "evidence_trust": "LOCAL_UNAUTHENTICATED", "case_ids": sorted(seen),
            "candidate_acceptance": "NOT_REVIEWED", "decision": "BLOCK", "reasons": reasons}


def main():
    parser = argparse.ArgumentParser(description="Check local logs; never grant project acceptance")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or args.output_dir.is_symlink() or not args.output_dir.parent.is_dir():
        parser.error("output directory must be new")
    if any((parent / ".git").exists() for parent in (args.output_dir.parent.resolve(), *args.output_dir.parent.resolve().parents)):
        parser.error("output directory must be outside a checkout")
    try:
        if args.artifacts_dir.is_symlink() or not args.artifacts_dir.is_dir():
            raise ValueError("artifact directory must be a plain directory")
        data = local_file(args.manifest.parent, args.manifest.name, 64_000)
        result = check_evidence(json.loads(data), args.artifacts_dir.resolve(), hashlib.sha256(data).hexdigest())
    except (OSError, ValueError, TypeError) as error:
        parser.error(f"invalid evidence: {type(error).__name__}")
    args.output_dir.mkdir()
    (args.output_dir / "EVIDENCE-CHECK.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"local_integrity": result["local_integrity"], "decision": "BLOCK"}))
    return 0 if result["local_integrity"] == "INTACT_LOCAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
