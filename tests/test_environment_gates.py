import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EnvironmentGates(unittest.TestCase):
    def test_missing_real_engine_blocks_full_profile_without_test_double(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "full"
            environment = {**os.environ, "LOOP_TEST_ENGINE_ROOT": str(Path(folder) / "missing"),
                           "LOOP_CONTRACT_SHA256": "0" * 64, "BWRAP_BINARY": ""}
            result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/run_tests.py"),
                                     "--profile", "full", "--output", str(output)],
                                    env=environment, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "BLOCK")
            self.assertFalse((output / "github-project-evaluation.log").exists())

    def test_production_adapter_has_no_fake_engine_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "skills/github-project-evaluation/scripts"),
                           "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run([sys.executable, "-B", "-c", "import loop_native_test_runner"],
                                    cwd=folder, env=environment, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"adapters", result.stderr)
