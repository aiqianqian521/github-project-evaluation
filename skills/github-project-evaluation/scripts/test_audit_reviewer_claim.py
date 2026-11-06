import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_reviewer_claim import audit


class ReviewerAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.first_pass = self.root / "first-pass.json"
        self.review = self.root / "review.txt"
        self.execution = self.root / "execution.json"
        self.first_pass.write_text(json.dumps({
            "schema": "project-first-pass.v1", "expected_repository": "psf/requests",
            "local_commit": "a" * 40, "evidence_score": 100, "goal_fit": "NOT_REVIEWED",
            "upstream_commit_verified": False, "license_approved": False,
            "deployment_test_gate": "BLOCK"}))
        self.review.write_text("结论：合格部署。")

    def test_false_green_claim_is_flagged_and_never_approved(self):
        self.execution.write_text(json.dumps({"schema": "project-tests.execution.v1",
            "repository": "psf/requests", "commit": "a" * 40, "verdict": "FAIL",
            "gate": {"exit_code": 1}, "review": {"status": "PENDING"}}))
        result = audit(self.first_pass, self.review, self.execution)
        self.assertTrue(result["claim_requires_correction"])
        self.assertEqual(result["deployment_test_gate"], "BLOCK")
        self.assertIn("independent_execution_not_passed", result["blocking_reasons"])

    def test_audit_exit_status_and_provenance(self):
        destination = self.root / "fresh"
        process = subprocess.run([sys.executable, str(Path(__file__).with_name("audit_reviewer_claim.py")),
            "--first-pass", str(self.first_pass), "--review-text", str(self.review),
            "--output-dir", str(destination)], capture_output=True, check=False)
        self.assertEqual(process.returncode, 2)
        report = json.loads((destination / "REVIEW-AUDIT.json").read_text())
        self.assertEqual(report["decision"], "BLOCK")
        self.assertRegex(report["review_text_sha256"], r"\A[0-9a-f]{64}\Z")
        self.assertIn("independent_execution_not_provided", report["blocking_reasons"])

    def test_forged_green_execution_cannot_bypass_human_gate(self):
        self.execution.write_text(json.dumps({"schema": "project-tests.execution.v1",
            "repository": "psf/requests", "commit": "a" * 40, "verdict": "PASS",
            "gate": {"exit_code": 0}, "review": {"status": "APPROVED"}}))
        result = audit(self.first_pass, self.review, self.execution)
        self.assertEqual(result["decision"], "BLOCK")
        self.assertIn("human_goal_fit_not_reviewed", result["blocking_reasons"])

    def test_execution_without_identity_is_rejected(self):
        self.execution.write_text(json.dumps({"schema": "project-tests.execution.v1",
            "verdict": "PASS", "gate": {"exit_code": 0}, "review": {"status": "APPROVED"}}))
        result = audit(self.first_pass, self.review, self.execution)
        self.assertIn("execution_not_bound_to_frozen_repository", result["blocking_reasons"])

    def test_modified_first_pass_gate_is_fail_closed(self):
        first_pass = json.loads(self.first_pass.read_text())
        first_pass["deployment_test_gate"] = "APPROVE"
        self.first_pass.write_text(json.dumps(first_pass))
        result = audit(self.first_pass, self.review)
        self.assertIn("first_pass_gate_changed_or_unrecognized", result["blocking_reasons"])

    def test_unverified_legacy_self_reported_pass_never_becomes_verified(self):
        self.execution.write_text(json.dumps({"schema": "project-tests.execution.v1",
            "repository": "psf/requests", "commit": "a" * 40, "verdict": "PASS",
            "gate": {"exit_code": 0}, "review": {"status": "APPROVED"}}))
        result = audit(self.first_pass, self.review, self.execution)
        self.assertEqual(result["execution_verdict"], "UNVERIFIED_CLAIM")
        self.assertIn("legacy_execution_contract_not_verified", result["blocking_reasons"])
        self.assertEqual(result["decision"], "BLOCK")

    def test_benign_review_remains_blocked_without_false_claim(self):
        self.review.write_text("仅供审核；待业务真值和用户签收。")
        result = audit(self.first_pass, self.review)
        self.assertFalse(result["possible_release_claim"])
        self.assertEqual(result["decision"], "BLOCK")

    def test_explicitly_not_deployable_is_not_approval(self):
        self.review.write_text("尚不可部署；可部署性未经验证。")
        self.assertFalse(audit(self.first_pass, self.review)["possible_release_claim"])
        self.review.write_text("该项目可部署。")
        self.assertTrue(audit(self.first_pass, self.review)["possible_release_claim"])

    def test_oversized_or_symlink_review_rejected(self):
        self.review.write_bytes(b"z" * 256001)
        with self.assertRaises(ValueError):
            audit(self.first_pass, self.review)
        self.review.unlink()
        self.review.symlink_to(self.first_pass)
        with self.assertRaises(ValueError):
            audit(self.first_pass, self.review)

    def test_malformed_execution_is_rejected(self):
        self.execution.write_text(json.dumps({"schema": "project-tests.execution.v1",
            "gate": None, "review": {"status": "APPROVED"}}))
        with self.assertRaises(ValueError):
            audit(self.first_pass, self.review, self.execution)

    def test_output_symlink_into_checkout_is_rejected(self):
        checkout = self.root / "repo"
        (checkout / ".git").mkdir(parents=True)
        alias = self.root / "aliased-repo"
        alias.symlink_to(checkout, target_is_directory=True)
        destination = alias / "audit"
        process = subprocess.run([sys.executable, str(Path(__file__).with_name("audit_reviewer_claim.py")),
            "--first-pass", str(self.first_pass), "--review-text", str(self.review),
            "--output-dir", str(destination)], capture_output=True, check=False)
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse((checkout / "audit").exists())


if __name__ == "__main__":
    unittest.main()
