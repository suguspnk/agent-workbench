---
name: code-review-node-nestjs
description: "Add Node.js and NestJS-specific defect concerns to the code-review core when runtime imports, dependencies, or framework configuration provide evidence. This overlay does not own targets, severity, checks, or output."
---

# Node.js and NestJS Review Overlay

Use only with `$code-review` and the implied JavaScript/TypeScript overlay. The core owns target selection, role protocol, severity, evidence, checks, and output.

Select this overlay only from real Node built-in/server/Nest imports, runtime dependencies, `nest-cli.json`, or an explicit caller override at the nearest package/config boundary. A `.js` or `.ts` extension alone is not Node/Nest evidence.

Read [references](references.md), then apply the mapped concerns relevant to the changed code.

## Mapped review concerns

- [NODE-001] Trace synchronous CPU, filesystem, crypto, compression, parsing, regex, and loop work on request/event-loop paths; identify demonstrated blocking or starvation risks.
- [NODE-002] Verify operational/programmer errors, rejected promises, callback errors, EventEmitter `error` events, stream errors, and cleanup reach the intended boundary exactly once.
- [NEST-001] Check shutdown and lifecycle hooks for signal registration, enabled shutdown hooks, async completion, resource ordering, idempotence, and in-flight work behavior.
- [NEST-002] Verify Nest exception filters preserve intended HTTP/RPC/GraphQL semantics, do not leak internals, and do not swallow or remap errors inconsistently across transports.
- [NEST-003] Inspect provider scope and lifecycle only where changed state is shared; look for request leakage, unintended singleton state, or duplicate initialization with concrete call paths.

Do not report generic framework preferences, folder-layout opinions, or speculative scale concerns. Send only evidenced defects to the core contract.
