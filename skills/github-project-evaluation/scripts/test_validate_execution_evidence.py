import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_execution_evidence import check_evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        artifacts = {}
        for role, data in (("stdout", b"PASS\n"), ("stderr", b""), ("exit", b"0\n")):
            path = f"probe.{role}"
            (self.root / path).write_bytes(data)
            artifacts[role] = {"path": path, "sha256": hashlib.sha256(data).hexdigest()}
        self.manifest = {"schema": "project-tests.evidence.v2", "repository": "example/demo",
                         "commit": "a" * 40, "cases": [{"case_id": "probe", "expected_exit_code": 0,
                                                      "artifacts": artifacts}]}

    def check(self):
        return check_evidence(self.manifest, self.root)

    def test_real_bytes_are_integrity_only_never_approval(self):
        result = self.check()
        self.assertEqual(result["local_integrity"], "INTACT_LOCAL")
        self.assertEqual(result["evidence_trust"], "LOCAL_UNAUTHENTICATED")
        self.assertEqual(result["candidate_acceptance"], "NOT_REVIEWED")
        self.assertEqual(result["decision"], "BLOCK")

    def test_log_corruption_is_blocked(self):
        (self.root / "probe.stdout").write_bytes(b"FAIL\n")
        self.assertIn("probe/stdout: digest_mismatch", self.check()["reasons"])

    def test_forged_matching_hash_and_failure_exit_still_blocked(self):
        (self.root / "probe.exit").write_bytes(b"1\n")
        self.manifest["cases"][0]["artifacts"]["exit"]["sha256"] = hashlib.sha256(b"1\n").hexdigest()
        self.assertIn("probe/exit: unexpected_exit_code", self.check()["reasons"])

    def test_symlink_and_traversal_do_not_read_outside_artifacts(self):
        (self.root / "probe.stdout").unlink()
        (self.root / "probe.stdout").symlink_to("/etc/passwd")
        self.assertIn("probe/stdout: OSError", self.check()["reasons"])
        self.manifest["cases"][0]["artifacts"]["stdout"]["path"] = "../secret"
        self.assertIn("probe/stdout: ValueError", self.check()["reasons"])

    def test_missing_case_data_and_duplicate_ids_rejected(self):
        self.manifest["cases"][0]["artifacts"].pop("stderr")
        with self.assertRaises(ValueError):
            self.check()
        self.manifest["cases"][0]["artifacts"]["stderr"] = {"path": "probe.stderr", "sha256": "0" * 64}
        self.manifest["cases"].append(self.manifest["cases"][0])
        with self.assertRaises(ValueError):
            self.check()

    def test_claimed_approved_review_cannot_promote_local_integrity(self):
        self.manifest["review"] = {"status": "APPROVED"}
        self.manifest["verdict"] = "PASS"
        self.assertEqual(self.check()["decision"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
