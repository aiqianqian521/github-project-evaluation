# Reproducible pressure and stability design

## Before defining a curve

Identify real production-like flow and SLO owner. Specify workload proportions and request/job payload distribution, number of tenants, cache warm/cold state, data volume, dependency stubs versus real downstream and isolation namespace. Record target hardware, replication factor, rate limits, autoscaling, runtime/config and traffic generator capacity. No traffic injection before written approval, ceilings and abort method. Production shared services, external APIs, financial orders and irreversible host mutations default to **design only**.

Define a measurable hypothesis per scenario: e.g., queue grows because workers serialize one project; expected bottleneck and falsifying observation. Choose **open-loop** arrival rate for services subject to burst arrivals (record offered vs completed load to avoid coordinated omission); use **closed-loop** for bounded worker pools/interactive users and report concurrency/think time. Never report `C ≈ λW` as a capacity proof; if used, state it is an approximate sizing estimate subject to stability and distribution.

## Workload schedule and instrumentation

Predeclare baseline at low steady rate, approved target, staircase increments, short burst, sustained soak, controlled break-point (only in disposable environment) and post-pressure recovery. Each step has `rate/concurrency`, ramp and stable window durations, repetition/seed, data reset vs carryover, resource ceiling, and stop signal. The exact values must come from a signed SLO/capacity owner or be labelled **illustrative, blocks execution**. An unbounded `while true` or traffic to an unapproved address is not an acceptable plan. For costed LLMs include token/cost/time limits, timeout/rate-limit/retry amplification and judge quality drift.

Measure numerator/denominator explicitly: offered vs attempted vs completed throughput; p50/p95/p99 end-to-end latency for successes **and errors**; timeouts, retries, queue depth/age, CPU quota/throttle, RSS/OOM, disk/inodes/IOPS, DB pool/locks, downstream latency, tail error budget, correctness rate and lost/duplicate state. Aggregate over consistent windows, record warm-up separately, time synchronization and timestamps. Observe generator saturation independently; if generator caps first, report `BLOCKED: generator` not server capacity. Compare warm/cold and baseline/control, record regression delta and raw traces/samples rather than only charts.

## Abort, recovery, verdict

Preapprove numerical stop ceilings for errors, p99, resource/latency, data corruption, external cost, disk growth and blast radius; have a named operator with a kill command whose effect is verified **in isolation** before any load. On ceiling breach stop load, contain effects, preserve evidence and check service/data recovery and consistency; no automatic destructive cleanup. Approval scope includes address/environment, max intensity, duration, shared dependency quota and forbidden fault injection. If unknown, mark `BLOCKED`; never quietly use guessed values as production thresholds.

Report: source/config/data/generator hash; per-phase planned vs actual arrival curve; latency histograms, error classes, saturation and timestamps; bottleneck evidence, fairness by tenant, post-load data integrity and recovery; deviations/uncertainty; SLO comparison only where pre-approved. Passing tests never proves absolute capacity outside measured boundaries; distinguish throughput plateau vs latency cliff vs correctness failure.
