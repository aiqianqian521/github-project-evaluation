"""Sparse-first read-only source acquisition; never executes repository code.

Transient Git writes have sampled guards, NOT a filesystem quota. Only a clean
post-stop measurement within budget can be promoted to the requested destination.
"""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import argparse
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import subprocess
import tempfile
import time


PATTERNS = "\n".join(["*.md", "*.rst", "LICENSE*", "COPYING*", "NOTICE*", "*.py", "*.java",
                       "*.kt", "*.gradle", "*.kts", "*.properties", "*.toml", "*.yaml", "*.yml",
                       "requirements*.txt", "*.json", "*.cfg", "*.ini", "*.txt"]) + "\n"


def measure(root, max_files=20_000):
    size = count = 0
    for path in root.rglob("*"):
        try:
            details = path.lstat()
        except FileNotFoundError:
            # Git atomically renames temporary packs/locks while the guard polls.
            continue
        if stat.S_ISLNK(details.st_mode):
            raise ValueError("symlink_in_acquisition")
        if stat.S_ISREG(details.st_mode):
            size += details.st_size
            count += 1
            if count > max_files:
                raise ValueError("file_count_budget")
        elif not stat.S_ISDIR(details.st_mode):
            raise ValueError("special_file_in_acquisition")
    return size, count


def accepted_measure(root, byte_budget, max_files):
    size, count = measure(root, max_files)
    if size > byte_budget:
        raise ValueError("final_byte_budget_exceeded")
    return {"bytes": size, "files": count}


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def _git_binary():
    """Resolve git instead of hardcoding /usr/bin/git (Homebrew/nix/Windows all break on it)."""
    return os.environ.get("GIT_BINARY") or shutil.which("git") or "git"


def run(command, root, home, budget, max_files, deadline, input_data=None):
    started = time.monotonic()
    peak = 0
    reason = None
    if sys.platform == "win32":
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "LANG": "C", "LC_ALL": "C",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    else:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C", "LC_ALL": "C",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (budget, budget))
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, env=env, start_new_session=True, preexec_fn=limits)
        try:
            if input_data is not None:
                process.stdin.write(input_data)
                process.stdin.close()
            while process.poll() is None:
                size, _ = measure(root, max_files)
                peak = max(peak, size)
                if size > budget or time.monotonic() > deadline:
                    reason = "sampled_byte_budget_stop" if size > budget else "deadline_stop"
                    stop(process)
                    break
                time.sleep(.05)
            code = process.wait()
        except BaseException:
            stop(process)
            raise
        finally:
            # Do not leave descendants after Git itself exits.
            stop(process)
        stdout.seek(0); stderr.seek(0)
        out, err = stdout.read(32_769), stderr.read(32_769)
    return {"command": command, "exit": code, "stop": reason, "peak_sampled_bytes": peak,
            "seconds": round(time.monotonic() - started, 3),
            "stdout": out[:32_768].decode(errors="replace"), "stderr": err[:32_768].decode(errors="replace"),
            "log_truncated": len(out) > 32_768 or len(err) > 32_768}


def acquire(repository, destination, byte_budget=64 * 1024 * 1024, max_files=20_000,
            seconds=120, require_hard_quota=False, commit=None):
    report = {"schema": "source-acquisition.v1", "repository": repository, "status": "BLOCK", "commands": [],
              "policy": "sparse-first; no ordinary-clone fallback", "code_executed": False,
              "budget": {"accepted_bytes_max": byte_budget, "files_max": max_files, "seconds": seconds,
                         "transient_disk_hard_quota": False, "transient_guard": "50ms sampled aggregate + per-file RLIMIT_FSIZE"},
              "scope": "selected text/code files only; models, images, APKs and runtime fixtures omitted"}
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or any(
            part in {".", ".."} for part in repository.split("/")):
        raise ValueError("invalid owner/repo")
    if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid commit")
    if require_hard_quota:
        return {**report, "reason": "hard_filesystem_quota_unavailable_no_network_started"}
    destination = Path(destination).resolve()
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError("destination must be fresh under an existing trusted parent")
    if not 1_048_576 <= byte_budget <= 268_435_456 or not 1 <= max_files <= 20_000 or not 1 <= seconds <= 180:
        raise ValueError("invalid bounded acquisition budget")
    with tempfile.TemporaryDirectory(prefix=".source-quarantine-", dir=destination.parent) as temporary:
        home = Path(temporary)
        root = home / "checkout"
        root.mkdir()
        common = [_git_binary(), "-c", "core.hooksPath=" + os.devnull, "-c", "protocol.file.allow=never",
                  "-c", "protocol.ext.allow=never", "-c", "protocol.https.allow=always",
                  "-c", "filter.lfs.process=", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.required=false"]
        commands = [
            (common + ["clone", "--depth", "1", "--filter=blob:none", "--no-checkout", "--no-tags", "--single-branch",
                       "--", "https://github.com/" + repository + ".git", str(root)], None),
            (common + ["-C", str(root), "sparse-checkout", "set", "--no-cone", "--stdin"], PATTERNS.encode()),
            (common + ["-C", str(root), "checkout", "--detach", "HEAD"], None),
        ]
        deadline = time.monotonic() + seconds
        try:
            for command, data in commands:
                result = run(command, root, home, byte_budget, max_files, deadline, data)
                report["commands"].append(result)
                if result["exit"] != 0 or result["stop"]:
                    return {**report, "reason": "git_failed_or_guard_stopped_no_promotion"}
                if "filtering not recognized" in result["stderr"].lower():
                    return {**report, "reason": "upstream_filter_unsupported_no_promotion"}
            measured = accepted_measure(root, byte_budget, max_files)
            if time.monotonic() > deadline:
                return {**report, "reason": "deadline_before_promotion"}
            head = run(common + ["-C", str(root), "rev-parse", "HEAD"], root, home,
                       byte_budget, max_files, deadline)
            report["commands"].append(head)
            observed_commit = head["stdout"].strip()
            if head["exit"] != 0 or head["stop"] or not re.fullmatch(r"[0-9a-f]{40}", observed_commit) or (
                    commit is not None and commit != observed_commit):
                return {**report, "reason": "commit_identity_mismatch_or_unavailable"}
            measured = accepted_measure(root, byte_budget, max_files)
            if time.monotonic() > deadline:
                return {**report, "reason": "deadline_before_final_promotion"}
            root.rename(destination)
            return {**report, "status": "ACQUIRED_SPARSE", "commit": observed_commit,
                    "accepted_measurement": measured, "destination": str(destination),
                    "upstream_identity": "DECLARED_ONLY_REQUIRES_FIRST_PASS_VERIFY_UPSTREAM"}
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            return {**report, "reason": str(error)[:256]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--byte-budget", type=int, default=67_108_864)
    parser.add_argument("--max-files", type=int, default=20_000)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--commit")
    parser.add_argument("--require-hard-quota", action="store_true")
    args = parser.parse_args()
    release = Path(__file__).resolve().parents[3]
    report = args.report.resolve()
    if args.destination.resolve().is_relative_to(release) or report.is_relative_to(release):
        parser.error("acquisition outputs must be outside the installed Skill")
    try:
        # Reserve the receipt before any network side effect; never overwrite evidence.
        with report.open("x") as stream:
            result = acquire(args.repository, args.destination, args.byte_budget, args.max_files,
                             args.seconds, args.require_hard_quota, args.commit)
            stream.write(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"status": result["status"], "report": str(report)}))
        return 0 if result["status"] == "ACQUIRED_SPARSE" else 2
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
