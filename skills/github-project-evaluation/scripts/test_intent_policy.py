import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from discover import Cache, discover, write_report
from intent_policy import query_plan, role_hint


class IntentPolicyTests(unittest.TestCase):
    def test_exact_alias_plan_is_bounded_and_keeps_original(self):
        for query, intent in (("AI画画", "text-to-image"), ("运镜", "camera-motion"), ("逆向", "reverse-engineering")):
            plan = query_plan(query)
            self.assertEqual(plan["intent"], intent)
            self.assertEqual(plan["queries"][0], query)
            self.assertLessEqual(len(plan["queries"]), 3)
            self.assertEqual(len(set(plan["queries"])), len(plan["queries"]))

    def test_unknown_and_literal_are_not_silently_reinterpreted(self):
        self.assertEqual(query_plan("AI画画教程")["queries"], ["AI画画教程"])
        self.assertIsNone(query_plan("AI画画", literal=True)["intent"])
        self.assertEqual(query_plan("custom", "camera-motion", literal=True)["queries"], ["custom"])
        with self.assertRaises(ValueError):
            query_plan("x", "not-supported")

    def test_explicit_intent_does_not_drop_original_query(self):
        plan = query_plan("camera control", "camera-motion")
        self.assertEqual(plan["intent_origin"], "explicit")
        self.assertEqual(plan["queries"], ["camera control", "camera trajectory"])

    def test_holdout_role_labels_not_popularity(self):
        cases = [
            ("text-to-image", "lab/tiny", "Text-to-image diffusion model implementation", "MATCH_HINT"),
            ("text-to-image", "lab/awesome-art", "Curated text-to-image diffusion models", "REJECT_HINT"),
            ("text-to-image", "lab/tutorial", "Text-to-image generator tutorial", "REJECT_HINT"),
            ("text-to-image", "lab/caption", "Image-to-text and text-to-image model", "UNKNOWN"),
            ("text-to-image", "lab/unknown", "Beautiful pictures", "UNKNOWN"),
            ("text-to-image", "lab/chat", "AI suite with multi-model chats and text-to-image generation", "UNKNOWN"),
            ("camera-motion", "lab/viewcraft", "Camera pose conditioned video generation", "MATCH_HINT"),
            ("camera-motion", "lab/three", "Camera trajectory for novel view rendering", "MATCH_HINT"),
            ("camera-motion", "lab/obsbot", "Camera control for OBSBOT webcam", "REJECT_HINT"),
            ("camera-motion", "lab/mobile", "Camera recorder with camera pose", "REJECT_HINT"),
            ("camera-motion", "lab/control", "Camera control toolkit", "UNKNOWN"),
            ("camera-motion", "lab/scenes", "Camera pose refinement for 3D reconstruction", "UNKNOWN"),
            ("camera-motion", "lab/dataset", "Dataset of camera poses and 3D bounding boxes", "UNKNOWN"),
            ("camera-motion", "lab/human", "Multi-camera 3D human pose estimation", "UNKNOWN"),
            ("camera-motion", "lab/calibration", "Camera calibration with 3D trajectory rendering", "UNKNOWN"),
            ("reverse-engineering", "lab/local", "Decompiler for local Android APKs", "MATCH_HINT"),
            ("reverse-engineering", "lab/asm", "Static binary analysis and disassembly", "MATCH_HINT"),
            ("reverse-engineering", "lab/course", "Reverse engineering course", "REJECT_HINT"),
            ("reverse-engineering", "lab/steal", "Reverse engineering credential theft keylogger", "REJECT_HINT"),
            ("reverse-engineering", "lab/proxy", "HTTP reverse proxy", "UNKNOWN"),
            ("reverse-engineering", "lab/guide", "Comprehensive manual for reverse engineering", "REJECT_HINT"),
            ("reverse-engineering", "lab/Z0FCourse_ReverseEngineering", "Reverse engineering Windows", "REJECT_HINT"),
            ("reverse-engineering", "lab/links", "Thousands of resources related to reverse engineering", "REJECT_HINT"),
            ("reverse-engineering", "lab/router-skill", "Reverse engineering skill router", "UNKNOWN"),
            ("reverse-engineering", "lab/decomp", "SWF decompiler extracts images and other resources", "MATCH_HINT"),
        ]
        for intent, name, description, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(role_hint({"full_name": name, "description": description,
                                            "github_stars": 1_000_000}, intent)["status"], expected)

    def test_real_collect_path_expands_chinese_dedups_and_preserves_provenance(self):
        requested = []
        def fetch(url):
            term = parse_qs(urlparse(url).query)["q"][0]
            requested.append(term)
            return json.dumps({"total_count": 2, "incomplete_results": False, "items": [
                {"full_name": "lab/tiny", "description": "Text-to-image diffusion model", "stargazers_count": 10},
                {"full_name": "lab/awesome", "description": "Awesome text-to-image diffusion models", "stargazers_count": 900_000}]}).encode()
        with tempfile.TemporaryDirectory() as temporary:
            result = discover("AI画画", Cache(Path(temporary) / "cache", fetch=fetch), source="github", max_pages=1, verify_top=0)
            self.assertEqual(requested, ["AI画画", "text-to-image"])
            self.assertEqual(result["rows_seen"], 2)
            self.assertEqual(result["shortlist"], ["lab/tiny"])
            self.assertEqual(result["candidates"][0]["full_name"], "lab/awesome")
            self.assertEqual(result["candidates"][0]["intent_role_hint"]["status"], "REJECT_HINT")
            self.assertEqual(result["candidates"][0]["matched_queries"], requested)
            self.assertEqual({item["query"] for item in result["provenance"]}, set(requested))
            self.assertEqual(len(result["query_runs"]), 2)
            self.assertEqual(result["acceptance"], "NOT_REVIEWED")
            write_report(result, Path(temporary) / "report")
            self.assertIn("text-to-image", (Path(temporary) / "report/SHORTLIST.md").read_text())

    def test_expanded_provider_failure_cannot_be_hidden_by_other_query(self):
        def fetch(url):
            if parse_qs(urlparse(url).query)["q"][0] == "text-to-image":
                raise OSError("HTTP_403")
            return json.dumps({"total_count": 0, "incomplete_results": False, "items": []}).encode()
        with tempfile.TemporaryDirectory() as temporary:
            result = discover("AI画画", Cache(Path(temporary) / "cache", fetch=fetch), source="github", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["errors"][0]["query"], "text-to-image")
        self.assertEqual(result["errors"][0]["reason"], "HTTP_403")
        self.assertEqual(result["coverage"]["github-api"]["status"], "PARTIAL")

    def test_literal_mode_has_one_request_and_no_intent_filter(self):
        requested = []
        def fetch(url):
            requested.append(url)
            return b'{"total_count":0,"incomplete_results":false,"items":[]}'
        with tempfile.TemporaryDirectory() as temporary:
            result = discover("AI画画", Cache(Path(temporary) / "cache", fetch=fetch), source="github", verify_top=0, literal=True)
        self.assertEqual(len(requested), 1)
        self.assertIsNone(result["query_plan"]["intent"])

    def test_cross_query_authoritative_github_summary_overrides_higher_score_mirror(self):
        stale = {"full_name": "lab/conflict", "title": "Text-to-image", "description": "Text-to-image diffusion model",
                 "sources": ["kaiyuanbang"], "github_url": "https://github.com/lab/conflict", "score": 99,
                 "github_stars": None, "site_stars": 900_000, "language": "Python"}
        fresh = {**stale, "title": "lab/conflict", "description": "Image-to-text captioning only",
                 "sources": ["github-api"], "score": 0, "github_stars": 0, "github_verified": True,
                 "metadata_authority": "github", "metadata_fetched_at": 200}
        def result(row):
            return {"schema": "project-discovery.v1", "candidates": [row], "status": "COMPLETE", "rows_seen": 1,
                    "provenance": [], "errors": [], "coverage": {}, "reported_count": None, "shortlist": [],
                    "source_mode": "multi", "acceptance": "NOT_REVIEWED"}
        with patch("discover.collect_query", side_effect=[result(stale), result(fresh)]):
            actual = discover("AI画画", None)
        observed = actual["candidates"][0]
        self.assertEqual(observed["description"], fresh["description"])
        self.assertEqual(observed["score"], 0)
        self.assertEqual(observed["github_stars"], 0)
        self.assertEqual(observed["site_description"], stale["description"])
        self.assertEqual(actual["shortlist"], [])
        self.assertEqual(observed["intent_role_hint"]["status"], "UNKNOWN")

    def test_cross_query_newer_github_metadata_wins_not_stale_stars(self):
        requested = []
        def fetch(url):
            query = parse_qs(urlparse(url).query)["q"][0]
            requested.append(query)
            return json.dumps({"total_count": 1, "incomplete_results": False, "items": [{
                "full_name": "lab/change", "description": "Text-to-image diffusion model" if len(requested) == 1 else "Unrelated software",
                "stargazers_count": 999999 if len(requested) == 1 else 0}]}).encode()
        with tempfile.TemporaryDirectory() as temporary:
            actual = discover("AI画画", Cache(Path(temporary) / "cache", fetch=fetch), source="github", max_pages=1, verify_top=0)
        self.assertEqual(actual["candidates"][0]["description"], "Unrelated software")
        self.assertEqual(actual["candidates"][0]["score"], 0)
        self.assertEqual(actual["shortlist"], [])


if __name__ == "__main__":
    unittest.main()
