# Three deliverables and completeness review

Write to a new directory controlled by the user or local workspace. Do not overwrite prior reports. The two design files are mandatory; the handoff file captures decisions and source provenance. Use these **exact section headings** (validator uses them); add project-specific subsections freely.

## `FUNCTIONAL-TEST-DESIGN.md`

1. `## 项目画像与证据边界` — revision/path/source, actual entry and workflows, observed versus inferred, runtime/environment/sandbox, explicit exclusions.
2. `## 功能风险地图` — high-risk side effects, invariants, test layers, test type route, source-backed mapping.
3. `## 功能用例账本` — table of stable `F-...` IDs including positive, negative, boundary, concurrency, recovery, permissions and delivery as appropriate. Every row has fixture, action, expected truth/forbidden side effect, independent oracle, evidence, level, impact and current `NOT-RUN`.
4. `## 环境与准入` — fixture isolation, data/credentials, source-to-binary check, observation availability, permissions and non-executable blockers.
5. `## 执行顺序与判据` — exact conditional commands when known (never fabricate an executable path), preconditions, cleanup, PASS/FAIL/BLOCK/SKIP/N/A semantics and independent scoring.
6. `## 准出与交付` — coverage counting, release/partial gate, append-only evidence, run ID, issue/error logs, sanitized archive and owners.

## `PRESSURE-TEST-DESIGN.md`

1. `## 负载对象与容量目标` — legitimate target, topology, units, SLO/owner or TBD block.
2. `## 负载模型与工作负载` — open/closed arrival, transaction mix, payload and data distribution, generators/downstream/dependencies.
3. `## 场景与流量曲线` — stable `P-...` IDs, per-phase rate/concurrency/duration/ramp/repeats/stop signal; baseline, target, staircase, burst, soak, breakpoint if safe and recovery (N/A with reason if omitted).
4. `## 环境数据与隔离` — synthetic data, hardware, source/config, network, max budget, cleanup/rollback and test authorization.
5. `## 观测与归因` — offered/completed, distribution/tails, errors, resources, generator bottleneck, correctness, per-tenant and traces; correlation and baselines.
6. `## 停机回滚与恢复` — numeric ceilings approved by named owner or TBD BLOCK, kill switch, recovery probes, data integrity and incident routing.
7. `## 判据与报告` — thresholds, measurement window, full raw evidence/ID/hash, independent decision, blockers and interpretation limits.

## `TEST-HANDOFF.md`

Include traceability table `source claim | source ref/line | design decision | verification still needed`, decision owner/TBD table, case counts by type, risk-ranked blind spots and next authorized step. Add an independent review table: `check | reviewer | independent evidence | decision | owner/retest condition`, with rows for source existence or incomplete label, risk-to-case coverage, independent oracles, signed load scope/limits/stop or execution BLOCK, and secrets/redaction review. If reviewer, evidence or decision is missing, set `DESIGN-REVIEW-BLOCKED`; never present the validator result as that sign-off. Source guides may give methodology, **not current project truth**. Explicitly state `设计完成 ≠ 测试通过` and list all unexecuted cases.

Design completion: both documents exist, each functional row has at least six columns (ID, scope/source, fixture/action, expected truth or oracle, evidence, execution status), and each pressure row has at least five (ID, scenario, load and curve, observation or abort, execution status). The last column must contain `NOT-RUN`; add `BLOCK/SKIP/N/A` and the reason there when relevant. The portrait has a source locator, the handoff has a source reference and a separate five-row independent-review table; unresolved reviewer or evidence requires `DESIGN-REVIEW-BLOCKED`. The pressure document explains abort/recovery; oracle and load unit match the actual project; missing authorizations/thresholds are flagged; no invented execution success is allowed. The validator only checks parseability and minimum structural shape: a source path might not exist, case columns might lie, a reviewer could be fictitious and a fake SLO might parse. An independent reviewer must challenge those claims; actual testing remains a separate user-approved task.

For explicitly authorized execution, keep the three design documents frozen and add `TEST-EXECUTION.json` plus `EXECUTION-RESULTS.md` as specified in [execution method](execution-method.md). Store original logs next to the execution manifest with SHA-256, map every risk and case ID to actual evidence or BLOCK/N/A, keep native gate and independent business verdict separate, and obtain independent reviewer sign-off before acceptance. `validate_execution.py` verifies consistent hashes, statuses, exit codes, scope and derived verdict; it does not certify semantic truth, ownership or real authorization.
