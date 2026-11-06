"""Bounded local-only load and failure tests; never request public services."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover import Cache, discover


class DiscoveryStressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_local_large_page_deduplicates_and_caps_relevance(self):
        items = [
            {"full_name": f"example/drawing-{index}", "description": "AI绘画工具"}
            for index in range(900)
        ]
        items.append({"full_name": "example/drawing-0", "description": "AI绘画工具"})
        items.append({"full_name": "example/spam", "description": "unrelated " * 2000 + "AI绘画"})
        payload = json.dumps({"total_count": 902, "incomplete_results": False,
                              "items": items}, ensure_ascii=False).encode()
        self.assertLess(len(payload), 1_500_000)
        result = discover("AI绘画", Cache(self.root / "cache", fetch=lambda url: payload),
                          source="github", max_pages=1, verify_top=0)
        self.assertEqual(result["rows_seen"], 901)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotIn("example/spam", result["shortlist"])
        self.assertTrue(any(issue["reason"] == "count mismatch" for issue in result["errors"]))

    def test_oversized_or_invalid_page_fails_closed(self):
        for label, payload in (("oversized", b"x" * 1_500_001),
                               ("invalid-json", b'{"items": ['),
                               ("invalid-utf8", b"\xff")):
            with self.subTest(label=label):
                result = discover("RAG", Cache(self.root / label, fetch=lambda url: payload),
                                  source="github", max_pages=1, verify_top=0)
                self.assertEqual(result["status"], "PARTIAL")
                self.assertEqual(result["rows_seen"], 0)
                self.assertEqual(result["shortlist"], [])
                self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
