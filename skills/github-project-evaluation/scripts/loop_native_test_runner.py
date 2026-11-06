"""Bounded, restart-safe project test commands driven by Loop's TaskRunner contract."""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import fcntl
import hashlib
import json
import os
import math
import platform
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from adapters.task_runner import TaskInput, TaskResult, TaskRunner


def plain_bytes(path, limit=256_000):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > limit:
            raise ValueError("expected bounded regular input")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("input exceeds limit")
        return data
    finally:
        os.close(descriptor)


def digest(path, limit=1_000_000):
    return hashlib.sha256(plain_bytes(path, limit)).hexdigest()


def source_digest(root):
    records = []
    total = 0
    for directory, folders, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        folders[:] = sorted(name for name in folders if name != ".git")
        for name in sorted(folders + files):
            if len(records) >= 20_000:
                raise ValueError("source exceeds frozen-input budget")
            path = parent / name
            details = path.lstat()
            if stat.S_ISLNK(details.st_mode):
                value = "link:" + os.readlink(path)
            elif stat.S_ISREG(details.st_mode):
                total += details.st_size
                if total > 64_000_000 or len(records) >= 20_000:
                    raise ValueError("source exceeds frozen-input budget")
                value = digest(path, 64_000_000)
            elif stat.S_ISDIR(details.st_mode):
                value = "directory"
            else:
                raise ValueError("source contains special file")
            records.append([path.relative_to(root).as_posix(), details.st_mode & 0o777, value])
    head = None
    if (root / ".git").exists():
        environment = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
        for argv in (["rev-parse", "HEAD"], ["status", "--porcelain", "--untracked-files=all"]):
            result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *argv],
                                    capture_output=True, timeout=10, env=environment, check=False)
            if result.returncode or (argv[0] == "status" and result.stdout.strip()):
                raise ValueError("frozen checkout must remain clean")
            if argv[0] == "rev-parse":
                head = result.stdout.decode().strip()
    return hashlib.sha256(json.dumps([head, records], sort_keys=True).encode()).hexdigest()


class NativeProjectTestRunner(TaskRunner):
    def __init__(self, settings=None):
        self.manifest = Path(os.environ["LOOP_TEST_MANIFEST"]).absolute()
        self.manifest_bytes = plain_bytes(self.manifest, 64_000)
        self.spec = json.loads(self.manifest_bytes)
        self.root = Path(self.spec["project_root"]).resolve(strict=True)
        self.evidence = Path(self.spec["evidence_root"]).resolve(strict=True)
        self.home = Path(self.spec["home"]).resolve(strict=True)
        self.scratch = Path(self.spec["scratch"]).resolve(strict=True)
        self.stages = self.spec["stages"]
        if (not all(p.is_dir() for p in (self.root, self.evidence, self.home, self.scratch))
                or self.evidence.is_relative_to(self.root) or self.root.is_relative_to(self.evidence)
                or not isinstance(self.stages, list) or not 1 <= len(self.stages) <= 100 or not all(
            path.is_relative_to(self.evidence) for path in (self.home, self.scratch)
        )):
            raise ValueError("invalid isolated test paths")
        details = self.evidence.stat()
        if details.st_uid != os.getuid() or details.st_mode & 0o022:
            raise ValueError("evidence must be caller-owned and not group/world writable")
        if len({stage["id"] for stage in self.stages}) != len(self.stages):
            raise ValueError("duplicate stage id")
        for stage in self.stages:
            argv = stage["argv"]
            if (not isinstance(stage["id"], str) or not stage["id"].isascii() or
                not stage["id"].replace("-", "").replace("_", "").isalnum() or
                not isinstance(argv, list) or not argv or
                not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in argv) or
                not Path(argv[0]).is_absolute() or
                not Path(argv[0]).resolve(strict=True).is_file() or
                not (self.root / stage["cwd"]).resolve(strict=True).is_relative_to(self.root) or
                not (self.root / stage["cwd"]).is_dir() or
                type(stage["timeout_seconds"]) not in (int, float) or
                not 0 < stage["timeout_seconds"] <= 3600):
                raise ValueError("unsafe test stage")
        self.limit = self.spec["max_total_seconds"]
        if type(self.limit) not in (int, float) or not 0 < self.limit <= 7200:
            raise ValueError("invalid cumulative time limit")
        self.binding = self._binding()

    def _binding(self):
        if plain_bytes(self.manifest, 64_000) != self.manifest_bytes:
            raise ValueError("manifest_changed")
        argument_files = {}
        for stage in self.stages:
            for arg in stage["argv"][1:]:
                if len(arg) > 2048:
                    continue
                candidate = self.root / stage["cwd"] / arg
                try:
                    if candidate.is_file():
                        resolved = candidate.resolve(strict=True)
                        argument_files[str(candidate)] = [str(resolved), digest(resolved, 64_000_000)]
                except (OSError, ValueError):
                    raise ValueError("unable_to_freeze_argument_file")
        data = {"spec": hashlib.sha256(self.manifest_bytes).hexdigest(), "argument_files": argument_files,
                "source": source_digest(self.root), "runner": digest(Path(__file__)),
                "executables": {stage["argv"][0]: [str(Path(stage["argv"][0]).resolve(strict=True)),
                                                   digest(Path(stage["argv"][0]).resolve(strict=True), 256_000_000)]
                                for stage in self.stages}, "platform": platform.platform()}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _load(self, path):
        if not path.exists() and not path.is_symlink():
            if any(self.evidence.glob("*.stdout")) or any(self.evidence.glob("*.stderr")):
                raise ValueError("orphan_evidence_without_state")
            return {"schema": "native-test.state.v2", "binding": self.binding, "stages": {}, "elapsed": 0.0}
        state = json.loads(plain_bytes(path))
        if (not isinstance(state, dict) or state.get("schema") != "native-test.state.v2"
                or state.get("binding") != self.binding or not isinstance(state.get("stages"), dict)
                or type(state.get("elapsed")) not in (int, float)
                or not math.isfinite(state["elapsed"]) or state["elapsed"] < 0
                or not set(state["stages"]).issubset({stage["id"] for stage in self.stages})):
            raise ValueError("state_binding_or_schema_mismatch")
        for name, record in state["stages"].items():
            if not isinstance(record, dict) or record.get("status") not in {"PASS", "FAIL", "BLOCK", "INTERRUPTED"}:
                raise ValueError("invalid_stage_record")
            if record["status"] in {"PASS", "FAIL"}:
                stage = next(item for item in self.stages if item["id"] == name)
                if (record.get("argv") != stage["argv"] or record.get("cwd") != stage["cwd"]
                        or (record["status"] == "PASS" and record.get("exit_code") != 0)):
                    raise ValueError("recorded_stage_contract_mismatch")
                for label in ("stdout", "stderr"):
                    item = record.get(label)
                    if (not isinstance(item, dict) or item.get("path") != name + "." + label
                            or item.get("sha256") != digest(self.evidence / item["path"])):
                        raise ValueError("recorded_artifact_mismatch")
        return state

    def _blocked(self, reason):
        return TaskResult(status="error", execution={"status": "failed", "code": reason},
                          output={"status": "not_available"}, business={"status": "rejected"},
                          errors=[{"signature": "native-test:blocked", "params_snapshot": {},
                                   "fix_recipe": "Preserve evidence; use a fresh authorized run", "evidence": reason}],
                          raw_output={"plan_status": "BLOCK", "project_verdict": "NOT_ACCEPTED"})

    def validate_output(self, result):
        return (result.status == "completed" and result.output.get("status") == "valid"
                and result.business.get("status") == "passed"
                and result.raw_output.get("plan_status") == "PASS")

    def run(self, input: TaskInput) -> TaskResult:
        try:
            if self._binding() != self.binding:
                raise ValueError("frozen_inputs_changed")
            return self._run_checked(input)
        except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
            return self._blocked(str(error) if isinstance(error, ValueError) else type(error).__name__)

    def _run_checked(self, input):
        signals = input.signals or []
        requested = signals[0].get("signal_pattern") if len(signals) == 1 and isinstance(signals[0], dict) else None
        stage_ids = [stage["id"] for stage in self.stages]
        if requested not in stage_ids:
            return TaskResult(status="error", execution={"status": "failed", "code": "unknown_stage"},
                              business={"status": "rejected"},
                              errors=[{"signature": "native-test:unknown_stage", "params_snapshot": {},
                                       "fix_recipe": "Use a frozen, single-stage Loop signal",
                                       "evidence": "no matching stage"}])
        lock_path = self.evidence / "native-test.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise ValueError("unsafe_lock")
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if self._binding() != self.binding:
                raise ValueError("frozen_inputs_changed")
            state_path = self.evidence / "native-test-state.json"
            state = self._load(state_path)
            stage_id = requested
            pending = self.stages[stage_ids.index(requested)]
            if stage_id in state["stages"]:
                prior = state["stages"][stage_id]
                return self._result("error" if prior["status"] != "PASS" else "skipped",
                                    f"{stage_id} already attempted", state)
            if any(state["stages"].get(prior, {}).get("status") not in {"PASS", "FAIL"}
                   for prior in stage_ids[:stage_ids.index(stage_id)]):
                return self._result("skipped", "earlier stage not safely completed", state)
            remaining = self.limit - state["elapsed"]
            if remaining <= 0:
                state["stages"][stage_id] = {"status": "BLOCK", "reason": "cumulative time budget exhausted"}
                self._save(state_path, state)
                return self._result("skipped", "cumulative time budget exhausted", state)
            argv = pending["argv"]
            record = {"status": "INTERRUPTED", "argv": argv, "cwd": pending["cwd"],
                      "started_at": time.time()}
            state["stages"][stage_id] = record
            self._save(state_path, state)
            stdout_path = self.evidence / f"{stage_id}.stdout"
            stderr_path = self.evidence / f"{stage_id}.stderr"
            started = time.monotonic()
            environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.home),
                           "TMPDIR": str(self.scratch), "PYTHONDONTWRITEBYTECODE": "1"}
            process = None
            try:
                import resource
                def log_limit():
                    resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
                with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                    process = subprocess.Popen(
                        argv, cwd=self.root / pending["cwd"], env=environment,
                        stdout=stdout, stderr=stderr, start_new_session=True, preexec_fn=log_limit)
                    try:
                        exit_code = process.wait(timeout=min(pending["timeout_seconds"], remaining))
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        raise
                record["exit_code"] = exit_code
                record["status"] = "PASS" if exit_code == 0 else "FAIL"
            except subprocess.TimeoutExpired:
                record["status"] = "FAIL"
                record["reason"] = "timeout"
            except (OSError, subprocess.SubprocessError) as error:
                record["status"] = "FAIL"
                record["reason"] = f"process start failed: {type(error).__name__}"
            finally:
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                state["elapsed"] += time.monotonic() - started
                for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
                    if path.exists():
                        record[label] = {"path": path.name, "sha256": digest(path)}
                        if path.stat().st_size >= 1_000_000:
                            record.update(status="FAIL", reason="log_limit_reached")
                record["elapsed_seconds"] = round(time.monotonic() - started, 3)
                self._save(state_path, state)
            overall_status = "completed" if all(
                item["status"] == "PASS" for item in state["stages"].values()) else "error"
            return self._result(overall_status, stage_id, state)

    @staticmethod
    def _save(path, state):
        fd, replacement = tempfile.mkstemp(prefix=".native-state-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(replacement, path)
        finally:
            if os.path.exists(replacement):
                os.unlink(replacement)

    def _result(self, status, detail, state):
        bad = {stage_id: value for stage_id, value in state["stages"].items()
               if value["status"] != "PASS"}
        remaining = [stage["id"] for stage in self.stages if stage["id"] not in state["stages"]]
        plan = "FAIL" if bad else "PENDING" if remaining else "PASS"
        return TaskResult(
            status=status,
            execution={"status": "succeeded" if status == "completed" else "failed",
                       "code": detail},
            output={"status": "valid" if status == "completed" else "not_available"},
            business={"status": "rejected" if bad else "pending" if remaining else "passed"},
            provenance={"adapter": "native-project-tests", "evidence": str(self.evidence)},
            metrics={"stages_attempted": len(state["stages"]), "stages_failed": len(bad),
                     "stages_planned": len(self.stages), "stages_remaining": len(remaining)},
            errors=[{"signature": f"native-test:{stage_id}:{value['status']}",
                     "params_snapshot": {}, "fix_recipe": "Inspect the original project test output",
                     "evidence": str(value.get("stderr", value.get("reason", "nonzero exit")))}
                    for stage_id, value in bad.items()],
            raw_output={"stage": detail, "plan_status": plan, "remaining_stages": remaining,
                        "project_verdict": "FAIL" if bad else "NOT_ACCEPTED",
                        "state": state},
        )
