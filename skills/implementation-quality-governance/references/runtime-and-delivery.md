# Runtime And Delivery

For production-facing runtime, performance, observability, infrastructure, CI/CD, deployment, release, or a real operational rollout:

## Runtime And Performance

- Avoid N+1 queries, unbounded reads, full payload/table loading, costly render loops, and blocking work on latency-sensitive paths. Use pagination, limits, filtering, streaming, batching, indexes, and query shaping. Add caching only for demonstrated repeated cost with understood invalidation.
- Account for concurrency, retries, restarts, tenants, and horizontal scale. Bound concurrency and use backpressure/background work for slow external processing.
- For consequential optimization, provide a benchmark or falsifiable proxy with representative workload, baseline, expected direction and threshold, and observed result. Without either, state the hypothesis and uncertainty and do not claim improvement.
- Handle errors at the right boundary; retain causal context and cleanup. Set external-call timeouts/cancellation. Retry only transient idempotent work with bounded backoff/jitter; otherwise provide deduplication. Add privacy-safe, bounded-cardinality telemetry and verify critical signals/alerts when introduced.

## Infrastructure And Delivery Integrity

- Confirm the exact target environment, account, and region. Use least-privilege IAM, minimal ingress/egress, encryption and secret injection; assess state locking, drift, isolation, quotas, cost, availability, recovery, and destructive replacement. Run available policy, plan, and static checks. Never use production credentials in a lower environment.
- Bind an infrastructure plan to exact source/config identity, input variables, tool/provider versions, state snapshot, target environment/account/region, and applying identity. Hold an effective state lock or equivalent exclusive serialization from final drift validation through apply. If the platform cannot support either, require a central trusted, time-bounded waiver under `SKILL.md`, plus compensating concurrency controls and post-apply reconciliation. Apply the saved reviewed plan; if source, inputs, state, tools, or target drift, regenerate and re-review. Confirm the applied result against the reviewed plan and intended target.
- Build once when supported, record the tested artifact digest, and preserve that exact digest through promotion. Bind release evidence to the promoted digest; do not rebuild silently between test and deployment.

## Rollout And Operations

Only where a real production or operational rollout surface exists, define compatible deploy order, operational owner, monitoring evidence, health/abort thresholds, and rollback or forward-fix path. Use flags, staged/canary rollout, rate limits, or kill switches when project support and risk warrant them, and define cleanup. For high-risk release, establish go/no-go signals and verify old/new and migration compatibility plus recovery. Do not claim an untested rollback path.

When the request authorizes and includes an actual high-risk deployment or migration, capture evidence after the operation: exact target, applying identity, promoted artifact digest or saved-plan identity, applied result, observed health/monitoring signals, and go/no-go, abort, rollback, or forward-fix outcome. For planning-only work or work without deployment authorization, retain planning evidence and do not imply an operation occurred.
