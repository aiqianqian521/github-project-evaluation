import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.environ.get("LOOP_TEST_ENGINE_ROOT", str(
    Path(__file__).resolve().parents[3] / "source/loop-release-20261019/loop-dev-0927/loop-engine")))
from adapters.task_runner import TaskInput
from loop_discovery_runner import DiscoveryRunner


class LoopDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "evidence").mkdir()
        (self.root / "snapshots").mkdir()
        (self.root / "snapshots/.query").write_text("量化\n", encoding="utf-8")
        (self.root / "snapshots/page-1.html").write_text(
            '<span>搜索结果 <strong>1</strong></span><article class="ornav-repo ready">'
            '<h3>量化交易框架</h3><p>回测</p><bdi>example/engine</bdi></article>', encoding="utf-8")
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"root": str(self.root), "query": "量化", "max_pages": 1}))
        self.env = patch.dict(os.environ, {"LOOP_DISCOVERY_CONFIG": str(self.config)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def input(self, stage):
        return TaskInput(task_type="discovery", signals=[{"signal_pattern": stage}])

    def complete_online(self, runner):
        with patch("loop_discovery_runner.discover") as discover:
            discover.return_value = {"status": "COMPLETE", "rows_seen": 1,
                                     "provenance": [{"page": 1}], "errors": [], "candidates": [],
                                     "query": "量化", "source_mode": "site", "shortlist": [],
                                     "acceptance": "NOT_REVIEWED"}
            return runner.run(self.input("online"))

    def test_loop_act_runs_real_snapshot_and_negative_control(self):
        runner = DiscoveryRunner()
        with patch("loop_discovery_runner.discover") as discover:
            discover.return_value = {"status": "COMPLETE", "rows_seen": 1, "provenance": [{"page": 1}],
                                     "errors": [], "candidates": [], "query": "量化", "source_mode": "site",
                                     "shortlist": [], "acceptance": "NOT_REVIEWED"}
            online = runner.run(self.input("online"))
        self.assertEqual(online.status, "completed")
        snapshot = runner.run(self.input("snapshot"))
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.raw_output["stages"]["snapshot"]["online_row_delta"], 0)
        self.assertTrue((self.root / "snapshot-cache").is_dir())
        self.assertFalse(any((self.root / "cache").glob("*.data")))
        negative = runner.run(self.input("negative"))
        self.assertEqual(negative.status, "completed")
        self.assertEqual(negative.raw_output["acceptance"], "NOT_REVIEWED")
        self.assertTrue((self.root / "evidence/snapshot/candidates.json").is_file())
        self.assertEqual(runner.run(self.input("snapshot")).status, "completed")

    def test_failure_persists_after_snapshot_recovery(self):
        runner = DiscoveryRunner()
        with patch("loop_discovery_runner.discover") as discover:
            discover.return_value = {"status": "PARTIAL", "rows_seen": 0, "provenance": [],
                                     "errors": [{"reason": "site_unavailable"}], "candidates": [],
                                     "query": "量化", "source_mode": "site", "shortlist": [],
                                     "acceptance": "NOT_REVIEWED"}
            self.assertEqual(runner.run(self.input("online")).status, "error")
            self.assertEqual(discover.call_count, 1)
            self.assertEqual(runner.run(self.input("online")).status, "error")
            self.assertEqual(discover.call_count, 1)
        recovered = runner.run(self.input("snapshot"))
        self.assertEqual(recovered.raw_output["stages"]["snapshot"]["rows_seen"], 1)
        self.assertEqual(recovered.status, "error")

    def test_invalid_and_out_of_order_fail_closed(self):
        runner = DiscoveryRunner()
        self.assertEqual(runner.run(self.input("invalid")).status, "error")
        self.assertEqual(runner.run(self.input("snapshot")).status, "skipped")
        self.assertFalse((self.root / "evidence/snapshot").exists())

    def test_crash_journal_does_not_refetch(self):
        (self.root / "evidence/discovery-state.json").write_text(json.dumps(
            {"online": {"status": "INTERRUPTED"}}))
        runner = DiscoveryRunner()
        self.assertEqual(runner.run(self.input("online")).status, "error")
        self.assertFalse((self.root / "evidence/online").exists())

    def test_changed_config_or_cached_page_cannot_reuse_online(self):
        runner = DiscoveryRunner()
        self.assertEqual(self.complete_online(runner).status, "completed")
        (self.root / "cache/extra.data").write_text("new-cache-record")
        self.assertEqual(runner.run(self.input("online")).status, "error")
        (self.root / "cache/extra.data").unlink()
        self.assertEqual(runner.run(self.input("online")).status, "completed")
        self.config.write_text(json.dumps({"root": str(self.root), "query": "量化", "max_pages": 2}))
        self.assertEqual(DiscoveryRunner().run(self.input("online")).status, "error")

    def test_changed_snapshot_or_report_blocks_subsequent_stage(self):
        runner = DiscoveryRunner()
        self.assertEqual(self.complete_online(runner).status, "completed")
        self.assertEqual(runner.run(self.input("snapshot")).status, "completed")
        (self.root / "snapshots/page-1.html").write_text("changed")
        self.assertEqual(runner.run(self.input("snapshot")).status, "error")
        self.assertEqual(runner.run(self.input("negative")).status, "skipped")

    def test_changed_online_report_prevents_snapshot_recovery(self):
        runner = DiscoveryRunner()
        self.assertEqual(self.complete_online(runner).status, "completed")
        (self.root / "evidence/online/candidates.json").write_text("{}")
        self.assertEqual(runner.run(self.input("snapshot")).status, "skipped")
        self.assertFalse((self.root / "evidence/snapshot").exists())

    def test_malformed_journal_returns_error_without_overwrite(self):
        journal = self.root / "evidence/discovery-state.json"
        for payload in ("{", json.dumps({"online": []})):
            with self.subTest(payload=payload):
                journal.write_text(payload)
                result = DiscoveryRunner().run(self.input("online"))
                self.assertEqual(result.status, "error")
                self.assertEqual(result.execution["code"], "journal_invalid")
                self.assertEqual(journal.read_text(), payload)


if __name__ == "__main__":
    unittest.main()
