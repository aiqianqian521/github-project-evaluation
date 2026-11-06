import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from discover import Cache


class CacheHardeningTests(unittest.TestCase):
    def test_predictable_temporary_symlink_cannot_overwrite_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "target"
            target.write_bytes(b"untouched")
            cache = Cache(root / "cache", fetch=lambda url: b"response")
            url = "https://api.github.com/repos/example/demo"
            key = hashlib.sha256(url.encode()).hexdigest()
            (cache.directory / (key + ".new")).symlink_to(target)
            cache.read(url)
            self.assertEqual(target.read_bytes(), b"untouched")
            self.assertEqual((cache.directory / (key + ".data")).read_bytes(), b"response")
            self.assertEqual((cache.directory / (key + ".data")).stat().st_mode & 0o777, 0o600)

    def test_shared_existing_cache_is_rejected_not_chmodded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shared"
            path.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                Cache(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
