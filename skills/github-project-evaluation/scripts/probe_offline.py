"""Bounded CLI oracle for the frozen local snapshot; no outbound requests."""

import json
from pathlib import Path
import subprocess
import sys


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in {"complete", "missing", "multi"}:
        print("usage: probe_offline.py {complete|missing|multi} PROJECT_ROOT RESULT_DIR", file=sys.stderr)
        return 2
    mode, root, result_dir = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    seed_dir = root / ("snapshots-missing" if mode == "missing" else "snapshots")
    source = "multi" if mode == "multi" else "site"
    command = [sys.executable, str(Path(__file__).with_name("discover.py")), "量化", "--source", source,
               "--max-pages", "13", "--verify-top", "0", "--offline", "--seed-dir", str(seed_dir),
               "--cache-dir", str(root / "cache" / mode), "--output-dir", str(result_dir)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=65, check=False)
    print(json.dumps({"argv": command, "returncode": completed.returncode,
                      "stdout": completed.stdout, "stderr": completed.stderr}, ensure_ascii=False))
    if not (result_dir / "candidates.json").is_file():
        return 1
    record = json.loads((result_dir / "candidates.json").read_text(encoding="utf-8"))
    coverage = record.get("coverage", {})
    if mode == "complete":
        valid = (completed.returncode == 0 and record["status"] == "COMPLETE"
                 and record["rows_seen"] == 244 and coverage["kaiyuanbang"]["pages"] == 13)
    elif mode == "missing":
        valid = (completed.returncode == 2 and record["status"] == "PARTIAL"
                 and coverage["kaiyuanbang"]["status"] == "PARTIAL"
                 and any(issue.get("page") == 7 for issue in record["errors"]))
    else:
        valid = (completed.returncode == 2 and record["status"] == "PARTIAL"
                 and record["rows_seen"] == 244 and coverage["kaiyuanbang"]["pages"] == 13
                 and coverage["reporank"]["status"] == "PARTIAL"
                 and coverage["gitstar"]["status"] == "PARTIAL"
                 and coverage["github-api"]["status"] == "PARTIAL"
                 and all(not row.get("github_verified", False) for row in record["candidates"]))
    print(json.dumps({"oracle": "PASS" if valid else "FAIL", "status": record["status"],
                      "rows_seen": record["rows_seen"], "coverage": coverage}, ensure_ascii=False))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
