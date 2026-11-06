"""Offline adversarial contracts for discovery completeness and trust boundaries."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover import Cache, checked_url, discover


def site_page():
    return (
        '<span>搜索结果 <strong>1</strong></span>'
        '<article class="ornav-repo"><h3>量化交易回测框架</h3>'
        '<p>期货策略回测</p><bdi>example/trader</bdi></article>'
    ).encode("utf-8")


class AdversarialDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_site_without_count_or_pagination_must_not_claim_complete(self):
        requested = []

        def fetch(url):
            requested.append(url)
            page = int(parse_qs(urlparse(url).query)["page"][0])
            if page == 1:
                return site_page().replace('<span>搜索结果 <strong>1</strong></span>'.encode(), b"")
            return site_page().replace(b"example/trader", b"example/other")

        result = discover("量化", Cache(self.root / "cache", fetch=fetch),
                          source="site", max_pages=2, verify_top=0)
        self.assertEqual(len(requested), 1)
        self.assertEqual(result["rows_seen"], 1)
        self.assertEqual(result["status"], "PARTIAL", "no count or last-page evidence exists")

    def test_invalid_github_stars_cannot_crash_or_poison_site_result(self):
        def fetch(url):
            if urlparse(url).netloc == "api.github.com":
                return json.dumps({"total_count": 1, "incomplete_results": False, "items": [
                    {"full_name": "example/trader", "description": "量化交易回测",
                     "stargazers_count": -10}]}).encode()
            return site_page()

        result = discover("量化", Cache(self.root / "cache", fetch=fetch),
                          source="both", max_pages=1, verify_top=0)
        self.assertEqual(result["rows_seen"], 1)
        self.assertEqual(result["candidates"][0]["full_name"], "example/trader")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotEqual(result["candidates"][0].get("github_stars"), -10)

    def test_offline_cache_symlink_cannot_read_outside_cache(self):
        url = "https://kaiyuanbang.cn/zh-cn/search.html?q=quant"
        payload = b"private file outside the discovery cache"
        outside = self.root / "private.txt"
        outside.write_bytes(payload)
        cache_dir = self.root / "cache"
        cache = Cache(cache_dir, offline=True, fetch=lambda url: self.fail("network fetch"))
        key = hashlib.sha256(url.encode()).hexdigest()
        (cache_dir / (key + ".data")).symlink_to(outside)
        (cache_dir / (key + ".json")).write_text(json.dumps({
            "sha256": hashlib.sha256(payload).hexdigest(), "fetched_at": time.time()}), encoding="utf-8")

        with self.assertRaises(ValueError, msg="cache data symlink escapes the cache boundary"):
            cache.read(url)

    def test_cache_directory_symlink_cannot_change_target_permissions(self):
        outside = self.root / "unrelated"
        outside.mkdir(mode=0o750)
        link = self.root / "cache-alias"
        link.symlink_to(outside, target_is_directory=True)
        before = outside.stat().st_mode & 0o777
        with self.assertRaises(ValueError):
            Cache(link)
        self.assertEqual(outside.stat().st_mode & 0o777, before)

    def test_url_allowlist_rejects_control_characters_stripped_by_parser(self):
        url = "https://api.github.com/search/repositories\n?per_page=30"
        with self.assertRaises(ValueError, msg="do not authorize a different URL than the raw input"):
            checked_url(url)

    def test_curl_http_zero_is_transport_failure_not_fake_http_response(self):
        url = "https://api.github.com/search/repositories?q=test"
        failure = subprocess.CompletedProcess(["curl"], 28, b"\n__HTTP_STATUS__:000", b"")
        with patch("discover.shutil.which", return_value="/usr/bin/curl"), patch(
                "discover.subprocess.run", return_value=failure):
            with self.assertRaisesRegex(OSError, "^timeout$"):
                Cache._http(url)
        rejected = subprocess.CompletedProcess(["curl"], 22, b"\n__HTTP_STATUS__:429", b"")
        with patch("discover.shutil.which", return_value="/usr/bin/curl"), patch(
                "discover.subprocess.run", return_value=rejected):
            with self.assertRaisesRegex(OSError, "^HTTP_429$"):
                Cache._http(url)


if __name__ == "__main__":
    unittest.main()
