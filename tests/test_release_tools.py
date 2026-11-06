import hashlib
import contextlib
import io
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseTests(unittest.TestCase):
    def test_exact_file_set_and_tamper_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "example").write_bytes(b"data")
            (root / "SHA256SUMS").write_text(hashlib.sha256(b"data").hexdigest() + "  example\n")
            verifier = load("verify_release")
            self.assertEqual(verifier.verify(root)["status"], "PASS")
            (root / "extra").write_text("unlisted")
            self.assertEqual(verifier.verify(root)["status"], "FAIL")
            (root / "extra").unlink()
            (root / "example").write_text("tampered")
            self.assertEqual(verifier.verify(root)["status"], "FAIL")

    def test_two_builds_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            root.mkdir()
            (root / "example.txt").write_text("data")
            builder = load("build_release")
            a = builder.build(root, Path(directory) / "a.tar.gz")
            b = builder.build(root, Path(directory) / "b.tar.gz")
            self.assertEqual(a["sha256"], b["sha256"])

    def test_output_ancestor_alias_cannot_write_inside_source(self):
        with tempfile.TemporaryDirectory() as directory:
            # macOS /var is itself a link; model the canonical ROOT used by tools.
            root = Path(directory).resolve() / "release"
            root.mkdir()
            alias = Path(directory) / "alias"
            alias.symlink_to(root, target_is_directory=True)
            for name in ("run_tests", "offline_acceptance", "handoff_check"):
                module = load(name)
                module.ROOT = root
                with self.subTest(tool=name), patch("sys.argv", [name, "--output", str(alias / name)]):
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                        module.main()
                    self.assertEqual(result.exception.code, 2)
                    self.assertFalse((root / name).exists())
            builder = load("build_release")
            with self.assertRaises(ValueError):
                builder.build(root, alias / "release.tar.gz")
            self.assertFalse((root / "release.tar.gz").exists())
