---
name: code-review-react-nextjs
description: "Add React web and Next.js-specific defect concerns to the code-review core when React DOM, Next dependencies/imports, or Next configuration provide evidence. React Native alone never activates this overlay."
---

# React and Next.js Review Overlay

Use only with `$code-review` and the implied JavaScript/TypeScript overlay. The core owns the target, role, severity, evidence, checks, and output.

Select from React DOM or Next imports/dependencies/configuration, or from React evidence at a boundary without React Native/Expo evidence. Never select it solely because React Native depends on or imports React. Record detection or caller-override evidence.

Read [references](references.md), then apply the mapped concerns relevant to the changed code.

## Mapped review concerns

- [REACT-001] Enforce hook call ordering and component/hook-only call sites through all changed branches, early returns, callbacks, and indirection.
- [REACT-002] Treat effects as synchronization with external systems. Check dependencies, cleanup, race/cancellation behavior, stale closures, duplicate development execution, and whether derived state should avoid an effect.
- [NEXT-001] Verify Server/Client Component boundaries, serializable props, browser/server-only API placement, secret exposure, and bundle expansion where `use client` or imports change.
- [NEXT-002] Inspect cache ownership, freshness, invalidation, dynamic/static rendering, request/user isolation, and mutation visibility using the repository's actual Next version and router.
- [REACT-003] Check render identity and stable keys where the diff changes state preservation or list membership/order.
- [REACT-004] Check controlled/uncontrolled input state transitions where the diff changes form ownership or initial values.
- [REACT-005] Check hydration parity where server-rendered markup or client initialization changes.
- [NEXT-003] Check loading, streaming, suspense, and error-boundary behavior where route segments or asynchronous rendering change.

Do not report subjective component structure, cosmetic preferences, or hypothetical rendering costs without an affected path. Feed only concrete defects into the core contract.
