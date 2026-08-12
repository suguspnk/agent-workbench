---
name: code-review-javascript-typescript
description: "Add JavaScript and TypeScript-specific defect concerns to the code-review core when changed files or configuration provide JS/TS evidence. This overlay never selects targets, assigns severity, changes output, or runs as a standalone review protocol."
---

# JavaScript and TypeScript Review Overlay

Use only with `$code-review`. The core owns target selection, reviewer/verifier routing, severity, evidence, checks, and handoff structure.

Select this overlay for changed JS/JSX/MJS/CJS/TS/TSX/MTS/CTS files or relevant JS/TS configuration at the nearest package/config boundary, or when the caller explicitly selects it. Record the evidence. Specialist overlays imply this overlay.

Read [references](references.md) for the authoritative basis and apply only rules relevant to the changed code and configured compiler/runtime version.

## Mapped review concerns

- [JSTS-001] Verify runtime control flow agrees with TypeScript narrowing; reject unsafe assertions, non-null assertions, or broad casts that hide reachable invalid states.
- [JSTS-006] Check discriminated unions, optional/null values, indexed access, exhaustiveness, and type guards at external or dynamic-data boundaries.
- [JSTS-002] Inspect `strict` and related compiler-option changes for newly unchecked consumers or false confidence from disabled checks.
- [JSTS-003] Verify ESM/CommonJS resolution, package exports, emitted syntax, file extensions, and runtime/toolchain compatibility where module configuration changes.
- [JSTS-004] Follow promise chains, `async`/`await`, rejection propagation, cancellation, cleanup, and accidental floating work through real callers.
- [JSTS-005] Distinguish compile-time types from runtime validation. Types alone do not validate JSON, environment variables, network responses, storage, or user input.

Do not report general style, preferred syntax, type cleverness, or optional refactors. Feed only evidenced domain defects into the core P0-P2 contract.
