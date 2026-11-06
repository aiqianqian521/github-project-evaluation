import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.environ.get("LOOP_TEST_ENGINE_ROOT", str(
    Path(__file__).resolve().parents[3] / "source/loop-release-20261019/loop-dev-0927/loop-engine")))
from adapters.task_runner import TaskInput
from loop_first_pass_runner import FirstPassWorkflowRunner


class FirstPassWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "checkouts/demo"
        self.repo.mkdir(parents=True)
        (self.root / "snapshots").mkdir()
        (self.root / "evidence").mkdir()
        (self.root / "snapshots/.query").write_text("demo")
        (self.root / "snapshots/page-1.html").write_text(
            '<span>搜索结果 <strong>1</strong></span><article class="ornav-repo">'
            '<h3>demo</h3><p>example</p><bdi>example/demo</bdi></article>')
        for name, content in (("README.md", "Read me"), ("LICENSE", "MIT License"),
                              ("pyproject.toml", "[project]\nname='demo'"),
                              ("src/demo.py", "name = 'demo'"),
                              ("tests/test_demo.py", "assert True")):
            file = self.repo / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        self.git("init", "-q")
        self.git("remote", "add", "origin", "https://github.com/example/demo.git")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "frozen fixture")
        self.config = self.root / "workflow.json"
        self.config.write_text(json.dumps({"root": str(self.root), "checkout": str(self.repo),
                                           "expected_repo": "example/demo", "query": "demo",
                                           "max_pages": 1}))
        self.environment = patch.dict(os.environ, {"LOOP_FIRST_PASS_CONFIG": str(self.config)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.repo), *arguments], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def stage(self, name):
        return TaskInput(task_type="first-pass", signals=[{"signal_pattern": name}])

    def test_two_real_stages_are_journaled_but_not_project_approved(self):
        runner = FirstPassWorkflowRunner()
        self.assertEqual(runner.run(self.stage("discovery")).status, "completed")
        first_pass = runner.run(self.stage("first_pass"))
        self.assertEqual(first_pass.status, "completed")
        self.assertEqual(first_pass.business["scope"], "evidence-record-only")
        self.assertEqual(first_pass.raw_output["deployment_test_gate"], "BLOCK")
        report = json.loads((self.root / "evidence/first_pass/FIRST-PASS.json").read_text())
        self.assertEqual(report["discovery_binding"], "MATCHED")
        self.assertFalse(report["upstream_commit_verified"])
        self.assertEqual(report["deployment_test_gate"], "BLOCK")
        self.assertEqual(runner.run(self.stage("first_pass")).status, "completed")

    def test_out_of_order_unknown_and_report_tampering_fail_closed(self):
        runner = FirstPassWorkflowRunner()
        self.assertEqual(runner.run(self.stage("first_pass")).status, "skipped")
        self.assertEqual(runner.run(self.stage("unknown")).status, "error")
        self.assertEqual(runner.run(self.stage("discovery")).status, "completed")
        report = self.root / "evidence/discovery/candidates.json"
        report.write_text("{}")
        self.assertEqual(runner.run(self.stage("discovery")).status, "error")
        self.assertEqual(runner.run(self.stage("first_pass")).status, "skipped")

    def test_dirty_checkout_or_config_change_never_reuses_first_pass(self):
        runner = FirstPassWorkflowRunner()
        self.assertEqual(runner.run(self.stage("discovery")).status, "completed")
        self.assertEqual(runner.run(self.stage("first_pass")).status, "completed")
        (self.repo / "README.md").write_text("Changed after review")
        self.assertEqual(runner.run(self.stage("first_pass")).status, "error")
        self.git("checkout", "--", "README.md")
        self.config.write_text(json.dumps({"root": str(self.root), "checkout": str(self.repo),
                                           "expected_repo": "example/demo", "query": "demo",
                                           "max_pages": 2}))
        self.assertEqual(FirstPassWorkflowRunner().run(self.stage("first_pass")).status, "error")

    def test_partial_discovery_or_crash_does_not_advance(self):
        (self.root / "snapshots/page-1.html").unlink()
        runner = FirstPassWorkflowRunner()
        self.assertEqual(runner.run(self.stage("discovery")).status, "error")
        self.assertEqual(runner.run(self.stage("first_pass")).status, "skipped")
        self.assertEqual(runner.run(self.stage("discovery")).status, "error")

    def test_offline_multi_reports_provider_gaps_but_preserves_site_lead(self):
        self.config.write_text(json.dumps({"root": str(self.root), "checkout": str(self.repo),
                                           "expected_repo": "example/demo", "query": "demo",
                                           "max_pages": 1, "source_mode": "multi"}))
        runner = FirstPassWorkflowRunner()
        self.assertEqual(runner.run(self.stage("discovery")).status, "completed")
        discovery = json.loads((self.root / "evidence/discovery/candidates.json").read_text())
        self.assertEqual(discovery["status"], "PARTIAL")
        self.assertEqual(discovery["coverage"]["github-api"]["status"], "PARTIAL")
        self.assertEqual(discovery["coverage"]["gitstar"]["scope"], "catalog-only")
        self.assertEqual(runner.run(self.stage("first_pass")).status, "completed")
        self.assertEqual(runner.run(self.stage("first_pass")).raw_output["deployment_test_gate"], "BLOCK")

    def test_exited_stage_cannot_be_promoted_from_interrupted_record(self):
        (self.root / "evidence/workflow-state.json").write_text(json.dumps({
            "discovery": {"status": "INTERRUPTED"}}))
        self.assertEqual(FirstPassWorkflowRunner().run(self.stage("discovery")).status, "error")
        self.assertFalse((self.root / "evidence/discovery").exists())

    def test_failed_inventory_keeps_bounded_child_exit_and_error(self):
        runner = FirstPassWorkflowRunner()
        failed = subprocess.CompletedProcess([], 2, b"", b"first-pass rejected\n")
        with patch("loop_first_pass_runner.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "inventory rejected"):
                runner.execute_first_pass()
        self.assertEqual((self.root / "evidence/first_pass.exit").read_text(), "2\n")
        self.assertEqual((self.root / "evidence/first_pass.stderr").read_bytes(), failed.stderr)
        self.assertFalse((self.root / "evidence/first_pass").exists())

    def test_timed_out_inventory_keeps_partial_child_output(self):
        runner = FirstPassWorkflowRunner()
        timed_out = subprocess.TimeoutExpired(["python"], 60, output=b"start", stderr=b"timeout\n")
        with patch("loop_first_pass_runner.subprocess.run", side_effect=timed_out):
            with self.assertRaises(subprocess.TimeoutExpired):
                runner.execute_first_pass()
        self.assertEqual((self.root / "evidence/first_pass.exit").read_text(), "124\n")
        self.assertEqual((self.root / "evidence/first_pass.stdout").read_bytes(), b"start")
        self.assertEqual((self.root / "evidence/first_pass.stderr").read_bytes(), b"timeout\n")


if __name__ == "__main__":
    unittest.main()
