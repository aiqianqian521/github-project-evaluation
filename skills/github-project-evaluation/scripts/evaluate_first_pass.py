"""Bounded, read-only evidence inventory of a locally frozen Git checkout."""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from discover import API, Cache, error_category


REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
DOCUMENT_LIMIT = 256_000
JVM_PATH_LIMIT = 20_000
JVM_DEPTH_LIMIT = 16


def safe_file(root, relative):
    if relative is None:
        return None
    candidate = root / relative
    if any(parent.is_symlink() for parent in candidate.parents if parent != root and parent.is_relative_to(root)):
        return None
    if not candidate.is_file() or candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
        return None
    if not 0 < candidate.stat().st_size <= DOCUMENT_LIMIT:
        return None
    return candidate


def locate(root, prefixes, directories=("",)):
    for directory in directories:
        parent = root / directory
        if parent.is_symlink() or not parent.is_dir():
            continue
        for candidate in sorted(parent.iterdir(), key=lambda entry: entry.name.lower()):
            relative = candidate.relative_to(root)
            name = candidate.name.lower()
            if (name.startswith(prefixes) and name.rsplit(".", 1)[-1] not in
                    {"example", "sample", "template", "bak"} and safe_file(root, relative)):
                return relative
    return None


def inventory(root, relative):
    if relative is None:
        return None
    file = safe_file(root, relative)
    if file is None:
        return None
    content = file.read_bytes()
    return {"path": relative.as_posix(), "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content)}


def _git_binary():
    """Resolve git once instead of hardcoding /usr/bin/git (breaks on Homebrew, nix, Windows)."""
    return os.environ.get("GIT_BINARY") or shutil.which("git") or "git"


def _git_env(root):
    if sys.platform == "win32":
        return {"PATH": os.environ.get("PATH", ""), "HOME": str(root),
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"}
    return {"PATH": "/usr/bin:/bin", "HOME": str(root),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"}


def git_bytes(root, *arguments, input_data=None):
    result = subprocess.run([_git_binary(), "--no-replace-objects", "-c", "core.fsmonitor=false", "-C", str(root), *arguments], capture_output=True,
                            input=input_data, timeout=15, check=False, env=_git_env(root))
    return result.stdout if result.returncode == 0 else None


def git_value(root, *arguments):
    result = git_bytes(root, *arguments)
    return result.decode("utf-8", errors="strict").strip() if result is not None else None


def verify_tree_objects(root, commit, object_format):
    raw = git_bytes(root, "cat-file", "commit", commit)
    if raw is None or len(raw) > DOCUMENT_LIMIT or hashlib.new(
            object_format, f"commit {len(raw)}\0".encode() + raw).hexdigest() != commit:
        raise ValueError("commit object hash mismatch or size budget")
    first = raw.split(b"\n", 1)[0]
    if not re.fullmatch(rb"tree [0-9a-f]{40,64}", first):
        raise ValueError("invalid committed root tree")
    listing = git_value(root, "ls-tree", "-rtz", "--full-tree", commit)
    if listing is None:
        raise ValueError("cannot inspect committed tree objects")
    trees = {first[5:].decode("ascii")}
    records = list(filter(None, listing.split("\0")))
    if len(records) > 200_000:
        raise ValueError("tree path budget exceeded")
    for record in records:
        header, _ = record.split("\t", 1)
        _, kind, sha = header.split(" ")
        if kind == "tree":
            trees.add(sha)
    # Raw --batch (not --filters) verifies names/tree links before trusting ls-tree.
    ids = sorted(trees)
    payload = git_bytes(root, "cat-file", "--batch", input_data=("\n".join(ids) + "\n").encode())
    if payload is None or len(payload) > 67_108_864:
        raise ValueError("tree object byte budget exceeded or unavailable")
    position = 0
    for sha in ids:
        end = payload.find(b"\n", position)
        header = payload[position:end].decode("ascii").split(" ")
        if end < 0 or len(header) != 3 or header[:2] != [sha, "tree"] or not header[2].isdecimal():
            raise ValueError("invalid tree object response")
        size = int(header[2])
        position = end + 1
        content = payload[position:position + size]
        position += size
        if (len(content) != size or payload[position:position + 1] != b"\n" or hashlib.new(
                object_format, f"tree {size}\0".encode() + content).hexdigest() != sha):
            raise ValueError("tree object hash mismatch")
        position += 1
    if position != len(payload):
        raise ValueError("unexpected tree object bytes")


def committed_worktree(root, max_paths=100_000, byte_limit=268_435_456,
                       executable_mode_unverified=None):
    """Compare raw blobs, not git-status filters, stat caches or skip-worktree hints.

    executable_mode_unverified: optional list. When given (only by evaluate()) and
    the platform has no executable bit (win32), 100755 mismatches are recorded in
    the list instead of raising; direct callers without the list keep strict mode.
    """
    tree = git_value(root, "ls-tree", "-rz", "--full-tree", "HEAD")
    index = git_value(root, "ls-files", "--stage", "-z", "--cached")
    flags = git_value(root, "ls-files", "-t", "-z", "--cached")
    object_format = git_value(root, "rev-parse", "--show-object-format")
    if tree is None or index is None or flags is None or object_format not in {"sha1", "sha256"}:
        raise ValueError("cannot inspect committed source without filters")
    verify_tree_objects(root, git_value(root, "rev-parse", "--verify", "HEAD"), object_format)
    expected, indexed = {}, {}
    for record in filter(None, tree.split("\0")):
        header, path = record.split("\t", 1)
        mode, kind, sha = header.split(" ")
        if kind not in {"blob", "commit"}:
            raise ValueError("unsupported Git object in checkout")
        expected[path] = (mode, sha)
    for record in filter(None, index.split("\0")):
        header, path = record.split("\t", 1)
        mode, sha, stage = header.split(" ")
        if stage != "0":
            raise ValueError("unmerged index")
        indexed[path] = (mode, sha)
    if len(expected) > max_paths or expected != indexed:
        raise ValueError("source path budget exceeded or index differs from HEAD")
    sparse_missing = {record[2:] for record in flags.split("\0") if record.startswith("S ")}
    seen, total = set(), 0
    for parent, directories, files in os.walk(root, followlinks=False):
        if Path(parent) == root:
            directories[:] = [name for name in directories if name != ".git"]
            files = [name for name in files if name != ".git"]
        links = [name for name in directories if (Path(parent) / name).is_symlink()]
        directories[:] = [name for name in directories if name not in links]
        for name in files + links:
            file = Path(parent) / name
            path = file.relative_to(root).as_posix()
            if path not in expected:
                raise ValueError("checkout contains untracked or ignored materialized files")
            mode, sha = expected[path]
            details = file.lstat()
            if mode == "160000":
                raise ValueError("materialized submodule requires separate review")
            if stat.S_ISLNK(details.st_mode):
                if mode != "120000":
                    raise ValueError("source type differs from HEAD")
                # Git stores POSIX-style link targets. Windows returns the
                # extended \\?\ prefix and backslashes, so normalise before
                # hashing or every absolute symlink looks corrupted.
                target_text = os.readlink(file)
                if sys.platform == "win32":
                    if target_text.startswith("\\\\?\\"):
                        target_text = target_text[4:]
                    target_text = target_text.replace("\\", "/")
                payload = os.fsencode(target_text)
                size = len(payload)
            elif stat.S_ISREG(details.st_mode) and mode in {"100644", "100755"}:
                size = details.st_size
                payload = None
                if bool(details.st_mode & 0o111) != (mode == "100755"):
                    if executable_mode_unverified is not None and sys.platform == "win32":
                        # Windows has no executable bit; bytes are still verified below.
                        executable_mode_unverified.append(path)
                    else:
                        raise ValueError("source executable mode differs from HEAD")
            else:
                raise ValueError("unsupported source file type")
            total += size
            if total > byte_limit:
                raise ValueError("materialized source byte budget exceeded")
            digest = hashlib.new(object_format)
            digest.update(f"blob {size}\0".encode())
            if payload is not None:
                digest.update(payload)
            else:
                with file.open("rb") as stream:
                    remaining = size
                    while remaining:
                        chunk = stream.read(min(65_536, remaining))
                        if not chunk:
                            raise ValueError("source changed while hashing")
                        digest.update(chunk)
                        remaining -= len(chunk)
                    if stream.read(1):
                        raise ValueError("source grew while hashing")
            if digest.hexdigest() != sha:
                raise ValueError("source bytes differ from HEAD (including skip-worktree); filters are not executed")
            seen.add(path)
        for name in directories:
            if expected.get((Path(parent) / name).relative_to(root).as_posix(), (None,))[0] == "160000":
                raise ValueError("materialized submodule requires separate review")
    missing = set(expected) - seen - sparse_missing
    if missing:
        raise ValueError("tracked files missing outside sparse checkout")
    return set(expected)


def remote_identity(origin):
    if not origin:
        return None
    if origin.startswith("git@github.com:"):
        repository = origin.split(":", 1)[1]
    else:
        parsed = urlparse(origin)
        if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
            return None
        repository = parsed.path.lstrip("/")
    repository = repository.removesuffix(".git")
    return repository.lower() if REPOSITORY.fullmatch(repository) else None


def verify_upstream_commit(expected_repository, declared_remote, commit, fetch=None):
    result = {"status": "BLOCK", "reason": "declared_origin_mismatch_or_missing"}
    if declared_remote != expected_repository.lower():
        return result
    url = f"{API}/repos/{expected_repository}/commits/{commit}"
    try:
        payload, provenance = Cache(Path("."), enabled=False, fetch=fetch).read(url)
        response = json.loads(payload)
        if not isinstance(response, dict) or not isinstance(response.get("sha"), str):
            raise ValueError("invalid commit metadata")
        if response["sha"] != commit:
            return {"status": "BLOCK", "reason": "upstream_commit_mismatch", "url": url,
                    "response_sha256": provenance["sha256"]}
        return {"status": "VERIFIED", "url": url, "response_sha256": provenance["sha256"],
                "fetched_at": provenance["fetched_at"]}
    except (ValueError, UnicodeError, OSError, URLError, HTTPError, RuntimeError, json.JSONDecodeError) as error:
        return {"status": "BLOCK", "reason": error_category(error), "url": url}


def area(root, directory, suffixes=None):
    parent = root / directory
    if parent.is_symlink() or not parent.is_dir() or not parent.resolve().is_relative_to(root):
        return None
    for child in sorted(parent.iterdir(), key=lambda entry: entry.name.lower()):
        if child.is_symlink() or not child.resolve().is_relative_to(root):
            continue
        if suffixes is None and child.is_dir():
            return {"path": directory, "observation": "directory_present_only"}
        if child.is_file() and child.stat().st_size <= DOCUMENT_LIMIT and (
                suffixes is None or child.suffix.lower() in suffixes):
            observed = inventory(root, child.relative_to(root))
            if observed is not None:
                return observed
    return None


def package_scope(root, expected_repository, tracked_files):
    package_name = expected_repository.split("/", 1)[1]
    if (package_name in {".", ".."} or "pnpm-workspace.yaml" not in tracked_files or
            f"packages/{package_name}/package.json" not in tracked_files):
        return None
    scope = Path("packages") / package_name
    package = root / scope
    manifest = safe_file(root, scope / "package.json")
    if package.is_symlink() or not package.is_dir() or manifest is None:
        return None
    try:
        declared_name = json.loads(manifest.read_text(encoding="utf-8")).get("name")
    except (ValueError, UnicodeError):
        return None
    if declared_name not in {package_name} and (not isinstance(declared_name, str) or
                                                 not declared_name.endswith("/" + package_name)):
        return None
    return scope


def source_area(root, scope=None, expected_repository=None):
    for directory in ("src", "lib", "pkg", "cmd", "app"):
        observed = area(root, (scope / directory).as_posix() if scope else directory)
        if observed is not None:
            return observed
    observed = area(root, (scope / "modules").as_posix() if scope else "modules", {".py"})
    if observed is not None:
        return observed
    if scope is not None:
        return None
    for workspace in ("apps", "packages"):
        parent = root / workspace
        if parent.is_symlink() or not parent.is_dir():
            continue
        for project in sorted(parent.iterdir(), key=lambda entry: entry.name.lower()):
            if project.is_symlink() or not project.is_dir() or not project.resolve().is_relative_to(root):
                continue
            observed = area(root, f"{workspace}/{project.name}/src")
            if observed is not None:
                return observed
    for parent in sorted(root.iterdir(), key=lambda entry: entry.name.lower()):
        if (parent.name.startswith(".") or parent.name.lower() in
                {"tests", "test", "spec", "docs", "doc", "documentation", "examples", "assets"} or
                parent.is_symlink() or not parent.is_dir() or not
                parent.resolve().is_relative_to(root)):
            continue
        marker = parent / "__init__.py"
        if (marker.is_file() and not marker.is_symlink() and
                marker.resolve().is_relative_to(root) and marker.stat().st_size <= DOCUMENT_LIMIT):
            observed = area(root, parent.name, {".py"})
            if observed is not None:
                return observed
    if scope is None and expected_repository is not None:
        name = expected_repository.split("/", 1)[1]
        if name not in {".", ".."}:
            return inventory(root, Path(f"{name}.h"))
    return None


def test_area(root, directory):
    parent = root / directory
    if parent.is_symlink() or not parent.is_dir() or not parent.resolve().is_relative_to(root):
        return None
    for candidate in sorted(parent.iterdir(), key=lambda entry: entry.name.lower()):
        if candidate.is_symlink():
            continue
        options = [candidate]
        if candidate.is_dir() and (candidate.name.lower() in
                {"unit", "integration", "e2e", "functional", "specs"} or
                candidate.name.lower().startswith("test_")):
            options = sorted(candidate.iterdir(), key=lambda entry: entry.name.lower())
        for file in options:
            name = file.name.lower()
            if (not file.is_symlink() and file.is_file() and
                    (name.startswith("test_") or name.startswith("test-") or
                     ".test." in name or ".spec." in name or name.endswith("_test.go") or
                     (file.suffix == ".rs" and Path(directory).name == "tests") or
                     (name in {"test.c", "tests.c", "test.cc", "tests.cc", "test.cpp", "tests.cpp"}
                      and Path(directory).name in {"test", "tests"}))):
                observed = inventory(root, file.relative_to(root))
                if observed is not None:
                    return observed
    return None


def root_smoke_test(root, tracked_files):
    if not {"Makefile", "smoke.c"}.issubset(tracked_files):
        return None
    makefile = safe_file(root, Path("Makefile"))
    smoke = safe_file(root, Path("smoke.c"))
    if makefile is None or smoke is None:
        return None
    recipe = makefile.read_text(encoding="utf-8", errors="replace")
    target = re.search(r"(?m)^smoke\s*:[^\n]*$", recipe)
    if target is None:
        return None
    commands = recipe[target.end():]
    next_target = re.search(r"(?m)^[^\s#][^:\n]*:", commands)
    if next_target is not None:
        commands = commands[:next_target.start()]
    if re.search(r"(?m)^\s+\./(?:\$@|smoke)(?:\s|$)", commands):
        return inventory(root, Path("smoke.c"))
    return None


def manifest_file(root):
    pyproject = locate(root, ("pyproject.toml",))
    if pyproject is not None:
        try:
            metadata = tomllib.loads((root / pyproject).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            metadata = {}
        if isinstance(metadata, dict) and ("project" in metadata or "build-system" in metadata):
            return pyproject
    manifest = locate(root, ("setup.cfg", "setup.py", "package.json", "cargo.toml",
                             "go.mod", "pom.xml", "library.json", "requirements.txt"))
    if manifest is not None:
        return manifest
    cmake = safe_file(root, Path("CMakeLists.txt"))
    if cmake is not None:
        content = cmake.read_text(encoding="utf-8", errors="replace")
        if (re.search(r"(?m)^[ \t]*cmake_minimum_required[ \t]*\(", content) and
                re.search(r"(?m)^[ \t]*project[ \t]*\(", content)):
            return Path("CMakeLists.txt")
    return None


def gradle_inventory(root, tracked_files, path_limit=JVM_PATH_LIMIT, depth_limit=JVM_DEPTH_LIMIT):
    """Observe committed JVM conventions without evaluating Gradle settings/plugins."""
    paths = sorted(path for path in tracked_files if path)
    considered = paths[:path_limit]
    excluded = {"build", "vendor", "third_party", "node_modules", "examples", "fixtures", "docs"}
    build_names = {"build.gradle", "build.gradle.kts"}
    builds = [Path(path) for path in considered
              if Path(path).name in build_names and len(Path(path).parts) <= depth_limit
              and not excluded.intersection(Path(path).parts)
              and inventory(root, Path(path)) is not None]
    builds.sort(key=lambda path: (len(path.parts), path.as_posix()))
    modules = {path.parent.as_posix() for path in builds}
    result = {"manifest": inventory(root, builds[0]) if builds else None,
              "source": None, "tests": None,
              "coverage": {"status": "PARTIAL" if len(paths) > path_limit or any(
                  len(Path(path).parts) > depth_limit for path in considered) else "BOUNDED_SCAN_COMPLETE",
                  "tracked_paths": len(paths), "paths_examined": len(considered),
                  "path_limit": path_limit, "depth_limit": depth_limit,
                  "scope": "tracked materialized Gradle JVM conventions only; not build graph or test execution"}}
    for path in considered:
        relative = Path(path)
        if len(relative.parts) > depth_limit or excluded.intersection(relative.parts):
            continue
        match = re.fullmatch(r"(?:(.+)/)?src/(main|test)/(java|kotlin)/(.+\.(?:java|kt))", path)
        if match is None or (match[1] or ".") not in modules:
            continue
        label = "source" if match[2] == "main" else "tests"
        if label == "tests" and not re.fullmatch(r"(?:Test.+|.+(?:Test|Tests|TestCase))\.(?:java|kt)", relative.name):
            continue
        if result[label] is None:
            result[label] = inventory(root, relative)
    return result


def evaluate(root, expected_repository, discovery=None, verify_upstream=False, upstream_fetch=None):
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not REPOSITORY.fullmatch(expected_repository):
        raise ValueError("invalid checkout or expected owner/repo")
    commit = git_value(root, "rev-parse", "--verify", "HEAD")
    worktree = git_value(root, "rev-parse", "--show-toplevel")
    if not commit or not COMMIT.fullmatch(commit) or worktree != str(root):
        raise ValueError("a frozen Git checkout root is required")
    executable_unverified = [] if sys.platform == "win32" else None
    tracked_files = committed_worktree(root, executable_mode_unverified=executable_unverified)
    declared_remote = remote_identity(git_value(root, "remote", "get-url", "origin"))
    upstream = (verify_upstream_commit(expected_repository, declared_remote, commit, upstream_fetch)
                if verify_upstream else {"status": "NOT_REQUESTED"})
    scope = package_scope(root, expected_repository, tracked_files)
    jvm = gradle_inventory(root, tracked_files) if scope is None else None
    discovery_match = False
    if discovery is not None:
        source = Path(discovery)
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 2_000_000:
            raise ValueError("invalid discovery record")
        data = json.loads(source.read_text(encoding="utf-8"))
        if data.get("schema") != "project-discovery.v1" or not isinstance(data.get("candidates"), list):
            raise ValueError("invalid discovery schema")
        discovery_match = any(isinstance(row, dict) and
                              isinstance(row.get("full_name"), str) and
                              row["full_name"].lower() == expected_repository.lower()
                              for row in data["candidates"])
    test_directories = [(scope / name).as_posix() if scope else name
                        for name in ("tests", "test", "spec", "__tests__")]
    if scope is None:
        package_name = expected_repository.split("/", 1)[1]
        for module in (Path(package_name), Path("src") / package_name):
            if (not (root / module).is_symlink() and
                    f"{module.as_posix()}/__init__.py" in tracked_files):
                test_directories.append((module / "tests").as_posix())
    evidence = {
        "readme": inventory(root, locate(root, ("readme",))),
        "getting_started": inventory(root, locate(root,
            ("getting-started", "getting_started", "get-started", "quickstart", "quick-start", "start", "installation"),
            ("docs", "doc", "documentation"))),
        "license": inventory(root, locate(root, ("license", "licence", "copying"))),
        "manifest": inventory(root, scope / "package.json" if scope else manifest_file(root)) or (
            jvm["manifest"] if jvm else None),
        "architecture": inventory(root, locate(root, ("architecture", "design", "contributing"),
            ("docs", "doc", "documentation"))),
        "changelog": inventory(root, locate(root, ("changelog", "changes", "history", "release_notes", "release-notes"))),
        "contributing": inventory(root, locate(root, ("contributing",))),
        "security": inventory(root, locate(root, ("security.md",), (".github", ""))),
        "tests": next((found for directory in test_directories
                       if (found := test_area(root, directory)) is not None), None) or (
                           root_smoke_test(root, tracked_files) if scope is None else None) or (
                               jvm["tests"] if jvm else None),
        "ci": area(root, ".github/workflows", {".yml", ".yaml"}),
        "source": jvm["source"] if jvm and jvm["manifest"] else source_area(root, scope, expected_repository),
    }
    for label, observed in evidence.items():
        if observed is None:
            continue
        observed_path = observed["path"]
        if observed_path not in tracked_files and not (
                observed.get("observation") == "directory_present_only" and any(
                    path.startswith(observed_path + "/") for path in tracked_files)):
            evidence[label] = None
    weights = {"readme": 8, "getting_started": 12, "license": 15, "manifest": 10,
               "architecture": 10, "changelog": 4, "contributing": 3, "security": 3,
               "tests": 10, "ci": 5, "source": 10}
    identity_points = 10 if declared_remote == expected_repository.lower() else 0
    score = identity_points + sum(points for key, points in weights.items() if evidence[key])
    mandatory = ("readme", "license", "manifest", "tests", "source")
    missing = [key for key in mandatory if evidence[key] is None]
    if declared_remote != expected_repository.lower():
        missing.append("declared_origin_mismatch_or_missing")
    if discovery is not None and not discovery_match:
        missing.append("repository_absent_from_discovery")
    return {"schema": "project-first-pass.v1", "expected_repository": expected_repository.lower(),
            "package_scope": scope.as_posix() if scope else None,
            "jvm_inventory": jvm["coverage"] if jvm else {"status": "NOT_APPLICABLE_PACKAGE_SCOPE"},
            "local_commit": commit, "declared_origin": declared_remote,
            "upstream_commit_verified": upstream["status"] == "VERIFIED",
            "upstream_commit_verification": upstream,
            "identity_gate": "PASS" if upstream["status"] == "VERIFIED" else "BLOCK",
            "discovery_candidate_matched": discovery_match,
            "discovery_binding": "NOT_PROVIDED" if discovery is None else
                                 "MATCHED" if discovery_match else "ABSENT",
            "evidence_score": score, "max_score": 100, "scoring": {"declared_origin": identity_points,
                **{key: points if evidence[key] else 0 for key, points in weights.items()}},
            "executable_mode_unverified": (sorted(executable_unverified)
                                           if executable_unverified is not None else []),
            "executable_bit_note": ("platform has no executable bit; 100755 entries recorded as "
                                     "unverified, bytes still hash-verified"
                                     if executable_unverified else None),
            "evidence": evidence, "blocking_gaps": missing,
            "triage": "REVIEW_CANDIDATE" if score >= 70 and not missing else "HOLD",
            "goal_fit": "NOT_REVIEWED", "license_approved": False,
            "deployment_test_gate": "BLOCK", "code_executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--expected-repo", required=True)
    parser.add_argument("--discovery-file", type=Path)
    parser.add_argument("--verify-upstream", action="store_true", help="Check the frozen commit with GitHub's live commit API; no cache")
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        root = arguments.checkout.resolve(strict=True)
        output = arguments.output_dir.resolve()
        if output.is_relative_to(root) or arguments.output_dir.exists():
            raise ValueError("output must be a fresh directory outside the checkout")
        result = evaluate(root, arguments.expected_repo, arguments.discovery_file,
                          verify_upstream=arguments.verify_upstream)
        output.mkdir(parents=True)
        (output / "FIRST-PASS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        missing = ", ".join(result["blocking_gaps"]) or "none"
        (output / "FIRST-PASS.md").write_text(
            "# First-pass static inventory\n\n"
            f"Repository: `{result['expected_repository']}`; local commit: `{result['local_commit']}`.\n\n"
            f"Evidence completeness: **{result['evidence_score']}/100**; triage: **{result['triage']}**. "
            "This is not a functional or deployment-test approval.\n\n"
            f"Blocking evidence gaps: {missing}. Discovery binding: {result['discovery_binding']}. "
            f"Upstream identity gate: {result['identity_gate']} "
            f"({result['upstream_commit_verification']['status']}). License obligations, goal fit and "
            "business behavior need independent review.\n\n"
            "Read `FIRST-PASS.json` for file-level SHA evidence. Do not run project commands "
            "or treat README/CI presence as proof of correctness.\n")
        print(json.dumps({"score": result["evidence_score"], "triage": result["triage"],
                          "deployment_test_gate": result["deployment_test_gate"]}))
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
