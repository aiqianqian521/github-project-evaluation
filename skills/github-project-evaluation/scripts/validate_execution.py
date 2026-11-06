#!/usr/bin/env python3
import hashlib
import json
import re
import sys
from pathlib import Path


HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
CASE_ID = re.compile(r"[FP]-[A-Za-z0-9-]+\Z")


def evidence_issues(root: Path, evidence: object, label: str) -> list[str]:
    if not isinstance(evidence, dict):
        return [f"{label}: evidence object missing"]
    name = evidence.get("path")
    digest = evidence.get("sha256")
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        return [f"{label}: evidence path must be relative"]
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return [f"{label}: evidence missing or outside run directory"]
    if not isinstance(digest, str) or not HEX_DIGEST.fullmatch(digest):
        return [f"{label}: evidence digest missing"]
    try:
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return [f"{label}: evidence unreadable"]
    if actual_digest != digest:
        return [f"{label}: evidence digest mismatch"]
    return []


def validate(directory: Path) -> list[str]:
    manifest = directory / "TEST-EXECUTION.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"execution manifest unreadable: {type(exc).__name__}"]
    if not isinstance(data, dict) or data.get("schema") != "project-tests.execution.v1":
        return ["execution schema mismatch"]
    issues = []
    source = data.get("source_sha256")
    if not isinstance(source, str) or not HEX_DIGEST.fullmatch(source):
        issues.append("source identity digest missing")
    if not isinstance(data.get("run_id"), str) or not data["run_id"].strip():
        issues.append("run_id missing")
    scope = data.get("scope")
    if not isinstance(scope, dict) or not scope.get("environment") or not scope.get("authorization"):
        issues.append("execution scope or authorization missing")
    gate = data.get("gate")
    if not isinstance(gate, dict) or type(gate.get("exit_code")) is not int:
        issues.append("gate exit code missing")
        gate_failure = True
    else:
        gate_failure = gate["exit_code"] != 0
        issues.extend(evidence_issues(directory, gate.get("evidence"), "gate"))
        exit_evidence = gate.get("exit_evidence")
        exit_issues = evidence_issues(directory, exit_evidence, "gate exit")
        issues.extend(exit_issues)
        if not exit_issues:
            try:
                exit_text = (directory / exit_evidence["path"]).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                issues.append("gate exit evidence unreadable")
            else:
                if exit_text != str(gate["exit_code"]):
                    issues.append("gate exit evidence contradicts claimed code")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        issues.append("execution case ledger missing")
        cases = []
    seen = set()
    failed = gate_failure
    blocked = False
    passed_count = 0
    for case in cases:
        if not isinstance(case, dict):
            issues.append("invalid case object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id) or case_id in seen:
            issues.append(f"invalid or duplicate case ID: {case_id}")
            continue
        seen.add(case_id)
        status = case.get("status")
        if status not in {"PASS", "FAIL", "BLOCK", "SKIP", "N/A"}:
            issues.append(f"{case_id}: invalid case status")
            continue
        if status in {"PASS", "FAIL"}:
            issues.extend(evidence_issues(directory, case.get("evidence"), case_id))
            oracle = case.get("oracle")
            if not isinstance(oracle, dict) or oracle.get("kind") != "independent" or not oracle.get("reference"):
                issues.append(f"{case_id}: independent oracle reference missing")
            if not case.get("expected") or case.get("actual") in (None, ""):
                issues.append(f"{case_id}: expected or actual missing")
            failed |= status == "FAIL"
            passed_count += status == "PASS"
        else:
            if not isinstance(case.get("reason"), str) or not case["reason"].strip():
                issues.append(f"{case_id}: blocked/skipped status needs reason")
            blocked |= status in {"BLOCK", "SKIP"}
    pressure = data.get("pressure")
    if not isinstance(pressure, dict) or pressure.get("status") not in {"PASS", "FAIL", "BLOCK", "NOT-RUN", "N/A"}:
        issues.append("pressure status missing")
    else:
        pressure_status = pressure["status"]
        if pressure_status in {"PASS", "FAIL"}:
            issues.extend(evidence_issues(directory, pressure.get("evidence"), "pressure"))
            if pressure.get("signed_thresholds") is not True and pressure_status == "PASS":
                issues.append("pressure PASS without signed thresholds")
            if pressure.get("attempted") is not True:
                issues.append("measured pressure not marked attempted")
        elif not pressure.get("reason"):
            issues.append("unrun/blocked pressure requires reason")
        failed |= pressure_status == "FAIL"
        blocked |= pressure_status in {"BLOCK", "NOT-RUN"}
    review = data.get("review")
    if not isinstance(review, dict) or review.get("status") not in {"PENDING", "APPROVED"}:
        issues.append("independent review status missing")
        blocked = True
    elif review["status"] == "APPROVED":
        if not review.get("reviewer") or review.get("decision") != "approved":
            issues.append("approved review identity or decision missing")
        issues.extend(evidence_issues(directory, review.get("evidence"), "review"))
    else:
        blocked = True
    if not passed_count:
        blocked = True
    derived = "FAIL" if failed else "BLOCK" if blocked else "PASS"
    if data.get("verdict") != derived:
        issues.append(f"verdict contradicts evidence: expected {derived}")
    return issues


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_execution.py OUTPUT_DIR", file=sys.stderr)
        return 2
    problems = validate(Path(sys.argv[1]))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("Execution evidence structure consistent; independent semantic review still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
