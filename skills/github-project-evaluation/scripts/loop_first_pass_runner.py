"""Native Loop Act for offline discovery followed by bounded static review."""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlencode

from adapters.task_runner import TaskInput, TaskResult, TaskRunner
from discover import SITE, Cache, discover, write_report
from evaluate_first_pass import evaluate, git_value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FirstPassWorkflowRunner(TaskRunner):
    STAGES = ("discovery", "first_pass")

    def __init__(self, settings=None):
        config_path = Path(os.environ["LOOP_FIRST_PASS_CONFIG"])
        self.config_sha256 = digest(config_path)
        self.spec = json.loads(config_path.read_text(encoding="utf-8"))
        self.root = Path(self.spec["root"]).resolve(strict=True)
        self.checkout = Path(self.spec["checkout"]).resolve(strict=True)
        self.snapshots = self.root / "snapshots"
        self.evidence = self.root / "evidence"
        if (not self.root.is_dir() or not self.checkout.is_dir() or
                not self.checkout.is_relative_to(self.root / "checkouts") or
                self.snapshots.is_symlink() or
                self.evidence.is_symlink() or not self.snapshots.is_dir() or
                not self.evidence.is_dir() or
                not 0 < self.spec["max_pages"] <= 25 or not self.spec["query"].strip() or
                self.spec.get("source_mode", "site") not in {"site", "multi"}):
            raise ValueError("invalid isolated workflow configuration")
        if (self.snapshots / ".query").read_text(encoding="utf-8").strip() != self.spec["query"].strip():
            raise ValueError("snapshot query mismatch")

    def validate_output(self, result):
        return result.status == "completed" and result.output.get("status") == "valid"

    def input_identity(self, stage):
        parts = [self.config_sha256, digest(Path(__file__)),
                 digest(Path(__file__).with_name("discover.py")),
                 digest(Path(__file__).with_name("evaluate_first_pass.py")),
                 digest(self.snapshots / ".query")]
        for number in range(1, self.spec["max_pages"] + 1):
            snapshot = self.snapshots / f"page-{number}.html"
            parts.append(digest(snapshot) if snapshot.is_file() and not snapshot.is_symlink() else "MISSING")
        if stage == "first_pass":
            report = self.evidence / "discovery/candidates.json"
            parts.append(digest(report))
            parts.append(git_value(self.checkout, "rev-parse", "HEAD") or "MISSING")
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def verify_existing(self, stage, record):
        if record.get("status") != "COMPLETE" or record.get("input_sha256") != self.input_identity(stage):
            return False
        output = self.evidence / stage / ("candidates.json" if stage == "discovery" else "FIRST-PASS.json")
        if not output.is_file() or output.is_symlink() or digest(output) != record.get("sha256"):
            return False
        if stage == "first_pass":
            observed = evaluate(self.checkout, self.spec["expected_repo"],
                                self.evidence / "discovery/candidates.json")
            return observed == json.loads(output.read_text(encoding="utf-8"))
        return True

    def execute_discovery(self):
        cache = Cache(self.root / "cache", offline=True)
        for number in range(1, self.spec["max_pages"] + 1):
            snapshot = self.snapshots / f"page-{number}.html"
            if snapshot.is_file() and not snapshot.is_symlink():
                url = SITE + "/zh-cn/search.html?" + urlencode({
                    "q": self.spec["query"], "updated": "365d", "sort": "stars_desc", "page": number})
                cache.seed_snapshot(url, snapshot)
        result = discover(self.spec["query"], cache, self.spec.get("source_mode", "site"),
                          self.spec["max_pages"], 0)
        if not any(
                row["full_name"].lower() == self.spec["expected_repo"].lower()
                for row in result["candidates"]):
            raise ValueError("candidate absent from observed sources")
        staging = self.evidence / ".discovery.attempt"
        write_report(result, staging)
        staging.rename(self.evidence / "discovery")
        return {"status": "COMPLETE", "coverage_status": result["status"],
                "rows_seen": result["rows_seen"],
                "sha256": digest(self.evidence / "discovery/candidates.json")}

    def execute_first_pass(self):
        staging = self.evidence / ".first_pass.attempt"
        command = [sys.executable, str(Path(__file__).with_name("evaluate_first_pass.py")),
                   str(self.checkout), "--expected-repo", self.spec["expected_repo"],
                   "--discovery-file", str(self.evidence / "discovery/candidates.json"),
                   "--output-dir", str(staging)]
        try:
            result = subprocess.run(command, cwd=self.root, capture_output=True, timeout=60,
                                    check=False, env={"PATH": "/usr/bin:/bin", "HOME": str(self.root),
                                                      "TMPDIR": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"})
        except subprocess.TimeoutExpired as failure:
            (self.evidence / "first_pass.stdout").write_bytes((failure.stdout or b"")[:4096])
            (self.evidence / "first_pass.stderr").write_bytes((failure.stderr or b"")[:4096])
            (self.evidence / "first_pass.exit").write_text("124\n")
            raise
        (self.evidence / "first_pass.stdout").write_bytes(result.stdout[:4096])
        (self.evidence / "first_pass.stderr").write_bytes(result.stderr[:4096])
        (self.evidence / "first_pass.exit").write_text(str(result.returncode) + "\n")
        if result.returncode != 0:
            raise ValueError("first-pass inventory rejected checkout")
        report = json.loads((staging / "FIRST-PASS.json").read_text(encoding="utf-8"))
        if not report["discovery_candidate_matched"] or report["deployment_test_gate"] != "BLOCK":
            raise ValueError("first-pass contract violation")
        staging.rename(self.evidence / "first_pass")
        return {"status": "COMPLETE", "score": report["evidence_score"],
                "triage": report["triage"], "deployment_test_gate": report["deployment_test_gate"],
                "sha256": digest(self.evidence / "first_pass/FIRST-PASS.json")}

    def run(self, input: TaskInput) -> TaskResult:
        signals = input.signals or []
        stage = signals[0].get("signal_pattern") if len(signals) == 1 and isinstance(signals[0], dict) else None
        if stage not in self.STAGES:
            return self.result("error", stage, {}, "invalid stage signal")
        with (self.evidence / "workflow.lock").open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state_file = self.evidence / "workflow-state.json"
            state = json.loads(state_file.read_text()) if state_file.exists() else {}
            if stage in state:
                try:
                    valid = self.verify_existing(stage, state[stage])
                except (OSError, ValueError, UnicodeError, json.JSONDecodeError, subprocess.TimeoutExpired):
                    valid = False
                return self.result("completed" if valid else "error", stage, state,
                                   "stage already recorded; identity or artifact changed" if not valid else "")
            if stage == "first_pass" and (
                    state.get("discovery", {}).get("status") != "COMPLETE" or
                    not self.verify_existing("discovery", state["discovery"])):
                return self.result("skipped", stage, state, "discovery not verified")
            try:
                identity = self.input_identity(stage)
            except (OSError, ValueError, TypeError):
                return self.result("error", stage, state, "input identity unavailable")
            state[stage] = {"status": "INTERRUPTED", "input_sha256": identity}
            self.save(state_file, state)
            try:
                details = self.execute_discovery() if stage == "discovery" else self.execute_first_pass()
                state[stage].update(details)
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError, subprocess.TimeoutExpired) as failure:
                state[stage].update({"status": "BLOCK", "reason": type(failure).__name__})
            self.save(state_file, state)
            return self.result("completed" if state[stage]["status"] == "COMPLETE" else "error",
                               stage, state, state[stage].get("reason", ""))

    @staticmethod
    def save(path, state):
        replacement = path.with_suffix(".new")
        replacement.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        os.replace(replacement, path)

    @staticmethod
    def result(status, stage, state, reason):
        completed = status == "completed"
        return TaskResult(status=status,
            execution={"status": "succeeded" if completed else "failed", "code": stage or "invalid"},
            output={"status": "valid" if completed else "not_available"},
            business={"status": "passed" if completed else "not_evaluated",
                      "scope": "evidence-record-only", "candidate_approval": "NOT_REVIEWED"},
            metrics={"records_written": int(completed), "stages_failed": int(not completed)},
            errors=[] if completed else [{"signature": "first-pass:blocked", "evidence": reason}],
            provenance={"adapter": "first-pass-workflow"},
            raw_output={"stages": state, "candidate_approval": "NOT_REVIEWED",
                        "deployment_test_gate": "BLOCK"})
