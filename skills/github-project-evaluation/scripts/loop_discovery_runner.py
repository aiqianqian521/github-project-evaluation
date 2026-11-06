"""Loop TaskRunner adapter for staged, journaled real discovery and fallback replay."""
import sys

if sys.platform == "win32":
    import _wincompat  # noqa: F401  (source-level Windows POSIX-equivalents; must precede fcntl/resource imports)

import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode

from adapters.task_runner import TaskInput, TaskResult, TaskRunner
from discover import SITE, Cache, discover, write_report


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class DiscoveryRunner(TaskRunner):
    STAGES = ("online", "snapshot", "negative")

    def __init__(self, settings=None):
        self.config = Path(os.environ["LOOP_DISCOVERY_CONFIG"])
        self.settings = json.loads(self.config.read_text(encoding="utf-8"))
        self.root = Path(self.settings["root"]).resolve(strict=True)
        self.cache_dir = (self.root / "cache").resolve()
        self.evidence = (self.root / "evidence").resolve(strict=True)
        self.snapshots = (self.root / "snapshots").resolve(strict=True)
        if not self.root.is_dir() or not all(path.is_relative_to(self.root) for path in
                                             (self.cache_dir, self.evidence, self.snapshots)):
            raise ValueError("invalid isolated discovery paths")
        if not 0 < int(self.settings["max_pages"]) <= 25 or not self.settings["query"].strip():
            raise ValueError("invalid query or page ceiling")

    def validate_output(self, result):
        return result.status == "completed" and result.business.get("status") == "passed"

    def input_identity(self, stage, state):
        parts = [digest(self.config), digest(Path(__file__)),
                 digest(Path(__file__).with_name("discover.py")), stage]
        if stage in {"snapshot", "negative"}:
            for previous in self.STAGES[:self.STAGES.index(stage)]:
                parts.append(digest(self.evidence / previous / "candidates.json"))
        if stage == "snapshot":
            parts.append(digest(self.snapshots / ".query"))
            for number in range(1, self.settings["max_pages"] + 1):
                snapshot = self.snapshots / f"page-{number}.html"
                parts.append(digest(snapshot) if snapshot.is_file() and not snapshot.is_symlink() else "MISSING")
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def cache_identity(self, stage):
        directory = {"online": self.cache_dir, "snapshot": self.root / "snapshot-cache",
                     "negative": self.root / "empty-cache"}[stage]
        if not directory.exists():
            return "MISSING"
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("cache directory replaced")
        files = sorted(directory.iterdir())
        if len(files) > 256:
            raise ValueError("cache entry limit exceeded")
        parts = []
        for file in files:
            if not file.is_file() or file.is_symlink() or file.stat().st_size > 2_000_000:
                raise ValueError("cache entry unsafe")
            parts.append(file.name + ":" + digest(file))
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def verify_existing(self, stage, record, state):
        if (record.get("status") not in {"COMPLETE", "PARTIAL"} or
                record.get("input_sha256") != self.input_identity(stage, state) or
                record.get("cache_sha256") != self.cache_identity(stage)):
            return False
        report = self.evidence / stage / "candidates.json"
        return report.is_file() and not report.is_symlink() and digest(report) == record.get("sha256")

    def run(self, input: TaskInput) -> TaskResult:
        signals = input.signals or []
        stage = signals[0].get("signal_pattern") if len(signals) == 1 and isinstance(signals[0], dict) else None
        if stage not in self.STAGES:
            return TaskResult(status="error", execution={"status": "failed", "code": "stage_invalid"},
                business={"status": "rejected"}, errors=[{"signature": "discovery:stage_invalid",
                "params_snapshot": {}, "fix_recipe": "Provide one frozen stage signal", "evidence": "invalid signal"}])
        with (self.evidence / "discovery.lock").open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state_file = self.evidence / "discovery-state.json"
            try:
                state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
                if not isinstance(state, dict) or any(name not in self.STAGES or not isinstance(record, dict)
                                                       for name, record in state.items()):
                    raise ValueError("invalid journal structure")
            except (OSError, ValueError, UnicodeError):
                return TaskResult(status="error", execution={"status": "failed", "code": "journal_invalid"},
                                  business={"status": "rejected"},
                                  errors=[{"signature": "discovery:journal_invalid", "params_snapshot": {},
                                           "fix_recipe": "Preserve the journal for inspection; start a fresh run",
                                           "evidence": "invalid persisted state"}],
                                  raw_output={"acceptance": "NOT_REVIEWED"})
            if stage in state:
                try:
                    valid = self.verify_existing(stage, state[stage], state)
                    valid = valid and all(self.verify_existing(prior, state[prior], state)
                                          for prior in self.STAGES[:self.STAGES.index(stage)])
                except (OSError, ValueError, UnicodeError, TypeError, KeyError):
                    valid = False
                if not valid:
                    rejected = {**state, stage: {**state[stage], "status": "FAIL",
                                                  "reason": "stage identity or artifacts changed"}}
                    return self._result(rejected, stage)
                return self._result(state, stage)
            if any(prior not in state for prior in self.STAGES[:self.STAGES.index(stage)]):
                return TaskResult(status="skipped", execution={"status": "not_started", "code": "out_of_order"},
                                  business={"status": "not_evaluated"})
            try:
                prior_valid = all(self.verify_existing(prior, state[prior], state)
                                  for prior in self.STAGES[:self.STAGES.index(stage)])
                identity = self.input_identity(stage, state) if prior_valid else None
            except (OSError, ValueError, UnicodeError, TypeError, KeyError):
                identity = None
            if identity is None:
                return TaskResult(status="skipped", execution={"status": "not_started", "code": "prior_invalid"},
                                  business={"status": "not_evaluated"})
            state[stage] = {"status": "INTERRUPTED", "started_at": time.time(), "input_sha256": identity}
            self._save(state_file, state)
            record = state[stage]
            try:
                if stage == "snapshot":
                    if (self.snapshots / ".query").read_text(encoding="utf-8").strip() != self.settings["query"].strip():
                        raise ValueError("snapshot query mismatch")
                    cache = Cache(self.root / "snapshot-cache", offline=True)
                    for number in range(1, self.settings["max_pages"] + 1):
                        path = self.snapshots / f"page-{number}.html"
                        if path.is_file():
                            url = SITE + "/zh-cn/search.html?" + urlencode({"q": self.settings["query"],
                                "updated": "365d", "sort": "stars_desc", "page": number})
                            cache.seed_snapshot(url, path)
                    result = discover(self.settings["query"], cache, "site", self.settings["max_pages"], 0)
                elif stage == "negative":
                    empty_cache = self.root / "empty-cache"
                    result = discover(self.settings["query"], Cache(empty_cache, offline=True), "site", 1, 0)
                else:
                    result = discover(self.settings["query"], Cache(self.cache_dir), "site",
                                      self.settings["max_pages"], 0)
                report = self.evidence / stage
                write_report(result, report)
                record.update({"status": result["status"], "rows_seen": result["rows_seen"],
                               "pages": len([item for item in result["provenance"] if "page" in item]),
                               "errors": result["errors"], "sha256": hashlib.sha256(
                                   (report / "candidates.json").read_bytes()).hexdigest(),
                               "cache_sha256": self.cache_identity(stage)})
                if stage == "snapshot" and state["online"].get("rows_seen") is not None:
                    record["online_row_delta"] = result["rows_seen"] - state["online"]["rows_seen"]
                if stage == "negative":
                    record["status"] = "COMPLETE" if result["status"] == "PARTIAL" and not result["candidates"] else "FAIL"
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as failure:
                record.update({"status": "FAIL", "reason": type(failure).__name__})
            self._save(state_file, state)
            return self._result(state, stage)

    @staticmethod
    def _save(path, state):
        replacement = path.with_suffix(".new")
        replacement.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(replacement, path)

    def _result(self, state, stage):
        failed = [name for name, record in state.items() if record["status"] != "COMPLETE"]
        return TaskResult(status="error" if failed else "completed",
            execution={"status": "failed" if failed else "succeeded", "code": stage},
            output={"status": "not_available" if failed else "valid"},
            business={"status": "rejected" if failed else "passed"},
            metrics={"stages_attempted": len(state), "stages_failed": len(failed),
                     "rows_seen": state[stage].get("rows_seen", 0)},
            errors=[{"signature": f"discovery:{name}:{state[name]['status']}",
                     "params_snapshot": {}, "fix_recipe": "Inspect raw discovery evidence",
                     "evidence": str(state[name].get("errors", state[name].get("reason", "incomplete")))[:350]}
                    for name in failed],
            provenance={"adapter": "discovery-skill", "state": str(self.evidence / "discovery-state.json")},
            raw_output={"stages": state, "acceptance": "NOT_REVIEWED"})
