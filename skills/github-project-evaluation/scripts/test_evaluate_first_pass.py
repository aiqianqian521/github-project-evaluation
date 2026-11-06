import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_first_pass import evaluate, gradle_inventory, main, remote_identity


class FirstPassTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("remote", "add", "origin", "https://github.com/example/demo.git")

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.repo), *arguments], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def freeze(self):
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "frozen fixture")

    def write(self, name, content):
        file = self.repo / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)

    def test_complete_static_inventory_still_blocks_deployment(self):
        for name, content in (
            ("README.md", "Getting started"), ("docs/quickstart.md", "Run this"),
            ("LICENSE", "MIT License"), ("pyproject.toml", "[project]\nname='demo'"),
            ("docs/architecture.md", "Architecture"), ("CHANGELOG.md", "0.1"),
            ("CONTRIBUTING.md", "Contribute"), (".github/SECURITY.md", "Report"),
            (".github/workflows/ci.yml", "name: CI"), ("tests/test_demo.py", "assert True"),
            ("src/demo.py", "value = True")):
            self.write(name, content)
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence_score"], 100)
        self.assertEqual(result["triage"], "REVIEW_CANDIDATE")
        self.assertEqual(result["blocking_gaps"], [])
        self.assertEqual(result["goal_fit"], "NOT_REVIEWED")
        self.assertFalse(result["upstream_commit_verified"])
        self.assertEqual(result["deployment_test_gate"], "BLOCK")
        self.assertFalse(result["code_executed"])
        self.assertEqual(result["evidence"]["license"]["sha256"],
                         hashlib.sha256(b"MIT License").hexdigest())

    def test_missing_or_template_license_and_wrong_origin_block_shortlist(self):
        self.write("README.md", "Read me")
        self.write("LICENSE.example", "not a real grant")
        self.write("src/demo.py", "code")
        self.write("tests/test_demo.py", "assert True")
        self.git("remote", "set-url", "origin", "https://github.com/other/demo.git")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["triage"], "HOLD")
        self.assertIn("license", result["blocking_gaps"])
        self.assertIn("declared_origin_mismatch_or_missing", result["blocking_gaps"])

    def test_symlinked_readme_never_leaves_checkout(self):
        outside = self.root / "private.txt"
        outside.write_text("secret fixture")
        (self.repo / "README.md").symlink_to(outside)
        self.write("LICENSE", "MIT")
        self.freeze()
        self.assertIsNone(evaluate(self.repo, "example/demo")["evidence"]["readme"])

    def test_empty_test_initializer_does_not_hide_real_tests_and_package(self):
        self.write("README.md", "Read me")
        self.write("tests/__init__.py", "")
        self.write("tests/test_public.py", "assert True")
        self.write("demo/__init__.py", "")
        self.write("demo/main.py", "exports = True")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["tests"]["path"], "tests/test_public.py")
        self.assertEqual(result["evidence"]["source"]["path"], "demo/main.py")

    def test_monorepo_source_is_found_without_inventing_tests(self):
        self.write("README.md", "Read me")
        self.write("LICENSE", "MIT")
        self.write("package.json", '{"name":"workspace"}')
        self.write("apps/web/src/main.ts", "export const ready = true")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["source"]["path"], "apps/web/src/main.ts")
        self.assertIsNone(result["evidence"]["tests"])
        self.assertIn("tests", result["blocking_gaps"])
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_python_modules_are_source_not_arbitrary_assets(self):
        self.write("README.md", "Read me")
        self.write("modules/font.ttf", "asset")
        self.write("modules/processing.py", "def process(): return True")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["source"]["path"], "modules/processing.py")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_test_support_files_alone_do_not_count_as_tests(self):
        self.write("README.md", "Read me")
        self.write("tests/__init__.py", "support")
        self.write("tests/conftest.py", "fixtures")
        self.write("tests/helpers/data.py", "fixture")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["tests"])
        self.assertIn("tests", result["blocking_gaps"])

    def test_symlinked_monorepo_project_cannot_supply_source(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "src").mkdir()
        (outside / "src/main.ts").write_text("private")
        (self.repo / "apps").mkdir()
        (self.repo / "apps/web").symlink_to(outside, target_is_directory=True)
        self.write("README.md", "Read me")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["source"])

    def test_scoped_monorepo_uses_matching_package_not_unrelated_app(self):
        for name, content in (("pnpm-workspace.yaml", "packages:\n  - packages/*\n"),
                              ("README.md", "A demo"), ("LICENSE", "MIT"),
                              ("package.json", '{"name":"workspace"}'),
                              ("packages/demo/package.json", '{"name":"demo"}'),
                              ("packages/demo/src/index.ts", "export const ready = true"),
                              ("packages/demo/tests/unit/cache.test.ts", "assert(true)"),
                              ("apps/a/src/wrong.ts", "do not select this")):
            self.write(name, content)
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["package_scope"], "packages/demo")
        self.assertEqual(result["evidence"]["source"]["path"], "packages/demo/src/index.ts")
        self.assertEqual(result["evidence"]["tests"]["path"], "packages/demo/tests/unit/cache.test.ts")
        self.assertEqual(result["evidence"]["manifest"]["path"], "packages/demo/package.json")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_package_without_real_test_stays_blocked(self):
        self.write("pnpm-workspace.yaml", "packages:\n  - packages/*\n")
        self.write("packages/demo/package.json", '{"name":"demo"}')
        self.write("packages/demo/src/index.ts", "export const ready = true")
        self.write("packages/demo/tests/unit/__init__.py", "not a test")
        self.write("apps/web/tests/test_app.py", "assert True")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["tests"])
        self.assertIn("tests", result["blocking_gaps"])

    def test_tests_in_package_named_subdirectory_count(self):
        self.write("README.md", "A demo")
        self.write("tests/test_demo/test_signer.py", "def test_signature(): pass")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["tests"]["path"], "tests/test_demo/test_signer.py")

    def test_python_package_inline_tests_count_without_unrelated_package(self):
        self.write("README.md", "Package doc")
        self.write("demo/__init__.py", "from .parser import parse")
        self.write("demo/parser.py", "def parse(): pass")
        self.write("demo/tests/test_parser.py", "def test_parse(): pass")
        self.write("other/tests/test_else.py", "def test_else(): pass")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["tests"]["path"], "demo/tests/test_parser.py")

    def test_tool_only_pyproject_uses_tracked_setup_manifest(self):
        self.write("pyproject.toml", "[tool.test]\nstrict=true")
        self.write("setup.py", "from setuptools import setup\nsetup(name='demo')")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["manifest"]["path"], "setup.py")

    def test_tool_only_pyproject_is_not_install_manifest(self):
        self.write("pyproject.toml", "[tool.test]\nstrict=true")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["manifest"])

    def test_unrelated_inline_tests_do_not_count(self):
        self.write("README.md", "Project doc")
        self.write("other/__init__.py", "")
        self.write("other/tests/test_else.py", "def test_else(): pass")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["tests"])

    def test_header_only_c_project_has_scoped_source_tests_and_manifest(self):
        self.write("README.md", "Header-only JSON tokenizer")
        self.write("library.json", '{"name":"demo"}')
        self.write("demo.h", "int demo_parse(void);")
        self.write("test/tests.c", "int main(void) { return 0; }")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["manifest"]["path"], "library.json")
        self.assertEqual(result["evidence"]["source"]["path"], "demo.h")
        self.assertEqual(result["evidence"]["tests"]["path"], "test/tests.c")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_cmake_build_manifest_and_c_getting_started_are_inventory_only(self):
        self.write("CMakeLists.txt", "cmake_minimum_required(VERSION 3.16)\nproject(demo LANGUAGES C)\n")
        self.write("doc/get-started.md", "Getting started")
        self.write("RELEASE_NOTES.md", "Release history")
        self.write("src/demo.c", "int demo(void) { return 1; }")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["manifest"]["path"], "CMakeLists.txt")
        self.assertEqual(result["evidence"]["getting_started"]["path"], "doc/get-started.md")
        self.assertEqual(result["evidence"]["changelog"]["path"], "RELEASE_NOTES.md")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_comment_only_cmake_cannot_supply_manifest(self):
        self.write("CMakeLists.txt", "# cmake_minimum_required(VERSION 3)\n# project(demo)\n")
        self.freeze()
        self.assertIsNone(evaluate(self.repo, "example/demo")["evidence"]["manifest"])

    def test_root_smoke_test_requires_tracked_executable_recipe(self):
        self.write("demo.h", "double parse(const char *expression);")
        self.write("smoke.c", "int main(void) { return 0; }")
        self.write("Makefile", "smoke: smoke.c demo.c\n\t$(CC) -o $@ $^\n\t./$@\n")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["tests"]["path"], "smoke.c")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_unexecuted_smoke_example_cannot_count_as_test(self):
        self.write("smoke.c", "int main(void) { return 0; }")
        self.write("Makefile", "smoke: smoke.c\n\t$(CC) -o $@ $^\nexample: example.c\n\t./smoke\n")
        self.freeze()
        self.assertIsNone(evaluate(self.repo, "example/demo")["evidence"]["tests"])

    def test_unrelated_header_and_c_source_cannot_count_for_other_project(self):
        self.write("other.h", "int unrelated(void);")
        self.write("example/tests.c", "int main(void) { return 0; }")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["source"])
        self.assertIsNone(result["evidence"]["tests"])

    def test_missing_git_and_invalid_discovery_fail_closed(self):
        with self.assertRaises(ValueError):
            evaluate(self.root, "example/demo")
        self.write("README.md", "Read me")
        self.freeze()
        discovery = self.root / "discovery.json"
        discovery.write_text(json.dumps({"schema": "project-discovery.v1", "candidates": [
            {"full_name": "other/repo"}]}))
        result = evaluate(self.repo, "example/demo", discovery)
        self.assertIn("repository_absent_from_discovery", result["blocking_gaps"])

    def test_discovery_api_metadata_cannot_verify_local_commit(self):
        self.write("README.md", "Read me")
        self.freeze()
        discovery = self.root / "discovery.json"
        discovery.write_text(json.dumps({"schema": "project-discovery.v1", "candidates": [
            {"full_name": "example/demo", "github_verified": True}]}))
        result = evaluate(self.repo, "example/demo", discovery)
        self.assertEqual(result["discovery_binding"], "MATCHED")
        self.assertFalse(result["upstream_commit_verified"])
        self.assertEqual(result["identity_gate"], "BLOCK")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_live_commit_api_matches_local_head_without_approving_deployment(self):
        self.write("README.md", "Read me")
        self.freeze()
        commit = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        requested = []

        def fetch(url):
            requested.append(url)
            return json.dumps({"sha": commit}).encode()

        result = evaluate(self.repo, "example/demo", verify_upstream=True, upstream_fetch=fetch)
        self.assertEqual(requested, [f"https://api.github.com/repos/example/demo/commits/{commit}"])
        self.assertTrue(result["upstream_commit_verified"])
        self.assertEqual(result["upstream_commit_verification"]["status"], "VERIFIED")
        self.assertEqual(result["identity_gate"], "PASS")
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_wrong_commit_network_failure_and_wrong_origin_block_identity(self):
        self.write("README.md", "Read me")
        self.freeze()
        wrong_sha = "f" * 40
        mismatch = evaluate(self.repo, "example/demo", verify_upstream=True,
                            upstream_fetch=lambda url: json.dumps({"sha": wrong_sha}).encode())
        self.assertEqual(mismatch["upstream_commit_verification"]["reason"], "upstream_commit_mismatch")
        self.assertEqual(mismatch["identity_gate"], "BLOCK")

        def unavailable(url):
            raise OSError("HTTP_403")

        failure = evaluate(self.repo, "example/demo", verify_upstream=True, upstream_fetch=unavailable)
        self.assertEqual(failure["upstream_commit_verification"]["reason"], "HTTP_403")
        self.assertEqual(failure["identity_gate"], "BLOCK")
        self.git("remote", "set-url", "origin", "https://github.com/other/repo.git")
        refused = evaluate(self.repo, "example/demo", verify_upstream=True,
                           upstream_fetch=lambda url: self.fail("must not fetch on wrong origin"))
        self.assertEqual(refused["upstream_commit_verification"]["reason"],
                         "declared_origin_mismatch_or_missing")
        self.assertEqual(refused["identity_gate"], "BLOCK")

    def test_partial_exact_candidate_matches_without_approving_deployment(self):
        self.write("README.md", "Known repository")
        self.freeze()
        discovery = self.root / "partial.json"
        discovery.write_text(json.dumps({"schema": "project-discovery.v1", "status": "PARTIAL",
            "candidates": [{"full_name": "example/demo", "sources": ["github-direct"],
                            "github_verified": True}]}))
        result = evaluate(self.repo, "example/demo", discovery)
        self.assertEqual(result["discovery_binding"], "MATCHED")
        self.assertFalse(result["upstream_commit_verified"])
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_dirty_checkout_cannot_claim_frozen_commit_for_new_readme(self):
        self.write("README.md", "Original")
        self.freeze()
        self.write("README.md", "Injected undocumented capability")
        with self.assertRaisesRegex(ValueError, "source bytes differ from HEAD"):
            evaluate(self.repo, "example/demo")
        self.git("checkout", "--", "README.md")
        self.write("LICENSE", "MIT")
        with self.assertRaisesRegex(ValueError, "untracked"):
            evaluate(self.repo, "example/demo")

    def test_ignored_readme_cannot_score_against_head(self):
        self.write(".gitignore", "README.md\n")
        self.freeze()
        self.write("README.md", "Ignored but uncommitted")
        # r4 rejects ignored materialized inputs too; no unbound file is reviewed.
        with self.assertRaisesRegex(ValueError, "ignored materialized"):
            evaluate(self.repo, "example/demo")

    def test_output_within_checkout_rejected_and_no_git_hooks_run(self):
        self.write("README.md", "Read me")
        self.freeze()
        entry = self.repo / ".git/hooks/post-checkout"
        entry.write_text("exit 99")
        saved = sys.argv
        try:
            sys.argv = ["evaluate_first_pass.py", str(self.repo), "--expected-repo",
                        "example/demo", "--output-dir", str(self.repo / "results")]
            with self.assertRaises(SystemExit):
                main()
        finally:
            sys.argv = saved
        self.assertFalse((self.repo / "results").exists())

    def test_only_canonical_github_remote_is_recognized(self):
        self.assertEqual(remote_identity("git@github.com:Example/Demo.git"), "example/demo")
        self.assertIsNone(remote_identity("https://github.com.evil.test/example/demo.git"))
        self.assertIsNone(remote_identity("file:///home/user/repo"))

    def test_gradle_kts_apktool_multimodule_evidence_is_hashed_not_executed(self):
        files = {"build.gradle.kts": "throw RuntimeException(\"never execute\")",
                 "settings.gradle.kts": 'include(":brut.apktool:apktool-lib")',
                 "brut.apktool/apktool-cli/build.gradle.kts": "plugins {}",
                 "brut.apktool/apktool-cli/src/main/java/brut/apktool/Main.java": "class Main {}",
                 "brut.apktool/apktool-lib/build.gradle.kts": "plugins {}",
                 "brut.apktool/apktool-lib/src/test/java/brut/androlib/ResourceDirectoryTraversalTest.java": "class ResourceDirectoryTraversalTest {}"}
        for path, content in files.items():
            self.write(path, content)
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        for label, suffix in (("manifest", "build.gradle.kts"), ("source", "Main.java"),
                              ("tests", "ResourceDirectoryTraversalTest.java")):
            observed = result["evidence"][label]
            self.assertTrue(observed["path"].endswith(suffix))
            self.assertEqual(observed["sha256"], hashlib.sha256(files[observed["path"]].encode()).hexdigest())
            self.assertNotIn(label, result["blocking_gaps"])
        self.assertFalse(result["code_executed"])
        self.assertEqual(result["deployment_test_gate"], "BLOCK")

    def test_groovy_root_java_and_kotlin_conventions(self):
        for path in ("build.gradle", "src/main/kotlin/org/demo/Main.kt", "src/test/kotlin/org/demo/MainTest.kt"):
            self.write(path, "fixture")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertEqual(result["evidence"]["manifest"]["path"], "build.gradle")
        self.assertTrue(result["evidence"]["source"]["path"].endswith("Main.kt"))
        self.assertTrue(result["evidence"]["tests"]["path"].endswith("MainTest.kt"))

    def test_gradle_test_helpers_are_not_test_cases(self):
        self.write("module/build.gradle", "plugins {}")
        self.write("module/src/test/java/demo/Fixture.java", "class Fixture {}")
        self.freeze()
        self.assertIsNone(evaluate(self.repo, "example/demo")["evidence"]["tests"])

    def test_java_without_own_module_build_is_not_inferred_from_unrelated_build(self):
        self.write("module/build.gradle", "plugins {}")
        self.write("unrelated/src/main/java/Main.java", "class Main {}")
        self.write("unrelated/src/test/java/MainTest.java", "class MainTest {}")
        self.freeze()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["source"])
        self.assertIsNone(result["evidence"]["tests"])

    def test_gradle_untracked_and_symlinked_evidence_is_rejected(self):
        self.write("build.gradle.kts", "plugins {}")
        self.freeze()
        path = "src/main/java/demo/Main.java"
        self.write(path, "class Main {}")
        with self.assertRaises(ValueError):
            evaluate(self.repo, "example/demo")
        (self.repo / path).unlink()
        outside = self.root / "Main.java"
        outside.write_text("class Main {}")
        (self.repo / path).symlink_to(outside)
        self.freeze()
        self.assertIsNone(evaluate(self.repo, "example/demo")["evidence"]["source"])

    def test_gradle_directory_alias_cannot_supply_build_or_code(self):
        self.write("real/build.gradle", "plugins {}")
        self.write("real/src/main/java/Main.java", "class Main {}")
        (self.repo / "alias").symlink_to("real", target_is_directory=True)
        tracked = {"alias/build.gradle", "alias/src/main/java/Main.java"}
        observed = gradle_inventory(self.repo.resolve(), tracked)
        self.assertIsNone(observed["manifest"])
        self.assertIsNone(observed["source"])

    def test_gradle_bounded_inventory_reports_partial_and_excludes_assets(self):
        for path in ("build.gradle", "fixtures/src/test/java/FakeTest.java",
                     "very/deep/module/src/main/java/org/example/Main.java"):
            self.write(path, "fixture")
        paths = {"build.gradle", "fixtures/src/test/java/FakeTest.java",
                 "very/deep/module/src/main/java/org/example/Main.java"}
        limited = gradle_inventory(self.repo.resolve(), paths, path_limit=1)
        self.assertEqual(limited["coverage"]["status"], "PARTIAL")
        self.assertEqual(limited["coverage"]["paths_examined"], 1)
        self.assertIsNone(limited["tests"])
        deep = gradle_inventory(self.repo.resolve(), paths, depth_limit=5)
        self.assertEqual(deep["coverage"]["status"], "PARTIAL")
        self.assertIsNone(deep["source"])

    def test_static_inventory_never_invokes_configured_clean_filter(self):
        self.write("README.md", "frozen content")
        self.write(".gitattributes", "README.md filter=marker\n")
        self.freeze()
        marker = self.root / "filter-was-executed"
        self.git("config", "filter.marker.clean", f"/usr/bin/touch {marker}")
        self.git("config", "filter.marker.required", "true")
        os.utime(self.repo / "README.md", (1_700_000_000, 1_700_000_000))
        result = evaluate(self.repo, "example/demo")
        self.assertFalse(marker.exists())
        self.assertFalse(result["code_executed"])

    def test_skip_worktree_modified_materialized_source_cannot_bind_to_head(self):
        self.write("module/build.gradle.kts", "plugins {}")
        source = "module/src/main/java/Main.java"
        self.write(source, "class Main {}")
        self.freeze()
        self.git("update-index", "--skip-worktree", source)
        self.write(source, "class Evil {}")
        with self.assertRaisesRegex(ValueError, "source bytes differ from HEAD"):
            evaluate(self.repo, "example/demo", verify_upstream=True,
                     upstream_fetch=lambda url: b'{"sha":"unused"}')

    def test_assume_unchanged_and_staged_index_do_not_hide_changes(self):
        self.write("README.md", "before")
        self.freeze()
        self.git("update-index", "--assume-unchanged", "README.md")
        self.write("README.md", "after")
        with self.assertRaisesRegex(ValueError, "source bytes differ from HEAD"):
            evaluate(self.repo, "example/demo")
        self.git("update-index", "--no-assume-unchanged", "README.md")
        self.git("add", "README.md")
        with self.assertRaisesRegex(ValueError, "index differs from HEAD"):
            evaluate(self.repo, "example/demo")

    def test_sparse_missing_sources_are_not_misreported_as_materialized(self):
        self.write("README.md", "before")
        self.write("module/build.gradle.kts", "plugins {}")
        source = "module/src/main/java/Main.java"
        self.write(source, "class Main {}")
        self.freeze()
        self.git("update-index", "--skip-worktree", source)
        (self.repo / source).unlink()
        result = evaluate(self.repo, "example/demo")
        self.assertIsNone(result["evidence"]["source"])
        self.assertIn("source", result["blocking_gaps"])

    def test_byte_budget_and_non_sparse_missing_file_fail_closed(self):
        from evaluate_first_pass import committed_worktree
        self.write("README.md", "before")
        self.freeze()
        with self.assertRaisesRegex(ValueError, "byte budget"):
            committed_worktree(self.repo.resolve(), byte_limit=5)
        (self.repo / "README.md").unlink()
        with self.assertRaisesRegex(ValueError, "tracked files missing"):
            evaluate(self.repo, "example/demo")

    def test_git_replace_cannot_bind_replacement_tree_to_original_commit(self):
        self.write("README.md", "original")
        self.freeze()
        original = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"]).decode().strip()
        self.write("README.md", "replacement")
        self.freeze()
        replacement = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"]).decode().strip()
        self.git("update-ref", "HEAD", original)
        self.git("replace", original, replacement)
        self.git("read-tree", "--reset", "-u", "HEAD")
        with self.assertRaisesRegex(ValueError, "index differs from HEAD"):
            evaluate(self.repo, "example/demo", verify_upstream=True,
                     upstream_fetch=lambda url: json.dumps({"sha": original}).encode())

    def test_corrupt_loose_commit_object_cannot_claim_original_sha(self):
        self.write("README.md", "original")
        self.freeze()
        original = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"]).decode().strip()
        raw = subprocess.check_output(["git", "-C", str(self.repo), "cat-file", "commit", original])
        corrupted = raw + b"forged commit message\n"
        object_file = self.repo / ".git/objects" / original[:2] / original[2:]
        object_file.chmod(0o600)
        object_file.write_bytes(zlib.compress(f"commit {len(corrupted)}\0".encode() + corrupted))
        with self.assertRaises(ValueError):
            evaluate(self.repo, "example/demo")


if __name__ == "__main__":
    unittest.main()
