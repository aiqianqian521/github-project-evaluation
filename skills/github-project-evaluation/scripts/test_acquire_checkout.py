from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

import acquire_checkout as acquisition


class AcquisitionTests(unittest.TestCase):
    def test_disappearing_git_lock_is_not_a_special_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gone = root / "packed-refs.lock"
            with patch.object(Path, "rglob", return_value=iter([gone])):
                self.assertEqual(acquisition.measure(root), (0, 0))

    def test_actual_local_process_final_aggregate_overshoot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "checkout"
            root.mkdir()
            code = ("from pathlib import Path; import sys; p=Path(sys.argv[1]); "
                    "(p/'one').write_bytes(b'x'*600000); (p/'two').write_bytes(b'x'*600000)")
            result = acquisition.run([sys.executable, "-B", "-c", code, str(root)], root, home,
                                     1_048_576, 100, time.monotonic() + 5)
            self.assertIn(result["exit"], (0, -15))
            with self.assertRaisesRegex(ValueError, "final_byte_budget_exceeded"):
                acquisition.accepted_measure(root, 1_048_576, 100)

    def test_actual_local_process_deadline_is_stopped_and_reaped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = acquisition.run([sys.executable, "-B", "-c", "import time;time.sleep(5)"],
                                     root, root, 1_048_576, 100, time.monotonic() + .05)
        self.assertEqual(result["stop"], "deadline_stop")
        self.assertNotEqual(result["exit"], 0)
        self.assertLess(result["seconds"], 2)

    def test_hard_quota_requirement_blocks_before_network(self):
        with patch.object(acquisition, "run") as run:
            result = acquisition.acquire("example/demo", Path("unused"), require_hard_quota=True)
        run.assert_not_called()
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["budget"]["transient_disk_hard_quota"])

    def test_accepted_artifact_budget_is_exact_not_sampled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "blob").write_bytes(b"123456789")
            self.assertEqual(acquisition.accepted_measure(root, 9, 1), {"bytes": 9, "files": 1})
            with self.assertRaisesRegex(ValueError, "final_byte_budget_exceeded"):
                acquisition.accepted_measure(root, 8, 1)
            with self.assertRaisesRegex(ValueError, "file_count_budget"):
                acquisition.accepted_measure(root, 9, 0)

    def test_final_check_rejects_between_poll_overshoot_without_promotion(self):
        def fake_run(command, root, home, *args):
            if "checkout" in command:
                (root / "overshoot").write_bytes(b"x" * 1_048_577)
            return {"exit": 0, "stop": None, "stdout": "", "stderr": ""}
        with tempfile.TemporaryDirectory() as temporary, patch.object(acquisition, "run", side_effect=fake_run):
            destination = Path(temporary) / "checkout"
            result = acquisition.acquire("example/demo", destination, byte_budget=1_048_576)
            self.assertEqual(result["status"], "BLOCK")
            self.assertEqual(result["reason"], "final_byte_budget_exceeded")
            self.assertFalse(destination.exists())

    def test_sparse_first_order_no_ordinary_clone_and_commit_must_match(self):
        commands = []
        def fake_run(command, root, *args):
            commands.append(command)
            (root / "README.md").write_text("read-only fixture")
            return {"exit": 0, "stop": None, "stdout": "a" * 40 + "\n" if "rev-parse" in command else "", "stderr": ""}
        with tempfile.TemporaryDirectory() as temporary, patch.object(acquisition, "run", side_effect=fake_run):
            destination = Path(temporary) / "checkout"
            result = acquisition.acquire("example/demo", destination, commit="a" * 40)
            self.assertEqual(result["status"], "ACQUIRED_SPARSE")
            self.assertTrue(destination.is_dir())
            self.assertIn("--filter=blob:none", commands[0])
            self.assertIn("--no-checkout", commands[0])
            self.assertIn("sparse-checkout", commands[1])
            self.assertIn("checkout", commands[2])
            self.assertFalse(result["code_executed"])
        with tempfile.TemporaryDirectory() as temporary, patch.object(acquisition, "run", side_effect=fake_run):
            destination = Path(temporary) / "checkout"
            result = acquisition.acquire("example/demo", destination, commit="b" * 40)
            self.assertEqual(result["status"], "BLOCK")
            self.assertFalse(destination.exists())

    def test_git_failure_or_unsupported_filter_has_no_fallback(self):
        for code, stderr in ((128, "fatal fixture"), (0, "warning: filtering not recognized by server, ignoring")):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary, patch.object(
                    acquisition, "run", return_value={"exit": code, "stop": None, "stderr": stderr}) as run:
                destination = Path(temporary) / "checkout"
                result = acquisition.acquire("example/demo", destination)
                self.assertEqual(result["status"], "BLOCK")
                self.assertEqual(run.call_count, 1)
                self.assertFalse(destination.exists())

    def test_symlink_and_special_path_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").symlink_to("missing")
            with self.assertRaisesRegex(ValueError, "symlink"):
                acquisition.accepted_measure(root, 100, 10)

    def test_invalid_repo_commit_and_existing_destination_rejected(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(acquisition, "run") as run:
            for repo in ("../demo", "example/..", "https://github.com/a/b", "a/b;cmd"):
                with self.assertRaises(ValueError):
                    acquisition.acquire(repo, Path(temporary) / "checkout")
            with self.assertRaises(ValueError):
                acquisition.acquire("example/demo", Path(temporary))
            with self.assertRaises(ValueError):
                acquisition.acquire("example/demo", Path(temporary) / "checkout", commit="HEAD;cmd")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
