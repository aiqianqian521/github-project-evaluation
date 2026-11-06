"""Fail-closed audit of a model's first-pass repository verdict."""
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


REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
RELEASE_CLAIM = re.compile(
    r"合格部署|批准部署|可以部署|(?<!不)可部署(?!性)|approved for deployment|deployment ready|production ready",
    re.IGNORECASE,
)
MAX_BYTES = 256_000


def read_input(file):
    source = Path(file)
    try:
        with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("review input must be a regular file")
            data = stream.read(MAX_BYTES + 1)
    except OSError as error:
        raise ValueError("review input is missing or unsafe") from error
    if len(data) > MAX_BYTES:
        raise ValueError("review input exceeds 256 KB")
    return data, hashlib.sha256(data).hexdigest()


def audit(first_pass_file, review_file, execution_file=None):
    first_pass_bytes, first_pass_sha256 = read_input(first_pass_file)
    review_bytes, review_sha256 = read_input(review_file)
    first_pass = json.loads(first_pass_bytes)
    review = review_bytes.decode("utf-8")
    if not isinstance(first_pass, dict) or first_pass.get("schema") != "project-first-pass.v1":
        raise ValueError("invalid first-pass contract")
    repository = first_pass.get("expected_repository")
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository identity")

    reasons = []
    if first_pass.get("deployment_test_gate") != "BLOCK":
        reasons.append("first_pass_gate_changed_or_unrecognized")
    else:
        reasons.append("first_pass_never_authorizes_deployment")
    if first_pass.get("goal_fit") != "NOT_REVIEWED":
        reasons.append("first_pass_goal_fit_changed_or_unrecognized")
    else:
        reasons.append("human_goal_fit_not_reviewed")
    if first_pass.get("upstream_commit_verified") is not True:
        reasons.append("upstream_commit_not_independently_verified")
    if first_pass.get("license_approved") is not True:
        reasons.append("license_not_approved")

    execution_sha256 = None
    execution_verdict = "NOT_PROVIDED"
    if execution_file is None:
        reasons.append("independent_execution_not_provided")
    else:
        execution_bytes, execution_sha256 = read_input(execution_file)
        execution = json.loads(execution_bytes)
        if not isinstance(execution, dict) or execution.get("schema") != "project-tests.execution.v1":
            raise ValueError("invalid execution contract")
        if not isinstance(execution.get("gate"), dict) or not isinstance(execution.get("review"), dict):
            raise ValueError("invalid execution gate or review")
        claimed_verdict = execution.get("verdict", "MISSING")
        execution_verdict = "UNVERIFIED_CLAIM" if claimed_verdict == "PASS" else claimed_verdict
        reasons.append("legacy_execution_contract_not_verified")
        if claimed_verdict != "PASS" or execution.get("gate", {}).get("exit_code") != 0:
            reasons.append("independent_execution_not_passed")
        if execution.get("repository") != repository or execution.get("commit") != first_pass.get("local_commit"):
            reasons.append("execution_not_bound_to_frozen_repository")
        if execution.get("review", {}).get("status") != "APPROVED":
            reasons.append("independent_review_not_approved")

    possible_release_claim = bool(RELEASE_CLAIM.search(review))
    return {
        "schema": "project-first-pass.review-audit.v1",
        "repository": repository,
        "first_pass_sha256": first_pass_sha256,
        "review_text_sha256": review_sha256,
        "execution_sha256": execution_sha256,
        "execution_verdict": execution_verdict,
        "possible_release_claim": possible_release_claim,
        "claim_requires_correction": possible_release_claim,
        "candidate_approval": "NOT_REVIEWED",
        "deployment_test_gate": "BLOCK",
        "decision": "BLOCK",
        "blocking_reasons": reasons,
        "next_gate": "independent human review and separately authorized downstream tests",
    }


def main():
    parser = argparse.ArgumentParser(description="Audit model prose; never grant execution or deployment")
    parser.add_argument("--first-pass", type=Path, required=True)
    parser.add_argument("--review-text", type=Path, required=True)
    parser.add_argument("--execution", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or args.output_dir.is_symlink():
        parser.error("output directory must be new")
    if not args.output_dir.parent.is_dir():
        parser.error("output parent must exist")
    output_parent = args.output_dir.parent.resolve()
    if any((parent / ".git").exists() for parent in (output_parent, *output_parent.parents)):
        parser.error("output directory must not be inside a Git checkout")
    try:
        result = audit(args.first_pass, args.review_text, args.execution)
        args.output_dir.mkdir(exist_ok=False)
        (args.output_dir / "REVIEW-AUDIT.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(f"review audit blocked: {type(error).__name__}")
    print(json.dumps({"decision": result["decision"],
                      "possible_release_claim": result["possible_release_claim"]}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
