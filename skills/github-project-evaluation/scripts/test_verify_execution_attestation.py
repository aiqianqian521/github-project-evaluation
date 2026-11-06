import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_execution_attestation import verify
from crypto_runtime import openssl_binary, openssl_capability


class SignedEvidenceTests(unittest.TestCase):
    def setUp(self):
        capability = openssl_capability()
        if capability["status"] != "READY":
            self.skipTest("trusted OpenSSL Ed25519 unavailable; see tools/doctor.py")
        self.openssl = openssl_binary()
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.key = self.root / "private.pem"
        self.public = self.root / "public.pem"
        subprocess.run([self.openssl, "genpkey", "-algorithm", "ED25519", "-out", str(self.key)],
                       check=True, capture_output=True)
        subprocess.run([self.openssl, "pkey", "-in", str(self.key), "-pubout", "-out", str(self.public)],
                       check=True, capture_output=True)
        self.pinned = hashlib.sha256(self.public.read_bytes()).hexdigest()
        self.spec = "b" * 64
        self.run_id = "math-holdout-01"
        artifact_records = {}
        for role, content in (("stdout", b"failures=0\n"), ("stderr", b""), ("exit", b"0\n")):
            name = "oracle." + role
            (self.root / name).write_bytes(content)
            artifact_records[role] = {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
        self.manifest = {"schema": "project-tests.evidence.v2", "repository": "example/demo",
                         "commit": "a" * 40, "cases": [{"case_id": "oracle", "expected_exit_code": 0,
                                                      "artifacts": artifact_records}]}
        self.manifest_bytes = json.dumps(self.manifest).encode()
        self.envelope = {"schema": "project-tests.attestation.v1", "repository": "example/demo",
                         "commit": "a" * 40, "run_id": self.run_id, "task_spec_sha256": self.spec,
                         "manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest()}
        self.sign_envelope()

    def sign_envelope(self):
        self.envelope_bytes = json.dumps(self.envelope).encode()
        envelope_file = self.root / "envelope.json"
        envelope_file.write_bytes(self.envelope_bytes)
        signature = self.root / "signature.bin"
        subprocess.run([self.openssl, "pkeyutl", "-sign", "-inkey", str(self.key),
                        "-rawin", "-in", str(envelope_file), "-out", str(signature)],
                       check=True, capture_output=True)
        self.signature_bytes = signature.read_bytes()

    def check(self, **overrides):
        arguments = {"envelope_bytes": self.envelope_bytes, "signature_bytes": self.signature_bytes,
                     "key_bytes": self.public.read_bytes(), "pinned_key_sha256": self.pinned,
                     "manifest_bytes": self.manifest_bytes, "artifacts_root": self.root,
                     "expected_repository": "example/demo", "expected_commit": "a" * 40,
                     "expected_run_id": self.run_id, "expected_spec_sha256": self.spec,
                     "temporary_parent": self.root}
        arguments.update(overrides)
        return verify(**arguments)

    def test_signed_evidence_still_blocks_project_approval(self):
        result = self.check()
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["signature_status"], "CRYPTO_VALID")
        self.assertEqual(result["key_pin_status"], "MATCH")
        self.assertEqual(result["anchor_trust"], "CALLER_ASSERTED_NOT_INDEPENDENTLY_VERIFIED")
        self.assertEqual(result["decision"], "BLOCK")

    def test_rewriting_log_and_manifest_hash_cannot_reuse_signed_envelope(self):
        changed = b"failures=1\n"
        (self.root / "oracle.stdout").write_bytes(changed)
        self.manifest["cases"][0]["artifacts"]["stdout"]["sha256"] = hashlib.sha256(changed).hexdigest()
        result = self.check(manifest_bytes=json.dumps(self.manifest).encode())
        self.assertIn("manifest_binding_mismatch", result["reasons"])
        self.assertEqual(result["signature_status"], "CRYPTO_VALID")

    def test_changing_signed_envelope_without_signer_breaks_signature(self):
        self.envelope["manifest_sha256"] = "c" * 64
        result = self.check(envelope_bytes=json.dumps(self.envelope).encode())
        self.assertIn("signature_invalid", result["reasons"])

    def test_wrong_run_spec_and_public_key_pin_fail(self):
        result = self.check(expected_run_id="other-run", expected_spec_sha256="c" * 64,
                            pinned_key_sha256="d" * 64)
        self.assertIn("run_binding_mismatch", result["reasons"])
        self.assertIn("task_spec_binding_mismatch", result["reasons"])
        self.assertIn("public_key_pin_mismatch", result["reasons"])

    def test_unsigned_failure_log_is_not_approved(self):
        (self.root / "oracle.stdout").write_bytes(b"failures=1\n")
        result = self.check(signature_bytes=b"invalid")
        self.assertIn("local_artifact_integrity_failed", result["reasons"])
        self.assertIn("signature_invalid", result["reasons"])

    def test_self_signed_fake_key_requires_matching_independent_pin(self):
        alternate = self.root / "alternate.pem"
        alternate_public = self.root / "alternate-public.pem"
        subprocess.run([self.openssl, "genpkey", "-algorithm", "ED25519", "-out", str(alternate)],
                       check=True, capture_output=True)
        subprocess.run([self.openssl, "pkey", "-in", str(alternate), "-pubout", "-out", str(alternate_public)],
                       check=True, capture_output=True)
        alternate_signature = self.root / "alternate.sig"
        subprocess.run([self.openssl, "pkeyutl", "-sign", "-inkey", str(alternate),
                        "-rawin", "-in", str(self.root / "envelope.json"), "-out", str(alternate_signature)],
                       check=True, capture_output=True)
        result = self.check(key_bytes=alternate_public.read_bytes(),
                            signature_bytes=alternate_signature.read_bytes())
        self.assertEqual(result["signature_status"], "CRYPTO_VALID")
        self.assertIn("public_key_pin_mismatch", result["reasons"])


if __name__ == "__main__":
    unittest.main()
