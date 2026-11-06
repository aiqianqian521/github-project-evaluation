"""Verify the exact release file set; same-directory hashes are not signatures."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


def _scan_root(root):
    """Extended-length prefix on Windows: the shipped path already exceeds MAX_PATH."""
    text = str(root)
    if os.name == "nt":
        return "\\\\?\\" + text
    return text


def verify(root):
    root = root.resolve(strict=True)
    manifest = root / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size > 2_000_000:
        raise ValueError("missing or unsafe SHA256SUMS")
    declared = {}
    for line in manifest.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("invalid manifest row")
        sha, name = match.groups()
        if (Path(name).is_absolute() or ".." in Path(name).parts or name in declared
                or name == "SHA256SUMS" or "\\" in name):
            raise ValueError("unsafe or duplicate manifest path")
        declared[name] = sha
    actual = {}
    scan = _scan_root(root)
    offset = len(scan) + 1
    for path in Path(scan).rglob("*"):
        name = str(path)[offset:].replace("\\", "/")
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("release contains link or special file")
        if path.is_file() and name != "SHA256SUMS":
            actual[name] = path
    mismatched = [name for name, path in actual.items()
                  if name in declared and hashlib.sha256(path.read_bytes()).hexdigest() != declared[name]]
    result = {"status": "PASS", "declared_files": len(declared), "actual_files": len(actual),
              "missing": sorted(set(declared) - set(actual)), "extra": sorted(set(actual) - set(declared)),
              "mismatched": mismatched, "publisher_authentication": "NOT_PROVIDED"}
    if result["missing"] or result["extra"] or result["mismatched"]:
        result["status"] = "FAIL"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        report = verify(args.root)
    except (OSError, ValueError) as error:
        report = {"status": "FAIL", "reason": str(error)}
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
