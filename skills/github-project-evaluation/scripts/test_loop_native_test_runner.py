import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.environ.get("LOOP_TEST_ENGINE_ROOT", str(
    Path(__file__).resolve().parents[4] / "source/loop-release-20261019/loop-dev-0927/loop-engine")))

from adapters.task_runner import TaskInput
from loop_native_test_runner import NativeProjectTestRunner


class NativeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.evidence = root / "evidence"
        self.project.mkdir()
        self.evidence.mkdir()
        (self.evidence / "home").mkdir()
        (self.evidence / "scratch").mkdir()
        self.manifest = root / "manifest.json"
        self.spec = {"project_root": str(self.project), "evidence_root": str(self.evidence),
                     "home": str(self.evidence / "home"), "scratch": str(self.evidence / "scratch"),
                     "max_total_seconds": 10,
                     "stages": [{"id": "native", "cwd": ".", "timeout_seconds": 3,
                                 "argv": [sys.executable, "-c", "print('native suite')"]}]}
        self.env = patch.dict(os.environ, {"LOOP_TEST_MANIFEST": str(self.manifest)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def runner(self):
        self.manifest.write_text(json.dumps(self.spec))
        return NativeProjectTestRunner()

    def request(self, stage="native"):
        return TaskInput(task_type="project-test", signals=[{"signal_pattern": stage}])

    def test_act_writes_raw_stdout_and_never_reruns(self):
        runner = self.runner()
        first = runner.run(self.request())
        self.assertEqual(first.business["status"], "passed")
        self.assertTrue(runner.validate_output(first))
        self.assertEqual((self.evidence / "native.stdout").read_text(), "native suite\n")
        self.assertEqual(runner.run(self.request()).status, "skipped")

    def test_failure_is_not_hidden_by_later_success(self):
        self.spec["stages"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(7)"]
        self.spec["stages"].append({"id": "gate", "cwd": ".", "timeout_seconds": 3,
                                    "argv": [sys.executable, "-c", "print('ok')"]})
        runner = self.runner()
        self.assertEqual(runner.run(self.request()).status, "error")
        self.assertEqual(runner.run(self.request()).status, "error")
        self.assertFalse((self.evidence / "gate.stdout").exists())
        second = runner.run(self.request("gate"))
        self.assertEqual(second.status, "error")
        self.assertEqual(second.raw_output["project_verdict"], "FAIL")
        self.assertEqual(second.raw_output["state"]["stages"]["native"]["exit_code"], 7)

    def test_timeout_kills_process_group_and_records_failure(self):
        self.spec["stages"][0].update(timeout_seconds=0.1,
            argv=[sys.executable, "-c", "import subprocess,time; subprocess.Popen(['sleep','4']); time.sleep(4)"])
        result = self.runner().run(self.request())
        self.assertEqual(result.status, "error")
        self.assertEqual(result.raw_output["state"]["stages"]["native"]["reason"], "timeout")

    def test_recovery_does_not_replay_interrupted_stage(self):
        runner = self.runner()
        state = {"schema": "native-test.state.v2", "binding": runner.binding,
                 "stages": {"native": {"status": "INTERRUPTED"}}, "elapsed": 0}
        (self.evidence / "native-test-state.json").write_text(json.dumps(state))
        result = runner.run(self.request())
        self.assertEqual(result.status, "error")
        self.assertEqual(result.raw_output["project_verdict"], "FAIL")

    def test_exhausted_cumulative_budget_blocks_without_process_spawn(self):
        runner = self.runner()
        state = {"schema": "native-test.state.v2", "binding": runner.binding, "stages": {}, "elapsed": 10}
        (self.evidence / "native-test-state.json").write_text(json.dumps(state))
        result = runner.run(self.request())
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.raw_output["state"]["stages"]["native"]["status"], "BLOCK")
        self.assertFalse((self.evidence / "native.stdout").exists())

    def test_successful_process_is_not_independent_business_acceptance(self):
        result = self.runner().run(self.request())
        self.assertEqual(result.raw_output["project_verdict"], "NOT_ACCEPTED")

    def test_out_of_order_signal_cannot_skip_first_stage(self):
        self.spec["stages"].append({"id": "gate", "cwd": ".", "timeout_seconds": 3,
                                    "argv": [sys.executable, "-c", "print('gate')"]})
        result = self.runner().run(self.request("gate"))
        self.assertEqual(result.status, "skipped")
        self.assertFalse((self.evidence / "gate.stdout").exists())

    def test_interrupted_first_stage_blocks_later_stage(self):
        self.spec["stages"].append({"id": "gate", "cwd": ".", "timeout_seconds": 3,
                                    "argv": [sys.executable, "-c", "print('gate')"]})
        runner = self.runner()
        (self.evidence / "native-test-state.json").write_text(json.dumps(
            {"schema": "native-test.state.v2", "binding": runner.binding,
             "stages": {"native": {"status": "INTERRUPTED"}}, "elapsed": 0}))
        result = runner.run(self.request("gate"))
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.raw_output["project_verdict"], "FAIL")
        self.assertFalse((self.evidence / "gate.stdout").exists())

    def test_reject_unsafe_stage_and_budget(self):
        self.spec["stages"][0]["id"] = "../escape"
        with self.assertRaises(ValueError):
            self.runner()
        self.spec["stages"][0]["id"] = "native"
        self.spec["max_total_seconds"] = 0
        with self.assertRaises(ValueError):
            self.runner()
        self.spec["max_total_seconds"] = 10
        self.spec["stages"][0]["cwd"] = "../"
        with self.assertRaises(ValueError):
            self.runner()

    def test_changed_manifest_blocks_old_success(self):
        runner = self.runner()
        self.assertEqual(runner.run(self.request()).status, "completed")
        self.spec["stages"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(9)"]
        result = self.runner().run(self.request())
        self.assertEqual(result.raw_output["plan_status"], "BLOCK")

    def test_tampered_log_is_not_reused(self):
        runner = self.runner()
        runner.run(self.request())
        (self.evidence / "native.stdout").write_text("changed")
        result = runner.run(self.request())
        self.assertEqual(result.raw_output["plan_status"], "BLOCK")

    def test_source_change_blocks_old_success(self):
        runner = self.runner()
        runner.run(self.request())
        (self.project / "new.py").write_text("changed")
        self.assertEqual(self.runner().run(self.request()).raw_output["plan_status"], "BLOCK")

    def test_partial_plan_cannot_validate_as_complete(self):
        self.spec["stages"].append({"id": "gate", "cwd": ".", "timeout_seconds": 3,
                                    "argv": [sys.executable, "-c", "print('gate')"]})
        runner = self.runner()
        first = runner.run(self.request())
        self.assertEqual(first.raw_output["plan_status"], "PENDING")
        self.assertFalse(runner.validate_output(first))
        last = runner.run(self.request("gate"))
        self.assertEqual(last.raw_output["plan_status"], "PASS")
        self.assertTrue(runner.validate_output(last))

    def test_legacy_state_and_symlink_block_without_overwrite(self):
        runner = self.runner()
        path = self.evidence / "native-test-state.json"
        path.write_text('{"stages":{},"elapsed":0}')
        before = path.read_bytes()
        self.assertEqual(runner.run(self.request()).raw_output["plan_status"], "BLOCK")
        self.assertEqual(path.read_bytes(), before)
        path.unlink()
        target = self.evidence / "target"
        target.write_bytes(before)
        path.symlink_to(target)
        self.assertEqual(runner.run(self.request()).raw_output["plan_status"], "BLOCK")
        self.assertEqual(target.read_bytes(), before)

    def test_malformed_state_preserved(self):
        runner = self.runner()
        path = self.evidence / "native-test-state.json"
        path.write_text("{")
        self.assertEqual(runner.run(self.request()).raw_output["plan_status"], "BLOCK")
        self.assertEqual(path.read_text(), "{")

    def test_external_script_argument_change_blocks_reuse(self):
        external = self.evidence.parent / "script.py"
        external.write_text("print('before')")
        self.spec["stages"][0]["argv"] = [sys.executable, str(external)]
        runner = self.runner()
        self.assertEqual(runner.run(self.request()).status, "completed")
        external.write_text("raise SystemExit(9)")
        self.assertEqual(self.runner().run(self.request()).raw_output["plan_status"], "BLOCK")

    def test_log_symlink_is_never_followed(self):
        runner = self.runner()
        target = self.evidence / "target"
        target.write_text("untouched")
        (self.evidence / "native.stdout").symlink_to(target)
        self.assertEqual(runner.run(self.request()).raw_output["plan_status"], "BLOCK")
        self.assertEqual(target.read_text(), "untouched")

    def test_output_flood_is_bounded_and_not_passed(self):
        self.spec["stages"][0]["argv"] = [sys.executable, "-c", "import os; os.write(1,b'x'*2000000)"]
        result = self.runner().run(self.request())
        self.assertLessEqual((self.evidence / "native.stdout").stat().st_size, 1_000_000)
        self.assertNotEqual(result.raw_output["plan_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
