# Execute, Observe, Challenge, Loop

## Preconditions and budget

Require explicit execution authority, a fixed source hash, a separate nonproduction workspace, a nonprivileged account, own TMPDIR/HOME/SQLite/cache, real target identity, safe traffic route and stop command. Record ceilings **before** work: requests, concurrency, duration, process RSS, free disk/RAM, cost, error/corruption threshold and scope of recovery probes. Load injection against shared services, production endpoints, live orders or external APIs is NOT-RUN/BLOCK without separate scope-specific approval. Illustrative ceilings are a safety budget, **not** signed capacity SLOs; no capacity PASS without an owner-signed objective and independent generator measurement. Record budget overshoots and harness failures as process deviations, not product errors.

## Evidence-first order

1. Run the native full suite and official delivery gate in the frozen isolated tree. Preserve actual command, raw log, exit code, failure list and coverage denominator. A partial pytest invocation is not a full gate, and a gate with one failure stays FAIL even if 1281 tests and coverage pass.
2. Seed synthetic, independently expected state. Probe positive, invalid, missing-ID, authorization, duplicate, retry, contention and side effects as applicable. Read the database/file truth directly; HTTP 200, mock PnL, `business=pending`, model self-rating or a passing *defect reproduction* test are never independent financial success.
3. Run bounded load in stages with offered/completed/error counts, response distributions, generator resource use and state correctness. Stop on the first observed hard ceiling, silent wrong write or missing observability. Explicitly mark burst/soak/breakpoint NOT-RUN when unsafe; no reset of the total budget on a rerun. Inspect the *actual* child PID, not unrelated services. Terminate only processes started in the current test and verify DB integrity/restart probes. Include a false-positive harness investigation as a separate event with preserved earlier records.
4. After each OODA/Loop round, compare the same predeclared source hash and criterion IDs; record raw result, independent oracle verdict and risk-ranked delta. Loop TaskRunner's `evaluation_record_written` or Verify 1/1 is not a business gate. Require at least one negative counterexample, retain frozen holdouts for final evaluation, and never train against holdout results. If defects remain, either fix them **within separately approved source scope** or report FAIL/BLOCK with owner; do not edit test oracle or delete failed cases merely to reach a green count.

## Execution artifacts

Write `TEST-EXECUTION.json` in a new evidence directory. Minimal contract:

```json
{
  "schema": "project-tests.execution.v1",
  "run_id": "unique-run-id",
  "source_sha256": "64-lowercase-hex-chars",
  "scope": {"environment": "isolated", "authorization": "explicit-user-scope"},
  "gate": {"exit_code": 1, "evidence": {"path": "logs/gate.log", "sha256": "64-lowercase-hex-chars"}, "exit_evidence": {"path": "logs/gate.exit", "sha256": "64-lowercase-hex-chars"}},
  "cases": [{"id": "F-01", "status": "FAIL", "expected": "redacted path",
             "actual": "full path", "oracle": {"kind": "independent", "reference": "frozen owner requirement"},
             "evidence": {"path": "logs/gate.log", "sha256": "64-lowercase-hex-chars"}}],
  "pressure": {"status": "BLOCK", "attempted": true, "reason": "no signed SLO"},
  "review": {"status": "PENDING"},
  "verdict": "FAIL"
}
```

All evidence paths are relative to the evidence directory and hash the original bytes; `gate.exit_evidence` contains the original machine-written decimal exit code followed by a newline, separate from the summary claim. Do not package live credentials, raw production datasets or external absolute paths. Case statuses are `PASS`, `FAIL`, `BLOCK`, `SKIP`, `N/A`; `BLOCK/SKIP/N/A` require reason. `pressure.PASS` requires real measurement evidence, `attempted=true`, and owner-signed thresholds (also independently review the signature); otherwise use BLOCK/NOT-RUN. Derive overall verdict as FAIL when native gate or any critical oracle fails; else BLOCK when applicable cases, load or independent review remain unresolved **or not a single executed case passes**; else PASS *only after independent human review*. `validate_execution.py` detects inconsistencies and tampered local evidence but cannot verify that a person truly signed, oracle truth or permission scope; retain human review as a separate mandatory release gate.

Write `EXECUTION-RESULTS.md` with raw evidence paths, commands, measured load distribution, errors, per-case expected/actual, independent oracle method, uncovered design IDs, source and runner versions, abort/restart proofs, corrections to harness and owner-retest conditions. Update `TEST-HANDOFF.md` with a pointer to these records, **never** rewrite design-only `NOT-RUN` rows as if the original design artifact were an executed report. Archive the immutable round outputs and include a final before/after/holdout comparison with semantically independent adjudication.
