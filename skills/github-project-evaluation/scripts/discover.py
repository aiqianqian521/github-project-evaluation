"""Bounded public-project discovery; preliminary signals, not source-code review."""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse, parse_qs
from urllib.request import HTTPRedirectHandler, Request, build_opener

from intent_policy import INTENTS, query_plan, role_hint


SITE = "https://kaiyuanbang.cn"
ENGLISH_SITE = "https://reporank.net"
GITSTAR_SITE = "https://gitstar.space"
API = "https://api.github.com"
SEARCH_SITES = {"kaiyuanbang": (SITE, "/zh-cn/search.html"),
                "reporank": (ENGLISH_SITE, "/en/search.html")}
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FINANCE = re.compile(r"交易|投资|回测|期货|加密|比特币|策略|金融|股票|外汇|量化投研|量化研究|trading|backtest|quantitative|market making|portfolio", re.I)
STRONG = re.compile(r"交易|回测|期货|加密|策略|trading|backtest|futures", re.I)
RESOURCE = re.compile(r"awesome|resources|interview|beginner|book|精选资源|面试|书稿|教程|指南|资源汇编", re.I)
RESEARCH = re.compile(r"因子|量化投研|量化研究|portfolio|factor|alpha", re.I)
SUMMARY_LIMIT = 512


def atomic_private_write(path, payload):
    # mkstemp never follows a predictable temporary symlink, even on shared caches.
    fd, name = tempfile.mkstemp(prefix=".cache-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def directional_terms(query):
    terms = re.findall(r"[a-z0-9]+", query.casefold())
    if (len(terms) == 3 and terms[1] == "to" and
            all(re.fullmatch(r"[a-z]+", term) for term in (terms[0], terms[2]))):
        return terms[0], terms[2]
    return None


def query_matches(text, query):
    lowered = text.casefold()
    terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", query.casefold())
    conversion = directional_terms(query)
    if conversion:
        origin, target = map(re.escape, conversion)
        directed = (r"(?<![a-z0-9])" + origin +
                    r"(?:[\s_-]+(?:and|or)[\s_-]+[a-z]+)?[\s_-]+(?:to|2)[\s_-]+" +
                    target + r"(?![a-z0-9])")
        compact = r"(?<![a-z0-9])" + origin + r"2" + target + r"(?![a-z0-9])"
        return bool(re.search(directed, lowered) or re.search(compact, lowered))
    terms = [term for term in terms if term not in {"to", "of", "for", "and", "the"}]
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", lowered)
    if len(terms) == 1 and re.fullmatch(r"[a-z0-9]+", terms[0]):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(terms[0]) + r"(?![a-z0-9])", normalized))
    if query.casefold() in lowered:
        return True
    if len(terms) < 2:
        return False
    return all((term in normalized if re.search(r"[\u4e00-\u9fff]", term) else
                re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", normalized))
               for term in terms)


def checked_url(url):
    if not isinstance(url, str) or any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError("invalid URL characters")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("non-public or invalid URL")
    if (parsed.netloc, parsed.path) in {
            ("kaiyuanbang.cn", "/zh-cn/search.html"),
            ("reporank.net", "/en/search.html"),
            ("gitstar.space", "/search")}:
        return url
    if parsed.netloc == "api.github.com" and (parsed.path == "/search/repositories" or
                                                  re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", parsed.path) or
                                                  re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/commits/[0-9a-f]{40,64}", parsed.path)):
        if parsed.path.startswith("/repos/") and any(
                segment in {".", ".."} for segment in parsed.path.split("/")[2:4]):
            raise ValueError("invalid repository path segment")
        if "/commits/" in parsed.path and parsed.query:
            raise ValueError("commit lookup cannot include query parameters")
        return url
    raise ValueError("network host or route not allowlisted")


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class Cache:
    def __init__(self, directory, offline=False, enabled=True, fetch=None):
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise ValueError("cache directory must not be a symbolic link")
        self.offline = offline
        self.enabled = enabled
        self.fetch = fetch or self._http
        if enabled:
            existed = self.directory.exists()
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            details = self.directory.stat()
            if details.st_uid != os.getuid() or (existed and details.st_mode & 0o077):
                raise ValueError("cache must be owned by caller with private 0700 permissions")
            self.directory.chmod(0o700)

    @staticmethod
    def _http(url):
        curl = shutil.which("curl")
        if not os.getenv("GITHUB_TOKEN") and curl:
            completed = subprocess.run(
                [curl, "--fail", "--silent", "--show-error", "--proto", "=https",
                 "--max-redirs", "0", "--max-filesize", "1500000", "--max-time", "15",
                 "--write-out", "\n__HTTP_STATUS__:%{http_code}",
                 "-A", "open-source-discovery/1.0 (+public metadata only)", url],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=17, check=False)
            payload, separator, raw_status = completed.stdout.rpartition(b"\n__HTTP_STATUS__:")
            if completed.returncode:
                if completed.returncode == 22 and separator and raw_status.isdigit() and raw_status != b"000":
                    raise OSError("HTTP_" + raw_status.decode("ascii"))
                category = {6: "DNS", 28: "timeout", 60: "TLS"}.get(completed.returncode, "network_error")
                raise OSError(category)
            if separator and raw_status.isdigit() and raw_status != b"200":
                raise OSError("transport_missing_http_status" if raw_status == b"000" else
                              "HTTP_" + raw_status.decode("ascii"))
            if not separator or not raw_status.isdigit():
                raise OSError("transport_missing_http_status")
            if len(payload) > 1_500_000:
                raise ValueError("page exceeds 1.5 MB")
            return payload
        headers = {"User-Agent": "open-source-discovery/1.0 (+public metadata only)",
                   "Accept": "application/vnd.github+json" if "api.github.com" in url else "text/html"}
        token = os.getenv("GITHUB_TOKEN") if url.startswith(API) else None
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(url, headers=headers)
        with build_opener(SafeRedirect()).open(request, timeout=12) as response:
            body = response.read(1_500_001)
            if len(body) > 1_500_000:
                raise ValueError("page exceeds 1.5 MB")
            return body

    def read(self, url, ttl_hours=24):
        checked_url(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        content = self.directory / (key + ".data")
        meta = self.directory / (key + ".json")
        if content.is_symlink() or meta.is_symlink():
            raise ValueError("cache entries must not be symbolic links")
        timestamp = time.time()
        if self.enabled and content.is_file() and meta.is_file():
            info = json.loads(meta.read_text(encoding="utf-8"))
            fetched_at = info.get("fetched_at") if isinstance(info, dict) else None
            if (type(fetched_at) not in (float, int) or not math.isfinite(fetched_at) or
                fetched_at > timestamp + 60 or not isinstance(info.get("sha256"), str)):
                raise ValueError("cache metadata invalid")
            if content.stat().st_size > 1_500_000:
                raise ValueError("cache entry exceeds 1.5 MB")
            payload = content.read_bytes()
            if hashlib.sha256(payload).hexdigest() == info.get("sha256"):
                age = max(0, timestamp - fetched_at)
                if self.offline or age < ttl_hours * 3600:
                    return payload, {"url": url, "sha256": info["sha256"],
                                     "fetched_at": fetched_at,
                                     "cache": "stale-offline" if age >= ttl_hours * 3600 else "hit",
                                     "origin": info.get("origin", "https"),
                                     "cache_trust": "local-unverified"}
        if self.offline:
            raise RuntimeError("offline cache miss: " + urlparse(url).netloc)
        payload = self.fetch(url)
        if not isinstance(payload, bytes) or len(payload) > 1_500_000:
            raise ValueError("invalid response payload")
        digest = hashlib.sha256(payload).hexdigest()
        if self.enabled:
            atomic_private_write(content, payload)
            atomic_private_write(meta, json.dumps({"fetched_at": timestamp, "sha256": digest,
                                                  "origin": "https"}).encode("utf-8"))
        return payload, {"url": url, "sha256": digest, "fetched_at": timestamp, "cache": "fresh", "origin": "https"}

    def cached(self, url, ttl_hours=12):
        checked_url(url)
        if not self.enabled:
            return False
        key = hashlib.sha256(url.encode()).hexdigest()
        content = self.directory / (key + ".data")
        meta = self.directory / (key + ".json")
        if content.is_symlink() or meta.is_symlink():
            return False
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            fetched_at = info["fetched_at"]
            return (type(fetched_at) in (float, int) and math.isfinite(fetched_at)
                    and fetched_at <= time.time() + 60 and content.is_file()
                    and content.stat().st_size <= 1_500_000
                    and hashlib.sha256(content.read_bytes()).hexdigest() == info["sha256"]
                    and (self.offline or 0 <= time.time() - fetched_at < ttl_hours * 3600))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def seed_snapshot(self, url, path):
        checked_url(url)
        if not self.enabled:
            raise ValueError("snapshot import requires cache")
        snapshot = Path(path)
        payload = snapshot.read_bytes()
        if not payload or len(payload) > 1_500_000:
            raise ValueError("invalid snapshot size")
        digest = hashlib.sha256(payload).hexdigest()
        key = hashlib.sha256(url.encode()).hexdigest()
        if (self.directory / (key + ".data")).is_symlink() or (
                self.directory / (key + ".json")).is_symlink():
            raise ValueError("cache entries must not be symbolic links")
        atomic_private_write(self.directory / (key + ".data"), payload)
        atomic_private_write(self.directory / (key + ".json"), json.dumps(
            {"fetched_at": snapshot.stat().st_mtime, "sha256": digest,
             "origin": "imported-direct-https-snapshot"}).encode("utf-8"))


class SearchHTML(HTMLParser):
    def __init__(self, site=SITE, search_path="/zh-cn/search.html"):
        super().__init__(convert_charrefs=True)
        self.site = site
        self.search_path = search_path
        self.rows = []
        self.page_links = set()
        self.article = None
        self.in_heading = 0
        self.in_paragraph = 0
        self.in_bdi = 0
        self.in_pagination = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "")
        if tag == "article" and "ornav-repo" in classes.split():
            self.article = {"title": "", "description": "", "fields": [],
                            "detail_url": urljoin(self.site, attributes.get("data-orank-target-url", "")),
                            "category": attributes.get("data-repo-category", ""),
                            "language": attributes.get("data-repo-language", "")}
        if tag == "nav" and "ornav-search-pagination" in classes.split():
            self.in_pagination = True
        if self.in_pagination and tag == "a":
            link = urljoin(self.site, html.unescape(attributes.get("href", "")))
            if urlparse(link).netloc == urlparse(self.site).netloc and urlparse(link).path == self.search_path:
                for value in parse_qs(urlparse(link).query).get("page", []):
                    if value.isdecimal():
                        self.page_links.add(int(value))
        if self.article is not None:
            if tag == "h3":
                self.in_heading += 1
            elif tag == "p" and not self.article["description"]:
                self.in_paragraph += 1
            elif tag == "bdi":
                self.in_bdi += 1

    def handle_endtag(self, tag):
        if self.article is not None:
            if tag == "h3":
                self.in_heading = max(0, self.in_heading - 1)
            elif tag == "p":
                self.in_paragraph = max(0, self.in_paragraph - 1)
            elif tag == "bdi":
                self.in_bdi = max(0, self.in_bdi - 1)
            elif tag == "article":
                fields = self.article.pop("fields")
                candidate = next((value for value in fields if REPO.fullmatch(value)), None)
                if candidate and not any(part in {".", ".."} for part in candidate.split("/")):
                    self.article["full_name"] = candidate
                    numbers = [int(value.replace(",", "")) for value in fields if re.fullmatch(r"[\d,]+", value)]
                    self.article["site_stars"] = numbers[0] if numbers else None
                    self.rows.append(self.article)
                self.article = None
        if tag == "nav":
            self.in_pagination = False

    def handle_data(self, data):
        if self.article is None:
            return
        value = data.strip()
        if not value:
            return
        if self.in_bdi:
            self.article["fields"].append(value)
        if self.in_heading:
            remaining = 256 - len(self.article["title"])
            if remaining > 0:
                self.article["title"] += (value + " ")[:remaining]
        elif self.in_paragraph:
            remaining = SUMMARY_LIMIT - len(self.article["description"])
            if remaining > 0:
                self.article["description"] += (value + " ")[:remaining]


class GitStarHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = {}

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attributes = dict(attrs)
        label = attributes.get("aria-label", "")
        target = attributes.get("href", "")
        prefix = "Open repository details for "
        if label.startswith(prefix):
            name = label[len(prefix):]
            if (REPO.fullmatch(name) and target == "/repo/" + name
                    and not any(part in {".", ".."} for part in name.split("/"))):
                self.rows[name.lower()] = {"full_name": name, "title": name,
                    "description": "", "language": "", "site_stars": None,
                    "github_url": "https://github.com/" + name,
                    "detail_url": GITSTAR_SITE + target, "sources": ["gitstar"],
                    "github_verified": False}


def error_category(error):
    if isinstance(error, HTTPError):
        return "HTTP_" + str(error.code)
    reason = str(error)
    if reason.startswith("HTTP_") and reason[5:].isdecimal():
        return reason
    if reason in {"DNS", "TLS", "timeout", "network_error"}:
        return reason
    if isinstance(error, (TimeoutError,)):
        return "timeout"
    return type(error).__name__


def score(row, query):
    identity = " ".join(((row.get("title") or "")[:256], row["full_name"]))
    text = identity + " " + (row.get("description") or "")[:SUMMARY_LIMIT]
    special = "量化" in query or "quant" in query.lower()
    relevant = bool(FINANCE.search(text)) if special else query_matches(text, query)
    if not relevant:
        return 0, "不符领域：限长摘要与查询条件未匹配"
    points = 30 + (25 if special and STRONG.search(text) else 0)
    if special and RESEARCH.search(text):
        points += 8
    if special and RESOURCE.search(text):
        points -= 25
    if query_matches(text, query):
        points += 10
    if not special and query_matches(identity, query):
        points += 15
    stars = row.get("github_stars") if row.get("github_stars") is not None else row.get("site_stars") or 0
    points += min(12, int(3 * math.log10(1 + stars)))
    if row.get("archived") is True or row.get("fork") is True:
        points -= 20
    pushed = row.get("pushed_at")
    if pushed:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days
            points += 8 if age <= 365 else -12
        except ValueError:
            pass
    if row.get("license") not in (None, "NOASSERTION"):
        points += 5
    return max(0, min(100, points)), "初筛：摘要相关性/热度/维护信号，未审代码"


def goal_hint(row, required_language=None, required_role=None, concept_any=None):
    reasons = []
    language = (row.get("language") or "").strip()
    if required_language and not language:
        reasons.append("language_unverified")
    elif required_language and language.casefold() != required_language.casefold():
        reasons.append("language_conflict")
    text = (row.get("full_name") or "") + " " + (row.get("description") or "")[:SUMMARY_LIMIT]
    if required_role == "library":
        if re.search(r"\b(benchmark|tutorial|awesome|resource list)\b", text, re.I):
            reasons.append("non_library_role_signal")
        elif not re.search(r"\b(library|libraries|lib)\b", text, re.I):
            reasons.append("library_role_unverified")
    if concept_any and not any(query_matches(text, concept) for concept in concept_any):
        reasons.append("concept_unverified")
    if "language_conflict" in reasons or "non_library_role_signal" in reasons:
        status = "REJECT_HINT"
    elif reasons:
        status = "UNKNOWN"
    else:
        status = "MATCH_HINT"
    return {"status": status, "reasons": reasons}


def collect_site(query, cache, max_pages, source="kaiyuanbang"):
    site, search_path = SEARCH_SITES[source]
    rows, provenance, errors = {}, [], []
    total = None
    page = 1
    expected_pages = 1
    while page <= expected_pages and page <= max_pages:
        url = site + search_path + "?" + urlencode(
            {"q": query, "updated": "365d", "sort": "stars_desc", "page": page})
        try:
            payload, info = cache.read(url)
            parser = SearchHTML(site, search_path)
            parser.feed(payload.decode("utf-8"))
            if page == 1:
                match = re.search(r"(?:搜索结果|Search Results?|Results)\s*<strong>([\d,]+)</strong>",
                                  payload.decode("utf-8"), re.I)
                total = int(match.group(1).replace(",", "")) if match else None
                if total is None and not parser.rows:
                    raise ValueError("result count and rows missing: site markup may have changed")
                expected_pages = max(parser.page_links, default=1)
                if total is None and not parser.page_links:
                    errors.append({"source": source, "reason": "pagination unverified"})
                if total is not None and parser.rows:
                    expected_pages = max(expected_pages, math.ceil(total / len(parser.rows)))
            if not parser.rows and (total or 0) > 0:
                raise ValueError("nonempty count but no parseable results")
            info.update({"page": page, "rows": len(parser.rows)})
            provenance.append(info)
            for row in parser.rows:
                key = row["full_name"].lower()
                if key not in rows:
                    row.update({"sources": [source],
                                "github_url": "https://github.com/" + row["full_name"]})
                    rows[key] = row
            if page < expected_pages:
                time.sleep(0.45 if not cache.offline else 0)
        except (ValueError, UnicodeError, OSError, URLError, HTTPError, RuntimeError, json.JSONDecodeError) as error:
            errors.append({"source": source, "page": page, "reason": error_category(error)})
        page += 1
    if expected_pages > max_pages:
        errors.append({"source": source, "reason": "page cap reached", "remaining": expected_pages - max_pages})
    if total is not None and len(rows) != total:
        errors.append({"source": source, "reason": "count mismatch", "reported": total,
                       "parsed_unique": len(rows)})
    return rows, provenance, errors


def collect_gitstar(query, cache):
    url = GITSTAR_SITE + "/search?" + urlencode({"q": query})
    try:
        payload, info = cache.read(url)
        parser = GitStarHTML()
        parser.feed(payload.decode("utf-8"))
        text = payload.decode("utf-8")
        if not parser.rows and "No repositories found for" not in text:
            raise ValueError("GitStar search markup unknown")
        return parser.rows, [{**info, "page": 1, "rows": len(parser.rows)}], [
            {"source": "gitstar", "reason": "catalog results only; pagination unverified"}]
    except (ValueError, UnicodeError, OSError, URLError, HTTPError, RuntimeError) as error:
        return {}, [], [{"source": "gitstar", "reason": error_category(error)}]


def collect_github(query, cache, max_pages, limit=3):
    rows, provenance, errors = {}, [], []
    expected_pages = 1
    new_pages = 0
    reported_total = None
    for page in range(1, min(max_pages, 34) + 1):
        if page > expected_pages:
            break
        url = API + "/search/repositories?" + urlencode(
            {"q": query, "sort": "stars", "order": "desc", "per_page": 30, "page": page})
        if new_pages >= limit and not cache.cached(url):
            break
        try:
            payload, info = cache.read(url, ttl_hours=12)
            if info["cache"] == "fresh":
                new_pages += 1
            data = json.loads(payload)
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("GitHub search schema changed")
            total = data.get("total_count")
            if type(total) is not int or total < 0:
                raise ValueError("GitHub search count invalid")
            for item in data["items"]:
                if not isinstance(item, dict):
                    raise ValueError("GitHub search item invalid")
                if (not isinstance(item.get("full_name"), str) or
                    not isinstance(item.get("description"), (str, type(None))) or
                    not isinstance(item.get("language"), (str, type(None))) or
                    not isinstance(item.get("pushed_at"), (str, type(None))) or
                    not isinstance(item.get("license"), (dict, type(None)))):
                    raise ValueError("GitHub search metadata invalid")
                stars = item.get("stargazers_count")
                if stars is not None and (type(stars) is not int or stars < 0):
                    raise ValueError("GitHub star count invalid")
                license_data = item.get("license") or {}
                if (not isinstance(license_data.get("spdx_id"), (str, type(None))) or
                    not isinstance(item.get("archived"), (bool, type(None))) or
                    not isinstance(item.get("fork"), (bool, type(None)))):
                    raise ValueError("GitHub search metadata invalid")
            if reported_total is None:
                reported_total = total
            elif reported_total != total:
                errors.append({"source": "github-api", "page": page, "reason": "count changed across pages",
                               "previous": reported_total, "reported": total})
            if total > 1000 and page == 1:
                errors.append({"source": "github-api", "reason": "1000-result search window",
                               "reported": total})
            expected_pages = min(34, max(1, math.ceil(total / 30)))
            if data.get("incomplete_results"):
                errors.append({"source": "github-api", "page": page, "reason": "incomplete_results"})
            provenance.append({**info, "page": page, "rows": len(data["items"]),
                               "total_count": data.get("total_count"), "incomplete_results": data.get("incomplete_results")})
            for item in data["items"]:
                full_name = item.get("full_name", "")
                if not REPO.fullmatch(full_name) or any(part in {".", ".."} for part in full_name.split("/")):
                    continue
                description = item.get("description") or ""
                rows[full_name.lower()] = {"full_name": full_name, "title": full_name,
                    "description": description[:SUMMARY_LIMIT], "description_truncated": len(description) > SUMMARY_LIMIT,
                    "language": item.get("language") or "",
                    "site_stars": None, "github_stars": item.get("stargazers_count"),
                    "pushed_at": item.get("pushed_at"), "archived": item.get("archived"),
                    "fork": item.get("fork"), "license": (item.get("license") or {}).get("spdx_id"),
                    "github_url": "https://github.com/" + full_name, "sources": ["github-api"],
                    "github_verified": info["cache"] == "fresh", "metadata_authority": "github",
                    "metadata_fetched_at": info["fetched_at"]}
            if len(data["items"]) < 30:
                break
            time.sleep(0.45 if not cache.offline else 0)
        except (ValueError, UnicodeError, OSError, URLError, HTTPError, RuntimeError, json.JSONDecodeError) as error:
            errors.append({"source": "github-api", "page": page, "reason": error_category(error)})
            break
    if expected_pages > len([item for item in provenance if "page" in item]):
        errors.append({"source": "github-api", "reason": "page cap reached",
                       "remaining": expected_pages - len([item for item in provenance if "page" in item])})
    if reported_total is not None and len(rows) != reported_total:
        errors.append({"source": "github-api", "reason": "count mismatch", "reported": reported_total,
                       "parsed_unique": len(rows)})
    return rows, provenance, errors


def github_repository_metadata(cache, repository):
    payload, info = cache.read(API + "/repos/" + quote(repository, safe="/"), ttl_hours=12)
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("full_name"), str):
        raise ValueError("GitHub repository metadata invalid")
    name = data["full_name"]
    if not REPO.fullmatch(name) or any(part in {".", ".."} for part in name.split("/")) or name.lower() != repository.lower():
        raise ValueError("repository identity mismatch")
    if (not isinstance(data.get("pushed_at"), (str, type(None))) or
            not isinstance(data.get("license"), (dict, type(None))) or
            not isinstance(data.get("description"), (str, type(None))) or
            not isinstance(data.get("language"), (str, type(None)))):
        raise ValueError("GitHub repository fields invalid")
    if (not isinstance((data.get("license") or {}).get("spdx_id"), (str, type(None))) or
            not isinstance(data.get("archived"), (bool, type(None))) or
            not isinstance(data.get("fork"), (bool, type(None)))):
        raise ValueError("GitHub repository fields invalid")
    stars = data.get("stargazers_count")
    if stars is not None and (type(stars) is not int or stars < 0):
        raise ValueError("GitHub star count invalid")
    return data, info


def prefer_github_summary(row, github_row):
    if "site_title" not in row and any(source in row["sources"] for source in ("kaiyuanbang", "reporank", "gitstar")):
        row["site_title"] = row.get("title", "")
        row["site_description"] = row.get("description", "")
    row.update({field: github_row[field] for field in
                ("full_name", "title", "description", "description_truncated", "language", "github_url")})
    row["metadata_authority"] = "github"
    if "metadata_fetched_at" in github_row:
        row["metadata_fetched_at"] = github_row["metadata_fetched_at"]


def collect_query(query, cache, source="both", max_pages=25, verify_top=8,
             required_language=None, required_role=None, concept_any=None):
    merged, provenance, errors = {}, [], []
    site_sources = (["kaiyuanbang", "reporank"] if source == "multi" else
                    ["kaiyuanbang"] if source in ("site", "both") else
                    ["reporank"] if source == "reporank" else [])
    coverage = {}
    for site_source in site_sources:
        observed_rows, observed, failures = collect_site(query, cache, max_pages, site_source)
        provenance.extend(observed)
        errors.extend(failures)
        coverage[site_source] = {"status": "PARTIAL" if failures else "COMPLETE",
                                 "pages": len(observed), "rows": len(observed_rows)}
        for key, row in observed_rows.items():
            if key in merged:
                merged[key]["sources"].extend(row["sources"])
            else:
                merged[key] = row
    if source in ("gitstar", "multi"):
        observed_rows, observed, failures = collect_gitstar(query, cache)
        provenance.extend(observed)
        errors.extend(failures)
        coverage["gitstar"] = {"status": "PARTIAL", "pages": len(observed),
                               "rows": len(observed_rows), "scope": "catalog-only"}
        for key, row in observed_rows.items():
            if key in merged:
                merged[key]["sources"].append("gitstar")
            else:
                merged[key] = row
    if source in ("github", "both", "multi"):
        observed_rows, observed, failures = collect_github(query, cache, max_pages)
        provenance.extend(observed)
        errors.extend(failures)
        coverage["github-api"] = {"status": "PARTIAL" if failures else "COMPLETE",
                                   "pages": len([item for item in observed if "page" in item]),
                                   "rows": len(observed_rows)}
        for key, row in observed_rows.items():
            if key in merged:
                prefer_github_summary(merged[key], row)
                merged[key].update({field: row.get(field) for field in
                    ("github_stars", "pushed_at", "archived", "fork", "license", "github_verified")})
                merged[key]["sources"].append("github-api")
            else:
                merged[key] = row
        if (failures and not observed_rows and REPO.fullmatch(query) and
                not any(part in {".", ".."} for part in query.split("/"))):
            try:
                data, info = github_repository_metadata(cache, query)
                name = data["full_name"]
                description = data.get("description") or ""
                direct_row = {"full_name": name, "title": name,
                    "description": description[:SUMMARY_LIMIT],
                    "description_truncated": len(description) > SUMMARY_LIMIT,
                    "language": data.get("language") or "", "site_stars": None,
                    "github_stars": data.get("stargazers_count"),
                    "pushed_at": data.get("pushed_at"), "archived": data.get("archived"),
                    "fork": data.get("fork"), "license": (data.get("license") or {}).get("spdx_id"),
                    "github_url": "https://github.com/" + name, "sources": ["github-direct"],
                    "github_verified": info["cache"] == "fresh", "metadata_authority": "github",
                    "metadata_fetched_at": info["fetched_at"]}
                if name.lower() in merged:
                    prefer_github_summary(merged[name.lower()], direct_row)
                    merged[name.lower()].update({key: value for key, value in direct_row.items()
                                                 if key not in {"sources", "title", "description", "description_truncated",
                                                                "language", "site_stars"}})
                    merged[name.lower()]["sources"].append("github-direct")
                else:
                    merged[name.lower()] = direct_row
                provenance.append({**info, "repository": name, "route": "exact-fallback"})
                coverage["github-direct"] = {"status": "PARTIAL", "pages": 1, "rows": 1,
                                              "scope": "exact-only"}
            except (ValueError, UnicodeError, OSError, URLError, HTTPError, RuntimeError, json.JSONDecodeError) as error:
                errors.append({"source": "github-direct", "repository": query,
                               "reason": error_category(error)})
                coverage["github-direct"] = {"status": "PARTIAL", "pages": 0, "rows": 0,
                                              "scope": "exact-only"}
    ranked = sorted(merged.values(), key=lambda row: (-score(row, query)[0],
                  -(row.get("github_stars") or row.get("site_stars") or 0), row["full_name"].lower()))
    verification_order = (sorted(ranked, key=lambda row: (
        goal_hint(row, required_language, required_role, concept_any)["status"] != "MATCH_HINT",
        -score(row, query)[0], row["full_name"].lower())) if required_language or required_role or concept_any else ranked)
    for row in verification_order[:verify_top]:
        if row.get("github_verified") or not REPO.fullmatch(row["full_name"]):
            continue
        try:
            data, info = github_repository_metadata(cache, row["full_name"])
            description = data.get("description") or ""
            prefer_github_summary(row, {"full_name": data["full_name"], "title": data["full_name"],
                "description": description[:SUMMARY_LIMIT], "description_truncated": len(description) > SUMMARY_LIMIT,
                "language": data.get("language") or "", "github_url": "https://github.com/" + data["full_name"]})
            row.update({"github_stars": data.get("stargazers_count"),
                        "pushed_at": data.get("pushed_at"), "archived": data.get("archived"),
                        "fork": data.get("fork"), "license": (data.get("license") or {}).get("spdx_id"),
                        "github_verified": info["cache"] == "fresh", "metadata_fetched_at": info["fetched_at"]})
            provenance.append({**info, "repository": row["full_name"]})
        except (ValueError, UnicodeError, OSError, URLError, HTTPError, RuntimeError, json.JSONDecodeError) as error:
            errors.append({"source": "github-verify", "repository": row["full_name"],
                           "reason": error_category(error)})
    for row in ranked:
        row["score"], row["rationale"] = score(row, query)
        row["review_state"] = "PRELIMINARY_ONLY"
    ranked.sort(key=lambda row: (-row["score"], -(row.get("github_stars") or row.get("site_stars") or 0),
                                 row["full_name"].lower()))
    cutoff = 40 if directional_terms(query) else 50
    if required_language or required_role or concept_any:
        for row in ranked:
            row["goal_hint"] = goal_hint(row, required_language, required_role, concept_any)
        eligible = [row for row in ranked if row["goal_hint"]["status"] == "MATCH_HINT"]
        shortlist = [row["full_name"] for row in eligible if row["score"] >= cutoff][:12]
        role_review_leads = [row["full_name"] for row in eligible if row["score"] < cutoff][:12]
    else:
        shortlist = [row["full_name"] for row in ranked if row["score"] >= cutoff][:12]
        role_review_leads = []
    return {"schema": "project-discovery.v1", "query": query, "source_mode": source,
            "goal_constraints": {"language": required_language, "role": required_role,
                                 "concept_any": concept_any or []},
            "role_review_leads": role_review_leads,
            "shortlist_min_score": cutoff,
            "status": "PARTIAL" if errors else "COMPLETE", "reported_count": next(
                (failure["reported"] for failure in errors if failure.get("reason") == "count mismatch"), None),
            "rows_seen": len(merged), "coverage": coverage, "provenance": provenance, "errors": errors,
            "candidates": ranked, "shortlist": shortlist,
            "acceptance": "NOT_REVIEWED"}


def discover(query, cache, source="both", max_pages=25, verify_top=8,
             required_language=None, required_role=None, concept_any=None, intent=None, literal=False):
    plan = query_plan(query, intent, literal)
    runs = [collect_query(term, cache, source, max_pages, verify_top,
                          required_language, required_role, concept_any) for term in plan["queries"]]
    if plan["intent"] is None:
        return {**runs[0], "query_plan": plan}
    merged = {}
    def authority(row):
        github = row.get("metadata_authority") == "github" or any(
            source in row["sources"] for source in ("github-api", "github-direct")) or row.get("github_verified")
        return (bool(github), row.get("metadata_fetched_at") or 0, bool(row.get("github_verified")))
    for term, run in zip(plan["queries"], runs):
        for candidate in run["candidates"]:
            key = candidate["full_name"].lower()
            previous = merged.get(key)
            matched = list(dict.fromkeys((previous or {}).get("matched_queries", []) + [term]))
            sources = list(dict.fromkeys((previous or {}).get("sources", []) + candidate["sources"]))
            if previous is None or authority(candidate) > authority(previous):
                merged[key] = dict(candidate)
                merged[key]["metadata_query"] = term
                if previous is not None:
                    for audit_key in ("site_title", "site_description"):
                        if audit_key in previous and audit_key not in merged[key]:
                            merged[key][audit_key] = previous[audit_key]
                    if authority(previous)[0] is False:
                        merged[key].setdefault("site_title", previous.get("title", ""))
                        merged[key].setdefault("site_description", previous.get("description", ""))
            merged[key].update({"matched_queries": matched, "sources": sources})
    for row in merged.values():
        # Re-score only the chosen authoritative metadata, never the old maximum.
        row["score"], row["rationale"] = max((score(row, term) for term in plan["queries"]), key=lambda item: item[0])
        row["metadata_selection"] = "github_then_observation_time_not_highest_score"
        row["intent_role_hint"] = role_hint(row, plan["intent"])
        if required_language or required_role or concept_any:
            row["goal_hint"] = goal_hint(row, required_language, required_role, concept_any)
    ranked = sorted(merged.values(), key=lambda row: (-row["score"], row["full_name"].lower()))
    eligible = [row for row in ranked if row["intent_role_hint"]["status"] == "MATCH_HINT" and
                (not (required_language or required_role or concept_any) or
                 row["goal_hint"]["status"] == "MATCH_HINT")]
    provenance = [{**item, "query": term} for term, run in zip(plan["queries"], runs)
                  for item in run["provenance"]]
    errors = [{**item, "query": term} for term, run in zip(plan["queries"], runs) for item in run["errors"]]
    coverage = {}
    for provider in dict.fromkeys(key for run in runs for key in run["coverage"]):
        pieces = [run["coverage"][provider] for run in runs if provider in run["coverage"]]
        coverage[provider] = {"status": "COMPLETE" if all(p["status"] == "COMPLETE" for p in pieces) else "PARTIAL",
                              "pages": sum(p["pages"] for p in pieces),
                              "rows": sum(p["rows"] for p in pieces), "rows_scope": "sum_before_cross_query_dedup"}
    return {**runs[0], "query": query, "query_plan": plan, "coverage": coverage,
            "query_runs": [{"query": term, "status": run["status"], "coverage": run["coverage"],
                            "rows_seen": run["rows_seen"], "reported_count": run["reported_count"]}
                           for term, run in zip(plan["queries"], runs)],
            "status": "PARTIAL" if errors or any(run["status"] != "COMPLETE" for run in runs) else "COMPLETE",
            "reported_count": None, "rows_seen": len(ranked), "provenance": provenance, "errors": errors,
            "candidates": ranked, "shortlist_min_score": 40,
            "shortlist": [row["full_name"] for row in eligible if row["score"] >= 40][:12],
            "role_review_leads": [row["full_name"] for row in eligible if row["score"] < 40][:12]}


def write_report(result, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "candidates.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 开源项目发现：初筛（非代码审计）", "", f"查询：{html.escape(result['query'])}；状态：{result['status']}；"
             f"去重项目：{result['rows_seen']}；来源：{result['source_mode']}；"
             f"候选分数门槛：{result.get('shortlist_min_score', 40 if directional_terms(result['query']) else 50)}"
             "（非验收分）。", "",
             "| 项目 | 来源 | Stars(来源) | 初筛分 | GitHub 核验 | 下一步 |", "| --- | --- | ---: | ---: | --- | --- |"]
    plan = result.get("query_plan", {})
    if plan.get("intent"):
        lines[2:2] = ["查询计划：" + html.escape(json.dumps(plan, ensure_ascii=False)),
                      "仅 MATCH_HINT 可自动入围；UNKNOWN/REJECT_HINT 保留于 candidates.json。角色提示不等于源码验证。", ""]
    for row in (r for r in result["candidates"] if r["full_name"] in result["shortlist"]):
        stars = row.get("github_stars") if row.get("github_stars") is not None else row.get("site_stars")
        origin = "GitHub" if row.get("github_stars") is not None else "开源榜/未知"
        safe_name = html.escape(row["full_name"])
        lines.append(f"| [{safe_name}]({row['github_url']}) | {', '.join(row['sources'])} | "
                     f"{stars if stars is not None else '?'} ({origin}) | {row['score']} | "
                     f"{'已核验元数据' if row.get('github_verified') else '待核验'} | 拉取冻结版本后二次评估 |")
    if any(result.get("goal_constraints", {}).values()):
        constraints = result["goal_constraints"]
        lines.extend(["", "## 显式目标约束", "", f"语言：{html.escape(constraints['language'] or '未指定')}；"
                      f"角色：{html.escape(constraints['role'] or '未指定')}；"
                      f"任一概念：{html.escape(', '.join(constraints['concept_any']) or '未指定')}。"
                      "仅按目录元数据过滤自动名单，无法确认源码实现；UNKNOWN 项未自动推荐。"])
        if not result["shortlist"]:
            lines.append("自动入围为空：不能用低分/角色不符项目填充推荐名额。")
        lines.extend(["", "### 待人工审阅的低分线索", ""])
        for name in result.get("role_review_leads", []):
            row = next(item for item in result["candidates"] if item["full_name"] == name)
            lines.append(f"- [{html.escape(name)}]({row['github_url']})：{row['score']} 分，"
                         f"{', '.join(row['sources'])}；仅元数据角色线索，不是自动推荐或业务验收。")
        if not result.get("role_review_leads"):
            lines.append("- 无；需扩展查询同义词、重新抓取或另找来源。")
    lines.extend(["", "## 数据缺口", ""])
    for issue in result["errors"]:
        lines.append("- " + html.escape(json.dumps(issue, ensure_ascii=False)))
    if not result["errors"]:
        lines.append("- 无抓取/分页缺口；代码质量、许可文本、回测防未来函数仍待二次评估。")
    lines.extend(["", "排名仅用于候选分流；Stars/站点解读不是业务有效性或安全结论。"])
    (output_dir / "SHORTLIST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Public repository discovery, not project approval")
    parser.add_argument("query")
    parser.add_argument("--source", choices=("site", "reporank", "gitstar", "github", "both", "multi"), default="both")
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--verify-top", type=int, default=8)
    parser.add_argument("--require-language", help="Exact GitHub primary-language hint (e.g. C, Python)")
    parser.add_argument("--require-role", choices=("library",), help="Metadata-only role hint")
    parser.add_argument("--intent", choices=tuple(INTENTS), help="Explicit task role and bounded synonym policy")
    parser.add_argument("--literal", action="store_true", help="Disable query expansion and automatic alias intent")
    parser.add_argument("--concept-any", action="append", default=[], help="One of up to eight goal terms")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--seed-dir", type=Path, help="Import captured page-N.html only when .query matches query")
    args = parser.parse_args()
    if not 0 < args.max_pages <= 25 or not 0 <= args.verify_top <= 20 or not args.query.strip():
        parser.error("query, page limit or verification count invalid")
    if args.require_language is not None and not re.fullmatch(r"[\w.+#-]{1,40}", args.require_language):
        parser.error("invalid language hint")
    if len(args.concept_any) > 8 or any(not re.fullmatch(r"[\w-]{2,40}", term) for term in args.concept_any):
        parser.error("invalid concept hint")
    if args.offline and args.no_cache:
        parser.error("offline mode requires cache")
    cache = Cache(args.cache_dir, offline=args.offline, enabled=not args.no_cache)
    if args.seed_dir:
        bound_query = (args.seed_dir / ".query").read_text(encoding="utf-8").strip() if (
            args.seed_dir / ".query").is_file() else None
        if args.no_cache or args.source in ("github", "reporank", "gitstar") or bound_query != args.query.strip():
            parser.error("snapshot query/source mismatch")
        for page_number in range(1, args.max_pages + 1):
            snapshot = args.seed_dir / f"page-{page_number}.html"
            if not snapshot.is_file():
                continue
            url = SITE + "/zh-cn/search.html?" + urlencode(
                {"q": args.query.strip(), "updated": "365d", "sort": "stars_desc", "page": page_number})
            cache.seed_snapshot(url, snapshot)
    result = discover(args.query.strip(), cache, args.source, args.max_pages, args.verify_top,
                      required_language=args.require_language, required_role=args.require_role,
                      concept_any=args.concept_any, intent=args.intent, literal=args.literal)
    write_report(result, args.output_dir)
    print(json.dumps({"status": result["status"], "rows": result["rows_seen"],
                      "shortlist": result["shortlist"], "errors": len(result["errors"])}))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
