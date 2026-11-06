import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover import Cache, GitStarHTML, SearchHTML, checked_url, collect_site, discover, score, write_report


def page(name, count, next_page=0):
    navigation = (f'<nav class="ornav-search-pagination"><a href="/zh-cn/search.html?page={next_page}">Next</a></nav>'
                  if next_page else "")
    return (f'<span>搜索结果 <strong>{count}</strong></span>'
        f'<article class="ornav-repo ready" data-orank-target-url="/zh-cn/repo/{name.replace("/", "-")}.html" '
        f'data-repo-category="finance" data-repo-language="Python">'
        '<h3><a>量化交易回测框架</a></h3><p>金融期货策略回测</p>'
        f'<div class="ornav-repo-meta"><bdi dir="ltr">{name}</bdi></div>'
        '<div class="ornav-repo-stats"><strong><bdi dir="ltr">8,000</bdi></strong></div>'
        f'</article>{navigation}').encode()


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_parser_extracts_real_site_markup_and_pagination(self):
        example = Path(os.environ.get("DISCOVERY_SITE_FIXTURE", str(
            Path(__file__).resolve().parents[1] / "references/fixtures/kaiyuanbang-quant-p1.html")))
        if not example.is_file():
            self.skipTest("captured public site snapshot not available")
        parser = SearchHTML()
        parser.feed(example.read_text(encoding="utf-8"))
        self.assertEqual(len(parser.rows), 20)
        self.assertEqual(parser.rows[1]["full_name"], "microsoft/qlib")
        self.assertEqual(parser.rows[1]["site_stars"], 49588)
        self.assertEqual(max(parser.page_links), 13)

    def test_mirror_and_api_deduplicate_three_sources(self):
        requested = []

        def fetch(url):
            requested.append(url)
            if "api.github.com/search" in url:
                return json.dumps({"total_count": 1, "incomplete_results": False, "items": [
                    {"full_name": "example/trader", "description": "quantitative trading backtest",
                     "stargazers_count": 50}]}).encode()
            if "gitstar.space" in url:
                return (b'<a href="/repo/example/trader" aria-label="Open repository details for '
                        b'example/trader">trader</a>')
            if "reporank.net" in url:
                return page("example/trader", 1).replace(b"/zh-cn/", b"/en/").replace(
                    "搜索结果".encode(), b"Search Results")
            return page("example/trader", 1)

        result = discover("trading", Cache(self.root / "cache", fetch=fetch),
                          source="multi", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["rows_seen"], 1)
        self.assertEqual(result["candidates"][0]["sources"],
                         ["kaiyuanbang", "reporank", "gitstar", "github-api"])
        self.assertEqual(len(requested), 4)
        self.assertEqual(set(result["coverage"]), {"kaiyuanbang", "reporank", "gitstar", "github-api"})
        self.assertEqual(result["coverage"]["gitstar"]["scope"], "catalog-only")

    def test_multi_source_failure_preserves_other_results_and_partial(self):
        def fetch(url):
            if "reporank.net" in url:
                raise OSError("HTTP_403")
            if "api.github.com" in url:
                raise OSError("HTTP_429")
            if "gitstar.space" in url:
                raise OSError("HTTP_403")
            return page("example/trader", 1)

        result = discover("trading", Cache(self.root / "cache", fetch=fetch),
                          source="multi", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["rows_seen"], 1)
        self.assertEqual(result["coverage"]["kaiyuanbang"]["status"], "COMPLETE")
        self.assertEqual(result["coverage"]["reporank"]["status"], "PARTIAL")
        self.assertEqual(result["coverage"]["github-api"]["status"], "PARTIAL")
        self.assertEqual(result["coverage"]["gitstar"]["status"], "PARTIAL")
        self.assertFalse(result["candidates"][0].get("github_verified", False))

    def test_mirror_unknown_pagination_cannot_claim_complete(self):
        payload = page("example/trader", 1).replace("搜索结果".encode(), b"Matches")
        result = discover("trading", Cache(self.root / "cache", fetch=lambda url: payload),
                          source="reporank", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(any(issue["reason"] == "pagination unverified" for issue in result["errors"]))

    def test_mirror_allowlist_and_redirect_target_restricted(self):
        self.assertEqual(checked_url("https://reporank.net/en/search.html?q=trading"),
                         "https://reporank.net/en/search.html?q=trading")
        for url in ("https://reporank.net.evil.org/en/search.html",
                    "https://reporank.net@evil.org/en/search.html",
                    "http://reporank.net/en/search.html", "https://reporank.net/admin"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                checked_url(url)

    def test_github_commit_lookup_is_sha_and_route_bound(self):
        commit = "a" * 40
        address = f"https://api.github.com/repos/example/demo/commits/{commit}"
        self.assertEqual(checked_url(address), address)
        for url in (address + "?per_page=100", address + "/more",
                    "https://api.github.com/repos/../demo/commits/" + commit,
                    "https://api.github.com/repos/example/demo/commits/main",
                    "https://api.github.com.evil.test/repos/example/demo/commits/" + commit):
            with self.subTest(url=url), self.assertRaises(ValueError):
                checked_url(url)

    def test_gitstar_page_extracts_only_strict_repo_links(self):
        parser = GitStarHTML()
        parser.feed('<a href="/repo/microsoft/qlib" aria-label="Open repository details for microsoft/qlib">'
                    'qlib</a><a href="/repo/../evil" aria-label="Open repository details for ../evil">x</a>'
                    '<a href="https://other.invalid/repo/a/b" aria-label="Open repository details for a/b">x</a>')
        self.assertEqual(list(parser.rows), ["microsoft/qlib"])
        self.assertEqual(parser.rows["microsoft/qlib"]["github_verified"], False)
        self.assertEqual(checked_url("https://gitstar.space/search?q=quant"),
                         "https://gitstar.space/search?q=quant")
        with self.assertRaises(ValueError):
            checked_url("https://gitstar.space/api/search?q=quant")

    def test_online_offline_same_content_with_provenance(self):
        def fetch(url):
            number = int(parse_qs(urlparse(url).query).get("page", [1])[0])
            return page("example/first" if number == 1 else "example/second", 2, 2 if number == 1 else 0)

        cache = Cache(self.root / "cache", fetch=fetch)
        online = discover("量化", cache, source="site", verify_top=0)
        offline = discover("量化", Cache(self.root / "cache", offline=True), source="site", verify_top=0)
        self.assertEqual(online["status"], "COMPLETE")
        self.assertEqual(online["rows_seen"], 2)
        self.assertEqual(online["shortlist"], offline["shortlist"])
        self.assertEqual(offline["provenance"][0]["cache"], "hit")
        write_report(offline, self.root / "out")
        self.assertIn("example/first", (self.root / "out/SHORTLIST.md").read_text())

    def test_offline_miss_reports_partial_not_fake_success(self):
        result = discover("量化", Cache(self.root / "cache", offline=True), source="site", verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["rows_seen"], 0)
        self.assertEqual(result["shortlist"], [])

    def test_reporank_results_zero_is_a_valid_empty_page(self):
        document = b'<html><span class="ornav-mini-stats">Results <strong>0</strong></span></html>'
        result = discover("python-hyper/h11", Cache(self.root / "cache", fetch=lambda url: document),
                          source="reporank", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["rows_seen"], 0)
        self.assertEqual(result["errors"], [])

    def test_rate_limit_and_forbidden_are_distinct_from_zero_results(self):
        for status in (403, 429):
            with self.subTest(status=status):
                cache = Cache(self.root / f"cache-{status}",
                    fetch=lambda url: (_ for _ in ()).throw(HTTPError(url, status, "blocked", {}, None)))
                result = discover("量化", cache, source="site", max_pages=1, verify_top=0)
                self.assertEqual(result["status"], "PARTIAL")
                self.assertEqual(result["errors"][0]["reason"], f"HTTP_{status}")

    def test_curl_http_status_is_not_hidden_by_exit_code(self):
        with patch("discover.shutil.which", return_value="/usr/bin/curl"), patch(
                "discover.subprocess.run", return_value=subprocess.CompletedProcess(
                    [], 22, stdout=b"\n__HTTP_STATUS__:403", stderr=b"")):
            with self.assertRaisesRegex(OSError, "HTTP_403"):
                Cache._http("https://kaiyuanbang.cn/zh-cn/search.html?q=test")

    def test_page_limit_and_missing_page_cannot_claim_full(self):
        cache = Cache(self.root / "cache", fetch=lambda url: page("example/only", 2, 2))
        result = discover("量化", cache, source="site", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(any(item["reason"] == "page cap reached" for item in result["errors"]))

    def test_changed_markup_is_not_reported_as_empty_search(self):
        result = discover("量化", Cache(self.root / "cache", fetch=lambda url: b"<html>challenge</html>"),
                          source="site", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["rows_seen"], 0)

    def test_out_of_domain_urls_fail_closed(self):
        for url in ("http://kaiyuanbang.cn/zh-cn/search.html",
                    "https://kaiyuanbang.cn.evil.org/zh-cn/search.html",
                    "https://kaiyuanbang.cn@evil.org/zh-cn/search.html",
                    "https://api.github.com/user", "https://api.github.com/repos/../..",
                    "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                checked_url(url)

    def test_poisoned_cache_is_not_used_offline(self):
        cache = Cache(self.root / "cache", fetch=lambda url: page("example/one", 1))
        collect_site("量化", cache, max_pages=1)
        data_file = next((self.root / "cache").glob("*.data"))
        data_file.write_bytes(b"poisoned")
        result = discover("量化", Cache(self.root / "cache", offline=True), source="site", verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["rows_seen"], 0)

    def test_semantic_filter_rejects_unrelated_quantification(self):
        self.assertEqual(score({"full_name": "author/infra", "title": "AI Infra 量化推导",
                                "description": "LLM 推理系统设计"}, "量化")[0], 0)

    def test_unrelated_domain_query_uses_generic_relevance_not_finance_gate(self):
        cache = Cache(self.root / "cache", fetch=lambda url: page("example/music", 1))
        result = discover("music", cache, source="site", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["shortlist"], ["example/music"])

    def test_late_keyword_in_large_summary_does_not_rank_unrelated_project(self):
        def fetch(url):
            return json.dumps({"total_count": 2, "incomplete_results": False, "items": [
                {"full_name": "example/spam", "description": "politics " * 6000 + "AI绘画",
                 "stargazers_count": 100000},
                {"full_name": "example/drawing", "description": "AI绘画生成工具",
                 "stargazers_count": 3000, "license": {"spdx_id": "MIT"},
                 "pushed_at": "2026-10-20T00:00:00Z"}]}).encode()

        result = discover("AI绘画", Cache(self.root / "cache", fetch=fetch),
                          source="github", max_pages=1, verify_top=0)
        self.assertEqual(result["shortlist"], ["example/drawing"])
        spam = next(row for row in result["candidates"] if row["full_name"] == "example/spam")
        self.assertEqual(spam["score"], 0)
        self.assertTrue(spam["description_truncated"])
        self.assertLessEqual(len(spam["description"]), 512)

    def test_hyphenated_video_query_matches_words_but_not_other_media(self):
        relevant = {"full_name": "example/video-gen", "title": "Video generation",
                    "description": "Text to video generation", "license": "MIT",
                    "pushed_at": "2026-10-20T00:00:00Z"}
        unrelated = {"full_name": "example/speech", "title": "Text to speech",
                     "description": "Audio generation", "github_stars": 100000}
        self.assertGreaterEqual(score(relevant, "text-to-video")[0], 50)
        self.assertEqual(score(unrelated, "text-to-video")[0], 0)
        self.assertEqual(score({"full_name": "example/drag", "title": "drag and drop",
                                "description": "UI library"}, "rag")[0], 0)

    def test_directional_conversion_requires_order_and_local_relation(self):
        for description in ("video downloader with speech-to-text for downloaded videos",
                            "video subtitles with AI dubbing and speech to text",
                            "text editor, as fun as a video game", "video to text and text to audio"):
            with self.subTest(description=description):
                self.assertEqual(score({"full_name": "example/irrelevant", "title": "Example",
                                        "description": description, "github_stars": 100000},
                                       "text-to-video")[0], 0)
        for description in ("text and image to video generation", "text-to-video diffusion",
                            "text2video synthesis"):
            with self.subTest(description=description):
                self.assertGreaterEqual(score({"full_name": "example/generator", "title": "Example",
                                               "description": description}, "text-to-video")[0], 40)

    def test_directional_low_popularity_research_stays_visible(self):
        payload = json.dumps({"total_count": 2, "incomplete_results": False, "items": [
            {"full_name": "example/tune-video", "description": "Text-to-video generation"},
            {"full_name": "example/downloader", "description": "video to text for AI agents"}]}).encode()
        result = discover("text-to-video", Cache(self.root / "cache", fetch=lambda url: payload),
                          source="github", max_pages=1, verify_top=0)
        self.assertEqual(result["shortlist"], ["example/tune-video"])
        self.assertEqual(result["shortlist_min_score"], 40)
        self.assertEqual(result["acceptance"], "NOT_REVIEWED")

    def test_explicit_c_library_goal_never_promotes_cpp_gui_or_benchmark(self):
        payload = json.dumps({"total_count": 5, "incomplete_results": False, "items": [
            {"full_name": "example/gui", "language": "C++",
             "description": "mathematical expression parser C++ GUI"},
            {"full_name": "example/benchmark", "language": "C",
             "description": "mathematical expression parser C benchmark"},
            {"full_name": "example/c-library", "language": "C",
             "description": "C library for parsing and evaluating mathematical expressions"},
            {"full_name": "example/unknown-language", "language": None,
             "description": "C library for parsing and evaluating mathematical expressions"},
            {"full_name": "example/parser", "language": "C",
             "description": "mathematical expression parser C"}]}).encode()
        result = discover("mathematical expression parser C",
                          Cache(self.root / "goal-cache", fetch=lambda url: payload),
                          source="github", max_pages=1, verify_top=0,
                          required_language="C", required_role="library")
        hints = {row["full_name"]: row["goal_hint"] for row in result["candidates"]}
        self.assertEqual(hints["example/gui"]["status"], "REJECT_HINT")
        self.assertEqual(hints["example/benchmark"]["status"], "REJECT_HINT")
        self.assertEqual(hints["example/unknown-language"]["status"], "UNKNOWN")
        self.assertEqual(hints["example/parser"]["status"], "UNKNOWN")
        self.assertEqual(result["shortlist"], [])
        self.assertEqual(result["role_review_leads"], ["example/c-library"])
        self.assertEqual(result["rows_seen"], 5)

    def test_goal_constrained_verification_spends_budget_on_matching_leads(self):
        requested = []
        page_html = ('搜索结果 <strong>2</strong>'
                     '<article class="ornav-repo ready" data-repo-language="C++">'
                     '<h3>mathematical expression parser C++ GUI</h3><p>GUI</p>'
                     '<bdi>example/gui</bdi></article>'
                     '<article class="ornav-repo ready" data-repo-language="C">'
                     '<h3>C library</h3><p>C library for parsing and evaluating mathematical expressions</p>'
                     '<bdi>example/c-library</bdi></article>').encode()

        def fetch(url):
            requested.append(url)
            if "kaiyuanbang.cn" in url:
                return page_html
            self.assertEqual(url, "https://api.github.com/repos/example/c-library")
            return json.dumps({"full_name": "example/c-library", "language": "C",
                               "stargazers_count": 1, "license": {"spdx_id": "MIT"}}).encode()

        result = discover("mathematical expression parser C", Cache(self.root / "verify-goal", fetch=fetch),
                          source="site", max_pages=1, verify_top=1,
                          required_language="C", required_role="library")
        self.assertIn("https://api.github.com/repos/example/c-library", requested)
        self.assertNotIn("https://api.github.com/repos/example/gui", requested)
        self.assertEqual(result["role_review_leads"], ["example/c-library"])

    def test_explicit_concepts_keep_math_library_without_recommending_regex_library(self):
        payload = json.dumps({"total_count": 2, "incomplete_results": False, "items": [
            {"full_name": "example/regex-lib", "language": "C",
             "description": "regular expression parsing library for C"},
            {"full_name": "example/math-lib", "language": "C",
             "description": "C library for parsing mathematical expressions"}]}).encode()
        result = discover("expression parser C library", Cache(self.root / "concept-goal", fetch=lambda url: payload),
                          source="github", max_pages=1, verify_top=0, required_language="C",
                          required_role="library", concept_any=["mathematical", "arithmetic"])
        hints = {row["full_name"]: row["goal_hint"] for row in result["candidates"]}
        self.assertEqual(hints["example/regex-lib"]["status"], "UNKNOWN")
        self.assertIn("concept_unverified", hints["example/regex-lib"]["reasons"])
        self.assertEqual(result["role_review_leads"], ["example/math-lib"])
        self.assertNotIn("example/regex-lib", result["shortlist"])

    def test_github_identity_and_source_merge(self):
        def fetch(url):
            if "/search/repositories" in url:
                return json.dumps({"total_count": 1, "incomplete_results": False, "items": [
                    {"full_name": "example/first", "description": "量化交易策略回测",
                     "stargazers_count": 9100, "html_url": "https://github.com/example/first",
                     "pushed_at": "2026-10-20T00:00:00Z", "archived": False, "fork": False,
                     "license": {"spdx_id": "MIT"}}]}).encode()
            if "/repos/" in url:
                return json.dumps({"full_name": "example/first", "stargazers_count": 9100}).encode()
            return page("example/first", 1)
        result = discover("量化", Cache(self.root / "cache", fetch=fetch),
                          source="both", max_pages=1, verify_top=1)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["rows_seen"], 1)
        self.assertEqual(result["candidates"][0]["sources"], ["kaiyuanbang", "github-api"])
        self.assertEqual(result["candidates"][0]["github_stars"], 9100)
        self.assertEqual(result["acceptance"], "NOT_REVIEWED")

    def test_github_search_summary_overrules_misleading_site_summary(self):
        def fetch(url):
            if "/search/repositories" in url:
                return json.dumps({"total_count": 1, "incomplete_results": False, "items": [
                    {"full_name": "example/utility", "description": "general-purpose utility",
                     "language": "C", "stargazers_count": 100}]}).encode()
            return page("example/utility", 1)

        result = discover("量化", Cache(self.root / "summary-merge", fetch=fetch),
                          source="both", max_pages=1, verify_top=0)
        row = result["candidates"][0]
        self.assertEqual(row["sources"], ["kaiyuanbang", "github-api"])
        self.assertEqual(row["site_description"].strip(), "金融期货策略回测")
        self.assertEqual(row["description"], "general-purpose utility")
        self.assertEqual(row["language"], "C")
        self.assertEqual(row["score"], 0)
        self.assertEqual(result["shortlist"], [])

    def test_github_verification_overrules_misleading_site_summary(self):
        def fetch(url):
            if "api.github.com" not in url:
                return page("example/utility", 1)
            return json.dumps({"full_name": "example/utility", "description": "general-purpose utility",
                               "language": "C", "stargazers_count": 100}).encode()

        result = discover("量化", Cache(self.root / "verify-summary", fetch=fetch),
                          source="site", max_pages=1, verify_top=1)
        row = result["candidates"][0]
        self.assertTrue(row["github_verified"])
        self.assertEqual(row["description"], "general-purpose utility")
        self.assertEqual(row["site_description"].strip(), "金融期货策略回测")
        self.assertEqual(row["score"], 0)
        self.assertEqual(result["shortlist"], [])

    def test_zero_github_stars_does_not_reuse_site_stars(self):
        row = {"full_name": "example/quant", "title": "example/quant",
               "description": "quantitative trading backtest", "github_stars": 0,
               "site_stars": 100000}
        without_site_stars = {**row, "site_stars": None}
        self.assertEqual(score(row, "quant"), score(without_site_stars, "quant"))

    def test_exact_repository_fallback_keeps_search_failure_partial(self):
        def fetch(url):
            if "/search/repositories" in url:
                raise OSError("timeout")
            self.assertEqual(url, "https://api.github.com/repos/example/demo")
            return json.dumps({"full_name": "example/demo", "description": "Demo package",
                               "stargazers_count": 120, "license": {"spdx_id": "MIT"}}).encode()

        cache = Cache(self.root / "fallback-cache", fetch=fetch)
        online = discover("example/demo", cache, source="github", max_pages=1, verify_top=0)
        self.assertEqual(online["status"], "PARTIAL")
        self.assertEqual(online["shortlist"], ["example/demo"])
        self.assertEqual(online["candidates"][0]["sources"], ["github-direct"])
        self.assertTrue(online["candidates"][0]["github_verified"])
        self.assertEqual(online["coverage"]["github-api"]["pages"], 0)
        self.assertEqual(online["coverage"]["github-direct"]["scope"], "exact-only")
        self.assertTrue(any(issue["reason"] == "timeout" for issue in online["errors"]))

        offline = discover("example/demo", Cache(self.root / "fallback-cache", offline=True),
                           source="github", max_pages=1, verify_top=0)
        self.assertEqual(offline["shortlist"], ["example/demo"])
        self.assertFalse(offline["candidates"][0]["github_verified"])
        self.assertEqual(offline["provenance"][-1]["cache_trust"], "local-unverified")
        self.assertEqual(offline["status"], "PARTIAL")

    def test_direct_fallback_cannot_verify_wrong_identity_or_unsafe_path(self):
        requested = []

        def fetch(url):
            requested.append(url)
            if "/search/repositories" in url:
                raise OSError("timeout")
            return json.dumps({"full_name": "other/demo"}).encode()

        for query in ("example/demo", "../.."):
            with self.subTest(query=query):
                requested.clear()
                result = discover(query, Cache(self.root / f"failure-{query.replace('/', '-')}", fetch=fetch),
                                  source="github", max_pages=1, verify_top=0)
                self.assertEqual(result["status"], "PARTIAL")
                self.assertEqual(result["candidates"], [])
                if query == "example/demo":
                    self.assertIn("ValueError", [item["reason"] for item in result["errors"]])
                    self.assertIn("https://api.github.com/repos/example/demo", requested)
                else:
                    self.assertFalse(any("/repos/" in url for url in requested))

    def test_exact_fallback_merges_existing_site_provenance(self):
        def fetch(url):
            if "/search/repositories" in url:
                raise OSError("timeout")
            if "/repos/" in url:
                return json.dumps({"full_name": "example/demo", "stargazers_count": 5}).encode()
            return page("example/demo", 1)

        result = discover("example/demo", Cache(self.root / "merge-cache", fetch=fetch),
                          source="both", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["rows_seen"], 1)
        self.assertEqual(result["candidates"][0]["sources"], ["kaiyuanbang", "github-direct"])
        self.assertEqual(result["candidates"][0]["site_stars"], 8000)
        self.assertTrue(result["candidates"][0]["github_verified"])

    def test_github_page_cap_is_never_complete(self):
        def fetch(url):
            return json.dumps({"total_count": 210, "incomplete_results": True,
                               "items": [{"full_name": "example/trader", "html_url": "https://evil.invalid/steal",
                                          "description": "quantitative trading backtest"}]}).encode()
        result = discover("quant", Cache(self.root / "cache", fetch=fetch),
                          source="github", max_pages=1, verify_top=0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["candidates"][0]["github_url"], "https://github.com/example/trader")
        self.assertTrue(any(error["reason"] == "page cap reached" for error in result["errors"]))

    def test_github_search_resumes_from_cached_pages_without_repeating_remote_fetch(self):
        fetched = []

        def fetch(url):
            page_number = int(parse_qs(urlparse(url).query)["page"][0])
            fetched.append(page_number)
            return json.dumps({"total_count": 120, "incomplete_results": False,
                "items": [{"full_name": f"example/trading-{page_number}-{index}",
                           "description": "algorithmic trading"} for index in range(30)]}).encode()

        cache = Cache(self.root / "cache", fetch=fetch)
        first = discover("trading", cache, "github", max_pages=3, verify_top=0)
        self.assertEqual(first["status"], "PARTIAL")
        self.assertEqual(fetched, [1, 2, 3])
        second = discover("trading", cache, "github", max_pages=4, verify_top=0)
        self.assertEqual(second["status"], "COMPLETE")
        self.assertEqual(second["rows_seen"], 120)
        self.assertEqual(fetched, [1, 2, 3, 4])
        third = discover("trading", cache, "github", max_pages=4, verify_top=0)
        self.assertEqual(third["status"], "COMPLETE")
        self.assertEqual(fetched, [1, 2, 3, 4])

    def test_snapshot_query_binding(self):
        cache = Cache(self.root / "cache", offline=True)
        cache.seed_snapshot("https://kaiyuanbang.cn/zh-cn/search.html?q=%E9%87%8F%E5%8C%96", self._snapshot())
        payload, info = cache.read("https://kaiyuanbang.cn/zh-cn/search.html?q=%E9%87%8F%E5%8C%96")
        self.assertIn(b"example/first", payload)
        self.assertEqual(info["origin"], "imported-direct-https-snapshot")

    def _snapshot(self):
        path = self.root / "snapshot.html"
        path.write_bytes(page("example/first", 1))
        return path


if __name__ == "__main__":
    unittest.main()
