"""Run local tests with honest counts and explicitly labeled Loop contract doubles."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "tools"))
from doctor import inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("portable", "full"), default="portable")
    parser.add_argument("--output", type=Path, required=True, help="fresh output directory outside source release")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error("output must be fresh and outside the release tree")
    output.mkdir(parents=True)
    capabilities = inspect()
    (output / "doctor.json").write_text(json.dumps(capabilities, indent=2))
    if args.profile == "full" and not capabilities["full_integration_ready"]:
        (output / "summary.json").write_text(json.dumps({"status": "BLOCK", "profile": "full",
                                                          "reason": "missing_pinned_external_dependencies"}, indent=2))
        print("BLOCK: full profile requires pinned real Loop and Linux bubblewrap; see doctor.json")
        return 2
    sys.path.insert(0, str(ROOT / "tests"))
    if args.profile == "portable":
        # Deliberate unit-only test double, never installed in production/runtime.
        from loop_contract_fixture import install
        install()
        os.environ.pop("BWRAP_BINARY", None)
    else:
        sys.path.insert(0, os.environ["LOOP_TEST_ENGINE_ROOT"])
    started = time.monotonic()
    results = []
    with tempfile.TemporaryDirectory(prefix="handoff-tests-", dir=output) as temporary:
        previous = Path.cwd()
        os.chdir(temporary)
        try:
            for relative in ("skills/github-project-evaluation/scripts", "tests"):
                directory = ROOT / relative
                sys.path.insert(0, str(directory))
                loader = unittest.TestLoader()
                suite = loader.discover(str(directory), "test_*.py", top_level_dir=str(directory))
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                    result = unittest.TextTestRunner(stream=buffer, verbosity=2).run(suite)
                name = directory.parent.name if relative != "tests" else "handoff"
                (output / (name + ".log")).write_text(buffer.getvalue())
                summary = {"suite": relative, "discovered": result.testsRun,
                           "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
                           "failures": len(result.failures), "errors": len(result.errors),
                           "skipped": len(result.skipped), "skip_reasons": [why for _, why in result.skipped],
                           "import_errors": loader.errors}
                results.append(summary)
                print(json.dumps(summary))
        finally:
            os.chdir(previous)
    errors = sum(item["errors"] + item["failures"] for item in results)
    skips = sum(item["skipped"] for item in results)
    # Portable expects only the three unavailable Linux integration tests to skip.
    expected_skips = 3 if args.profile == "portable" else 0
    status = "FAIL" if errors else "BLOCK" if skips != expected_skips else "PASS"
    summary = {"schema": "handoff.tests.v1", "profile": args.profile, "status": status,
               "seconds": round(time.monotonic() - started, 3), "suites": results,
               "loop_contract": "TEST_DOUBLE_UNIT_ONLY" if args.profile == "portable" else "EXTERNAL_PINNED",
               "full_loop_integration": "NOT_RUN" if args.profile == "portable" else "ADAPTER_CONTRACT_TESTED_NOT_SCHEDULER_E2E",
               "sandbox_integration": "NOT_RUN" if args.profile == "portable" else "LOCAL_PROBES_ONLY",
               "business_acceptance": "NOT_GRANTED"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"status": status, "summary": str(output / "summary.json")}))
    return 1 if status == "FAIL" else 2 if status == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
