import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validate_execution import validate


class ExecutionGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        (self.root / "evidence").mkdir()
        self.log = self.root / "evidence" / "run.log"
        self.log.write_text("FAIL independently observed\n", encoding="utf-8")
        self.digest = hashlib.sha256(self.log.read_bytes()).hexdigest()
        self.reference = {"path": "evidence/run.log", "sha256": self.digest}
        self.exit_log = self.root / "evidence" / "run.exit"
        self.exit_log.write_text("1\n", encoding="utf-8")
        self.exit_reference = {"path": "evidence/run.exit",
                               "sha256": hashlib.sha256(self.exit_log.read_bytes()).hexdigest()}
        self.document = {
            "schema": "project-tests.execution.v1",
            "run_id": "frozen-r1", "source_sha256": "a" * 64,
            "scope": {"environment": "isolated", "authorization": "user-approved-local-copy"},
            "gate": {"exit_code": 1, "evidence": self.reference, "exit_evidence": self.exit_reference},
            "cases": [{"id": "F-01", "status": "FAIL", "expected": "no path leakage",
                       "actual": "full path leaked", "oracle": {"kind": "independent", "reference": "owner path policy"},
                       "evidence": self.reference}],
            "pressure": {"status": "BLOCK", "attempted": True, "reason": "no signed SLO"},
            "review": {"status": "PENDING"}, "verdict": "FAIL",
        }

    def check(self):
        (self.root / "TEST-EXECUTION.json").write_text(json.dumps(self.document), encoding="utf-8")
        return validate(self.root)

    def test_real_failure_remains_fail(self):
        self.assertEqual(self.check(), [])

    def test_gate_failure_cannot_be_promoted(self):
        self.document["verdict"] = "PASS"
        self.assertIn("verdict contradicts evidence", "\n".join(self.check()))

    def test_forged_gate_exit_rejected(self):
        self.document["gate"]["exit_code"] = 0
        self.assertIn("gate exit evidence contradicts claimed code", "\n".join(self.check()))

    def test_non_utf8_exit_record_rejected_without_crash(self):
        self.exit_log.write_bytes(b"\xff\n")
        self.exit_reference["sha256"] = hashlib.sha256(self.exit_log.read_bytes()).hexdigest()
        self.assertIn("gate exit evidence unreadable", "\n".join(self.check()))

    def test_self_judged_case_rejected(self):
        self.document["cases"][0]["oracle"] = {"kind": "self", "reference": "Loop Verify"}
        self.assertIn("independent oracle", "\n".join(self.check()))

    def test_fake_unsigned_capacity_pass_rejected(self):
        self.document["pressure"] = {"status": "PASS", "attempted": True,
                                     "signed_thresholds": False, "evidence": self.reference}
        self.assertIn("pressure PASS without signed thresholds", "\n".join(self.check()))

    def test_tampered_evidence_rejected(self):
        self.log.write_text("PASS\n", encoding="utf-8")
        self.assertIn("evidence digest mismatch", "\n".join(self.check()))

    def test_blocked_oracle_needs_reason(self):
        self.document["cases"][0] = {"id": "F-01", "status": "BLOCK"}
        self.document["verdict"] = "FAIL"
        self.assertIn("needs reason", "\n".join(self.check()))

    def test_pending_review_prevents_success(self):
        self.document["gate"]["exit_code"] = 0
        self.exit_log.write_text("0\n", encoding="utf-8")
        self.exit_reference["sha256"] = hashlib.sha256(self.exit_log.read_bytes()).hexdigest()
        self.document["cases"][0].update(status="PASS", actual="no path leak")
        self.document["pressure"] = {"status": "N/A", "reason": "non-loadable pure calculation"}
        self.document["verdict"] = "PASS"
        self.assertIn("verdict contradicts evidence", "\n".join(self.check()))

    def test_structurally_reviewed_positive(self):
        self.document["gate"]["exit_code"] = 0
        self.exit_log.write_text("0\n", encoding="utf-8")
        self.exit_reference["sha256"] = hashlib.sha256(self.exit_log.read_bytes()).hexdigest()
        self.document["cases"][0].update(status="PASS", actual="no path leak")
        self.document["pressure"] = {"status": "N/A", "reason": "non-loadable pure calculation"}
        self.document["review"] = {"status": "APPROVED", "reviewer": "independent reviewer",
                                   "decision": "approved", "evidence": self.reference}
        self.document["verdict"] = "PASS"
        self.assertEqual(self.check(), [])

    def test_all_not_applicable_cannot_be_success(self):
        self.document["gate"]["exit_code"] = 0
        self.exit_log.write_text("0\n", encoding="utf-8")
        self.exit_reference["sha256"] = hashlib.sha256(self.exit_log.read_bytes()).hexdigest()
        self.document["cases"] = [{"id": "F-01", "status": "N/A", "reason": "not applicable"}]
        self.document["pressure"] = {"status": "N/A", "reason": "pure calculation"}
        self.document["review"] = {"status": "APPROVED", "reviewer": "external person",
                                   "decision": "approved", "evidence": self.reference}
        self.document["verdict"] = "PASS"
        self.assertIn("verdict contradicts evidence", "\n".join(self.check()))

    def test_rejected_review_cannot_be_approved(self):
        self.document["review"] = {"status": "APPROVED", "reviewer": "external person",
                                   "decision": "rejected", "evidence": self.reference}
        self.assertIn("approved review identity or decision missing", "\n".join(self.check()))

    def test_outside_evidence_rejected(self):
        self.document["cases"][0]["evidence"] = {"path": "../outside.log", "sha256": self.digest}
        self.assertIn("outside run directory", "\n".join(self.check()))


if __name__ == "__main__":
    unittest.main()
