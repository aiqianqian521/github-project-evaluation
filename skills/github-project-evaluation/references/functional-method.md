# Functional test design checklist

For every core workflow, construct an oracle ledger **before execution**:

`case_id | requirement/source | risk | environment | setup/fixture | action/entry | expected business state + forbidden side effect | oracle source | evidence path/fields | cleanup | applicability/status`.

Choose test layers (unit, contract, component, E2E) by failure mechanism. Minimize duplication: verify pure calculation with a fast independent fixture; reserve E2E for real interactions, deployment identity and rollback. Test at least:

1. Happy path with independently specified expected state, not the implementation's own output.
2. Boundary/invalid input, null/missing/upstream timeout; fail-closed for protective gates.
3. State lifecycle, restart/resume/retry/cancellation; no duplicate effects or missing committed operations.
4. Concurrent runs/tenants, isolation, unique artifacts and correct cancellation.
5. Authentication/authorization, untrusted plugin/tool input, secrets redaction; risk-specific safety invariants.
6. Regression fixed by an evidenced prior issue plus one unseen counterexample.
7. Delivery: source hash equals running version, correct config/data, real execution and logs, valid references, independent semantic result.

Declare statuses `PASS/FAIL/BLOCK/SKIP/N/A/NOT-RUN`. A generated design has no executed PASS. `SKIP` requires unmet precondition and reason, `N/A` a rationale, `BLOCK` owner and retest condition. Measure coverage as predeclared applicable criteria vs cases with independent evidence; never substitute model self-verification. For third-party/mock backends label capability not comparable with real backends. When a model is required, separate framework control path from model accuracy and version the prompt/judge/holdout.

Evidence: capture run/task/attempt ID, source/build/config/data digests, redacted command/parameters, timestamp, result, actual vs expected, original log reference, independent oracle reference. Match log assertions **literally to current code**; never reuse old project's debug prefixes. Diagnose code vs environment vs data vs oracle error without falsely turning blocked cases into passes.
