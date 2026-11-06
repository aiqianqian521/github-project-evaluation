# Route by executable surface

For mixed projects create a composite coverage map. Evidence must link to a specific repository revision and deployment identity. Sandbox state is an **orthogonal property**: in every route identify read/write/network/privilege limits and whether a safe equivalent exercise exists; substitutes must not be scored as native passes.

| Surface | Functional truth | Load unit and pressure hazards | Minimum observability |
| --- | --- | --- | --- |
| HTTP/API | schema, auth, idempotency, state transition, response and backing store | request arrival, body sizes, endpoint mix; bottlenecks in DB/queue/downstream/rate limiting | p50/p95/p99 end-to-end, errors by type, saturation and downstream metrics |
| CLI/library | output, exit semantics, state/files, input edge cases | concurrent invocations/calls, batch sizes, CPU/memory/filesystem; shared report collisions | wall time, unique run ID, queue/lock wait, RSS and output integrity |
| UI | user journeys, accessibility, error/retry, underlying API effects | browser sessions and API backplane; do not equate browser concurrency with API RPS | navigation timings + server-side errors/traces |
| Host/container agent | host vs container capabilities, enforcement, idempotent job/status | scan jobs, agents/host, scheduler burst, per-host resource and server ingest pressure | job start/end, skip reason, coverage, host and collector resources |
| Data pipeline | schema, lineage, deduplication, time availability, replay | records/batches, partitions, late data and backpressure | ingress/egress lag, retry, dead letter, completeness, watermark |
| AI/agent workflow | model answer independent judge, tool permissions, evidence linkage, resume | tasks/min, model tokens and latency, rate limit, retries, parallel work, cost | execution/output/business verdicts, per-tool trace, token/cost and saturation |
| Finance/safety | causality, ledger reconciliation, risk gate, sandbox vs live | event throughput and risk check latency only on **synthetic** data | independently recomputable state, halt/approval/audit and uncertainty |

Route selection: do not assume a WebUI is the bottleneck when decisions happen in workers; select entry→processing→result→state/side-effects. List excluded layers explicitly. For load work, if no safe harness exists, specify how to build one and mark the scenario `BLOCKED`; avoid unsolicited traffic against third parties.
