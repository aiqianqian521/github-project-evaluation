# r4 intent, evidence and acquisition contracts

## Chinese queries and roles

`discover.py 'AI画画' --source multi ...` automatically plans the original term plus `text-to-image`.
`运镜` plans original + `camera control` + `camera trajectory`; `逆向` plans original + `reverse engineering` + `decompiler`.
The exact, versioned lexicon is in `scripts/intent_policy.py`; arbitrary text is not guessed.
For other wording choose `--intent text-to-image|camera-motion|reverse-engineering` explicitly.
`--literal` disables expansions/implicit alias intent; with an explicit `--intent`, it still applies the requested role filter.

Each query obeys `--max-pages` and `--verify-top`; the total maximum is three times those budgets.
Check robots/rate for the planned operations first. Do not retry 403/429 by changing identities.
`query_plan`, `query_runs`, provenance/errors with query attribution and each row's `matched_queries` retain the audit trail.
Canonical owner/repo dedup is case-insensitive. Conflicting metadata chooses GitHub authority then observation time, never the highest preliminary score; scoring and role hints are recalculated from that summary. Provider row sums precede cross-query dedup; they are not unique project counts.
Any partial query/provider keeps the combined result PARTIAL, even with useful candidates.

Only metadata `MATCH_HINT` can enter the automatic shortlist for a supported intent.
Resource lists/tutorials, hardware-only recording and unrelated roles are rejected or UNKNOWN.
UNKNOWN/REJECT_HINT remain in candidates.json. Inspect them for false negatives; never backfill an empty shortlist.
These are conservative name/description heuristics, not general semantic understanding, source review,
measured live precision, safety certification or execution approval. Research repositories may be leads.

## JVM static inventory

`evaluate_first_pass.py` recognizes exact tracked `build.gradle` and `build.gradle.kts` files,
and same-module `src/main/java|kotlin` and named `Test*`, `*Test`, `*Tests`, `*TestCase` sources under `src/test/java|kotlin`.
It hashes materialized bounded regular files; symlink files/ancestors, untracked files and excluded asset/vendor trees do not supply evidence.
No settings/plugins/Gradle wrapper/build/test command is evaluated. The frozen-checkout gate does not run git status or clean filters: it compares HEAD and index then hashes raw materialized bytes, including skip-worktree/assume-unchanged files. Missing sparse paths do not supply evidence. Noncanonical filtered/CRLF bytes, modified/staged/untracked/ignored materialized data and materialized submodules BLOCK instead of running filters. Git replace refs are disabled; raw commit and tree payload hashes are checked as well as worktree blobs, so a local object-name substitution cannot borrow a genuine upstream SHA. The worktree check caps 100000 tracked paths and 256MiB materialized bytes; it is not atomic against concurrent untrusted writers. A settings include alone does not prove a module exists.
`jvm_inventory` reports path/depth scan limits and partial coverage. Unconventional layouts can remain missing;
do not translate missing detection into "repository has no tests". Static scores are not functional quality scores.

## Sparse-first acquisition

When network/source acquisition is authorized, prefer the shipped helper rather than ordinary clone then retry:

```sh
python3 -B scripts/acquire_checkout.py owner/repo \
  --destination /trusted/new-parent/checkout --report /trusted/new-parent/acquisition.json
```

It uses shallow blob-filtered no-checkout clone, then a fixed text/code sparse selection before materialization.
No Git hooks, LFS smudge, dependency install or repository command runs. The default 64 MiB includes `.git`
for the **accepted** checkout. It excludes images/models/APKs and therefore is not a complete runnable checkout.
The result still needs `evaluate_first_pass.py --verify-upstream`; declared Git origin is not identity proof.
Use `--commit <40-hex>` to reject moving HEAD instead of silently evaluating a different revision.

Transient acquisition has a sampled aggregate guard and per-file RLIMIT_FSIZE; neither is a filesystem quota.
The interval can overshoot. An exact final file/byte check after Git stops rejects the entire quarantine
instead of promoting an oversized tree. There is no unfiltered or ordinary-clone fallback.
`--require-hard-quota` returns BLOCK **before network**: this helper cannot promise a hard aggregate disk cap.
For that requirement supply an externally quota-controlled worker; do not call a polling fix a hard quota.
The parent directory/filesystem must be trusted against concurrent same-user path replacement.
Failures preserve bounded command output and reason in the receipt; temporary checkout is removed.
