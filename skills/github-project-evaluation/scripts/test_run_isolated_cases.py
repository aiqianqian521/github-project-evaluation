import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_isolated_cases import execute, load_spec


class IsolatedCasesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.commit = "a" * 40
        self.spec_path = self.root / "spec.json"
        self.spec = {"schema": "project-tests.run.v1", "repository": "example/demo",
                     "commit": self.commit, "cases": [{"case_id": "sandbox",
                         "argv": ["/usr/bin/python3", "-c", "import os,socket,pathlib; assert not pathlib.Path('/home/admin').exists(); assert not os.access('/workspace',os.W_OK); socket.socket().connect(('127.0.0.1',9))"],
                         "expected_exit_code": 0, "timeout_seconds": 4, "memory_mib": 256}]}

    def write_spec(self):
        self.spec_path.write_text(json.dumps(self.spec), encoding="utf-8")
        return hashlib.sha256(self.spec_path.read_bytes()).hexdigest()

    def test_specs_are_frozen_and_reject_unbounded_commands(self):
        digest = self.write_spec()
        self.assertEqual(load_spec(self.spec_path)[1], digest)
        for change in ({"argv": ["python3", "-c", "print(1)\x00print(2)"]},
                       {"timeout_seconds": 999}, {"case_id": "../bad"}):
            with self.subTest(change=change):
                self.spec["cases"][0].update(change)
                self.write_spec()
                with self.assertRaises(ValueError):
                    load_spec(self.spec_path)

    def test_missing_isolator_wrong_hash_and_unverified_identity_fail_before_execution(self):
        digest = self.write_spec()
        with self.assertRaisesRegex(ValueError, "spec hash"):
            execute(self.spec_path, self.checkout, self.root / "output", __file__, "f" * 64)
        with patch("run_isolated_cases.evaluate", return_value={"local_commit": self.commit,
                   "identity_gate": "BLOCK"}):
            with self.assertRaisesRegex(ValueError, "identity gate BLOCK"):
                execute(self.spec_path, self.checkout, self.root / "output", sys.executable, digest)
        self.assertFalse((self.root / "output").exists())
        with self.assertRaises(OSError):
            execute(self.spec_path, self.checkout, self.root / "output", self.root / "absent-bwrap", digest)

    def test_fake_isolator_blocks_even_when_case_expects_nonzero(self):
        self.spec["cases"][0]["expected_exit_code"] = 2
        digest = self.write_spec()
        with patch("run_isolated_cases.evaluate", return_value={"local_commit": self.commit,
                   "identity_gate": "PASS"}):
            result = execute(self.spec_path, self.checkout, self.root / "output", sys.executable, digest)
        self.assertEqual(result["execution_gate"], "BLOCK")
        self.assertEqual(result["reason"], "sandbox_preflight_failed")
        self.assertFalse((self.root / "output/sandbox.stdout").exists())

    @unittest.skipUnless(os.environ.get("BWRAP_BINARY"), "set BWRAP_BINARY to run local namespace integration")
    def test_network_home_and_checkout_are_sealed_in_real_namespace(self):
        self.spec["cases"][0]["argv"] = ["/usr/bin/python3", "-c",
            "import os,socket,pathlib; assert not pathlib.Path('/home/admin').exists(); "
            "assert not pathlib.Path('/etc').exists(); "
            "assert not os.access('/workspace', os.W_OK); "
            "\ntry: socket.socket().connect(('1.1.1.1', 80))\n"
            "except OSError as exc: assert exc.errno == 101\n"
            "else: raise AssertionError('network reachable')\n"
            "print('sandbox boundary observed')"]
        digest = self.write_spec()
        with patch("run_isolated_cases.evaluate", return_value={"local_commit": self.commit,
                   "identity_gate": "PASS", "upstream_commit_verification": {"status": "VERIFIED"}}):
            result = execute(self.spec_path, self.checkout, self.root / "output",
                             os.environ["BWRAP_BINARY"], digest)
        self.assertEqual(result["execution_gate"], "RECORDED")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")
        self.assertIn("sandbox boundary observed", (self.root / "output/sandbox.stdout").read_text())

    @unittest.skipUnless(os.environ.get("BWRAP_BINARY"), "set BWRAP_BINARY to run local namespace integration")
    def test_timeout_leaves_logs_and_blocks_next_case(self):
        self.spec["cases"][0]["argv"] = ["/usr/bin/python3", "-c", "import time; time.sleep(20)"]
        self.spec["cases"][0]["timeout_seconds"] = 1
        self.spec["cases"].append({"case_id": "must_not_run", "argv": ["/usr/bin/python3", "-c", "print('oops')"],
                                   "expected_exit_code": 0, "timeout_seconds": 2, "memory_mib": 256})
        digest = self.write_spec()
        with patch("run_isolated_cases.evaluate", return_value={"local_commit": self.commit,
                   "identity_gate": "PASS", "upstream_commit_verification": {"status": "VERIFIED"}}):
            result = execute(self.spec_path, self.checkout, self.root / "output",
                             os.environ["BWRAP_BINARY"], digest)
        self.assertEqual(result["execution_gate"], "BLOCK")
        self.assertFalse((self.root / "output/must_not_run.stdout").exists())
        self.assertTrue((self.root / "output/sandbox.stderr").exists())

    @unittest.skipUnless(os.environ.get("BWRAP_BINARY"), "set BWRAP_BINARY to run local namespace integration")
    def test_signal_is_not_an_expected_successful_exit(self):
        self.spec["cases"][0]["argv"] = ["/usr/bin/python3", "-c",
            "import os,signal; os.kill(os.getpid(),signal.SIGTERM)"]
        self.spec["cases"][0]["expected_exit_code"] = 143
        digest = self.write_spec()
        with patch("run_isolated_cases.evaluate", return_value={"local_commit": self.commit,
                   "identity_gate": "PASS", "upstream_commit_verification": {"status": "VERIFIED"}}):
            result = execute(self.spec_path, self.checkout, self.root / "output",
                             os.environ["BWRAP_BINARY"], digest)
        self.assertEqual(result["execution_gate"], "BLOCK")
