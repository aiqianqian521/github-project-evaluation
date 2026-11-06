"""Run predeclared repository commands in a bounded, networkless Linux namespace."""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys

from evaluate_first_pass import evaluate
from validate_execution_evidence import check_evidence


IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_LOG = 1_000_000


def load_spec(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 40_000:
        raise ValueError("expected a bounded regular spec file")
    payload = path.read_bytes()
    spec = json.loads(payload)
    if not isinstance(spec, dict) or set(spec) != {"schema", "repository", "commit", "cases"} or (
            spec["schema"] != "project-tests.run.v1" or not isinstance(spec["repository"], str) or
            not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", spec["repository"]) or
            any(part in {".", ".."} for part in spec["repository"].split("/")) or
            not isinstance(spec["commit"], str) or not re.fullmatch(r"[0-9a-f]{40,64}", spec["commit"]) or
            not isinstance(spec["cases"], list) or not 1 <= len(spec["cases"]) <= 20):
        raise ValueError("invalid run spec")
    seen = set()
    for case in spec["cases"]:
        if (not isinstance(case, dict) or set(case) !=
                {"case_id", "argv", "expected_exit_code", "timeout_seconds", "memory_mib"} or
                not isinstance(case["case_id"], str) or not IDENTIFIER.fullmatch(case["case_id"]) or
                case["case_id"] in seen or not isinstance(case["argv"], list) or
                not 1 <= len(case["argv"]) <= 16 or any(
                    not isinstance(arg, str) or not arg or len(arg) > 1024 or
                    any((ord(char) < 32 and char != "\n") or ord(char) == 127
                        for char in arg) for arg in case["argv"]) or
                type(case["expected_exit_code"]) is not int or not 0 <= case["expected_exit_code"] <= 255 or
                type(case["timeout_seconds"]) is not int or not 1 <= case["timeout_seconds"] <= 30 or
                type(case["memory_mib"]) is not int or not 128 <= case["memory_mib"] <= 1024):
            raise ValueError("invalid or duplicate test case")
        seen.add(case["case_id"])
    return spec, hashlib.sha256(payload).hexdigest()


def limits(case):
    resource.setrlimit(resource.RLIMIT_CPU, (case["timeout_seconds"], case["timeout_seconds"] + 1))
    memory = case["memory_mib"] * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_LOG, MAX_LOG))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))


def artifact(path):
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def run_in_namespace(prefix, argv, case, stdout, stderr, wall_seconds):
    info_read, info_write = os.pipe()
    timed_out = False
    try:
        with stdout.open("xb") as out_stream, stderr.open("xb") as err_stream:
            process = subprocess.Popen(prefix[:1] + ["--info-fd", str(info_write)] + prefix[1:] + argv,
                                       stdout=out_stream, stderr=err_stream, start_new_session=True,
                                       pass_fds=(info_write,), preexec_fn=lambda: limits(case))
            os.close(info_write)
            info_write = -1
            try:
                process.wait(timeout=wall_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        raw_info = os.read(info_read, 8193)
    finally:
        if info_write >= 0:
            os.close(info_write)
        os.close(info_read)
    try:
        namespace = json.loads(raw_info) if len(raw_info) <= 8192 else None
        isolated = isinstance(namespace, dict) and all(
            type(namespace.get(key)) is int and namespace[key] > 0 for key in
            ("mnt-namespace", "net-namespace", "pid-namespace", "ipc-namespace", "uts-namespace"))
    except (ValueError, TypeError):
        isolated = False
    return process.returncode, timed_out, isolated, raw_info


def execute(spec_path, checkout, output_dir, bwrap_path, expected_spec_sha256, upstream_fetch=None):
    spec_path = Path(spec_path)
    checkout = Path(checkout).resolve(strict=True)
    output_dir = Path(output_dir).resolve()
    bwrap_path = Path(bwrap_path).resolve(strict=True)
    spec, spec_sha256 = load_spec(spec_path)
    if not SHA.fullmatch(expected_spec_sha256) or spec_sha256 != expected_spec_sha256:
        raise ValueError("run spec hash does not match the pinned value")
    if output_dir.exists() or output_dir.is_relative_to(checkout):
        raise ValueError("output must be a fresh directory outside checkout")
    if not bwrap_path.is_file() or not os.access(bwrap_path, os.X_OK):
        raise ValueError("bubblewrap executable unavailable")
    first_pass = evaluate(checkout, spec["repository"], verify_upstream=True,
                          upstream_fetch=upstream_fetch)
    if first_pass["local_commit"] != spec["commit"] or first_pass["identity_gate"] != "PASS":
        raise ValueError("checkout commit or live upstream identity gate BLOCK")
    output_dir.mkdir(mode=0o700)
    if sys.platform != "linux":
        report = {"schema": "project-tests.isolated-run.v1", "spec_sha256": spec_sha256,
                  "identity_gate": first_pass["identity_gate"], "execution_gate": "BLOCK",
                  "reason": "sandbox_preflight_failed", "detail": "Linux bubblewrap required",
                  "candidate_acceptance": "NOT_REVIEWED", "deployment_test_gate": "BLOCK"}
        (output_dir / "RUN.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    prefix = [str(bwrap_path), "--unshare-all", "--die-with-parent", "--new-session",
              "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
              "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
              "--ro-bind", str(checkout), "/workspace", "--size", "33554432", "--tmpfs", "/tmp",
              "--dir", "/proc", "--dir", "/dev", "--ro-bind", "/dev/null", "/dev/null",
              "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
              "--setenv", "TMPDIR", "/tmp", "--chdir", "/workspace"]
    probe = ("import os,socket; assert not os.path.exists('/home'); "
             "assert not os.path.exists('/etc'); assert not os.access('/workspace',os.W_OK); "
             "\ntry: socket.socket().connect(('1.1.1.1',80))\n"
             "except OSError as exc: assert exc.errno==101\n"
             "else: raise AssertionError('network reachable')\nprint('ISOLATION_OK')")
    probe_stdout = output_dir / "preflight.stdout"
    probe_stderr = output_dir / "preflight.stderr"
    try:
        probe_exit, probe_timeout, probe_isolated, probe_info = run_in_namespace(
            prefix, ["/usr/bin/python3", "-c", probe], {"timeout_seconds": 5, "memory_mib": 256},
            probe_stdout, probe_stderr, 7)
    except (OSError, ValueError, subprocess.SubprocessError):
        probe_exit, probe_timeout, probe_isolated, probe_info = 1, False, False, b"{}"
    probe_ok = (probe_exit == 0 and not probe_timeout and probe_isolated and
                probe_stdout.read_bytes() == b"ISOLATION_OK\n")
    (output_dir / "preflight.namespace.json").write_bytes(probe_info)
    if not probe_ok:
        report = {"schema": "project-tests.isolated-run.v1", "spec_sha256": spec_sha256,
                  "identity_gate": first_pass["identity_gate"], "execution_gate": "BLOCK",
                  "reason": "sandbox_preflight_failed", "candidate_acceptance": "NOT_REVIEWED",
                  "deployment_test_gate": "BLOCK"}
        (output_dir / "RUN.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    cases = []
    namespaces = {}
    failed_case = False
    for case in spec["cases"]:
        name = case["case_id"]
        stdout = output_dir / (name + ".stdout")
        stderr = output_dir / (name + ".stderr")
        exit_file = output_dir / (name + ".exit")
        observed_exit, timed_out, isolated, namespace_info = run_in_namespace(
            prefix, case["argv"], case, stdout, stderr, case["timeout_seconds"] + 2)
        (output_dir / (name + ".namespace.json")).write_bytes(namespace_info)
        namespaces[name] = isolated
        exit_code = observed_exit if observed_exit >= 0 else 128 - observed_exit
        exit_file.write_text(str(exit_code) + "\n", encoding="utf-8")
        cases.append({"case_id": name, "expected_exit_code": case["expected_exit_code"],
                      "artifacts": {"stdout": artifact(stdout), "stderr": artifact(stderr),
                                    "exit": artifact(exit_file)}})
        if timed_out or observed_exit < 0 or exit_code >= 128 or not isolated or exit_code != case["expected_exit_code"]:
            failed_case = True
            break
    manifest = {"schema": "project-tests.evidence.v2", "repository": spec["repository"],
                "commit": spec["commit"], "cases": cases}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    integrity = check_evidence(manifest, output_dir)
    report = {"schema": "project-tests.isolated-run.v1", "spec_sha256": spec_sha256,
              "identity_gate": first_pass["identity_gate"], "upstream_commit_verification":
              first_pass["upstream_commit_verification"], "execution_gate": "RECORDED" if (
                  not failed_case and all(namespaces.values()) and len(cases) == len(spec["cases"]) and
                  integrity["local_integrity"] == "INTACT_LOCAL") else "BLOCK",
              "artifact_integrity": integrity["local_integrity"],
              "namespace_info_sha256": {name: hashlib.sha256(
                  (output_dir / (name + ".namespace.json")).read_bytes()).hexdigest() for name in namespaces},
              "candidate_acceptance": "NOT_REVIEWED", "deployment_test_gate": "BLOCK"}
    (output_dir / "RUN.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bwrap", type=Path, required=True)
    parser.add_argument("--expected-spec-sha256", required=True)
    arguments = parser.parse_args()
    try:
        report = execute(arguments.spec, arguments.checkout, arguments.output_dir,
                         arguments.bwrap, arguments.expected_spec_sha256)
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"execution_gate": report["execution_gate"],
                      "deployment_test_gate": report["deployment_test_gate"]}))
    return 0 if report["execution_gate"] == "RECORDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
