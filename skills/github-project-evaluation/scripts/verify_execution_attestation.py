"""Verify an externally signed run envelope without granting project approval."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from validate_execution_evidence import SHA, check_evidence, local_file
from crypto_runtime import openssl_binary


RUN_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


def signature_valid(envelope_bytes, signature_bytes, key_bytes, temporary_parent):
    if len(signature_bytes) != 64:
        return False
    with tempfile.TemporaryDirectory(dir=temporary_parent) as directory:
        folder = Path(directory)
        (folder / "envelope").write_bytes(envelope_bytes)
        (folder / "signature").write_bytes(signature_bytes)
        (folder / "public.pem").write_bytes(key_bytes)
        try:
            binary = openssl_binary()
            key_info = subprocess.run(
                [binary, "pkey", "-pubin", "-in", str(folder / "public.pem"),
                 "-text_pub", "-noout"], capture_output=True, timeout=8, check=False,
                env={"PATH": "/usr/bin:/bin", "HOME": str(folder)})
            if key_info.returncode != 0 or not key_info.stdout.startswith(b"ED25519 Public-Key:"):
                return False
            result = subprocess.run(
                [binary, "pkeyutl", "-verify", "-pubin", "-inkey", str(folder / "public.pem"),
                 "-rawin", "-in", str(folder / "envelope"), "-sigfile", str(folder / "signature")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False,
                env={"PATH": "/usr/bin:/bin", "HOME": str(folder)})
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0


def verify(envelope_bytes, signature_bytes, key_bytes, pinned_key_sha256, manifest_bytes,
           artifacts_root, expected_repository, expected_commit, expected_run_id,
           expected_spec_sha256, temporary_parent):
    envelope = json.loads(envelope_bytes)
    manifest = json.loads(manifest_bytes)
    if not isinstance(envelope, dict) or envelope.get("schema") != "project-tests.attestation.v1":
        raise ValueError("invalid attestation schema")
    required = {"schema", "repository", "commit", "run_id", "task_spec_sha256", "manifest_sha256"}
    if set(envelope) != required:
        raise ValueError("invalid attestation fields")
    if not isinstance(expected_run_id, str) or not RUN_ID.fullmatch(expected_run_id):
        raise ValueError("invalid expected run id")
    if any(not isinstance(digest, str) or not SHA.fullmatch(digest) for digest in
           (pinned_key_sha256, expected_spec_sha256, envelope["task_spec_sha256"], envelope["manifest_sha256"])):
        raise ValueError("invalid digest")
    evidence = check_evidence(manifest, artifacts_root, hashlib.sha256(manifest_bytes).hexdigest())
    reasons = list(evidence["reasons"])
    if evidence["local_integrity"] != "INTACT_LOCAL":
        reasons.append("local_artifact_integrity_failed")
    if (envelope["repository"] != expected_repository or envelope["commit"] != expected_commit or
            envelope["repository"] != evidence["repository"] or envelope["commit"] != evidence["commit"]):
        reasons.append("repository_or_commit_binding_mismatch")
    if envelope["run_id"] != expected_run_id:
        reasons.append("run_binding_mismatch")
    if envelope["task_spec_sha256"] != expected_spec_sha256:
        reasons.append("task_spec_binding_mismatch")
    if envelope["manifest_sha256"] != evidence["manifest_sha256"]:
        reasons.append("manifest_binding_mismatch")
    if hashlib.sha256(key_bytes).hexdigest() != pinned_key_sha256:
        reasons.append("public_key_pin_mismatch")
    crypto_valid = signature_valid(envelope_bytes, signature_bytes, key_bytes, temporary_parent)
    if not crypto_valid:
        reasons.append("signature_invalid")
    return {"schema": "project-tests.attestation-check.v1", "repository": evidence["repository"],
            "commit": evidence["commit"], "run_id": expected_run_id,
            "manifest_sha256": evidence["manifest_sha256"],
            "local_integrity": evidence["local_integrity"],
            "signature_status": "CRYPTO_VALID" if crypto_valid else "BLOCK",
            "key_pin_status": "MATCH" if "public_key_pin_mismatch" not in reasons else "BLOCK",
            "anchor_trust": "CALLER_ASSERTED_NOT_INDEPENDENTLY_VERIFIED",
            "candidate_acceptance": "NOT_REVIEWED", "decision": "BLOCK", "reasons": reasons}


def main():
    parser = argparse.ArgumentParser(description="Verify a pinned signed envelope; never approve a project")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--trusted-public-key", type=Path, required=True)
    parser.add_argument("--pinned-key-sha256", required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--expected-repository", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-spec-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or args.output_dir.is_symlink() or not args.output_dir.parent.is_dir():
        parser.error("output directory must be fresh")
    output_parent = args.output_dir.parent.resolve()
    if any((parent / ".git").exists() for parent in (output_parent, *output_parent.parents)):
        parser.error("output directory must be outside checkout")
    if args.artifacts_dir.is_symlink() or not args.artifacts_dir.is_dir():
        parser.error("artifacts directory must be a plain directory")
    try:
        manifest_bytes = local_file(args.manifest.parent, args.manifest.name, 64_000)
        envelope_bytes = local_file(args.envelope.parent, args.envelope.name, 8_000)
        signature_bytes = local_file(args.signature.parent, args.signature.name, 2_000)
        key_bytes = local_file(args.trusted_public_key.parent, args.trusted_public_key.name, 4_000)
        result = verify(envelope_bytes, signature_bytes, key_bytes, args.pinned_key_sha256, manifest_bytes,
                        args.artifacts_dir.resolve(), args.expected_repository, args.expected_commit,
                        args.expected_run_id, args.expected_spec_sha256, output_parent)
    except (OSError, ValueError, TypeError) as error:
        parser.error(f"invalid attestation input: {type(error).__name__}")
    args.output_dir.mkdir()
    (args.output_dir / "ATTESTATION-CHECK.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"signature_status": result["signature_status"], "decision": "BLOCK",
                      "reasons": result["reasons"]}))
    return 0 if not result["reasons"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
