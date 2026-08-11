# Changelog

All notable changes to Agent Workbench are documented here. Versions follow semantic versioning.

## 0.8.0 - 2026-08-11

- Added the `grilling` skill for a rigorous, user-owned decision interview that verifies available facts, asks one decision at a time, tracks dependencies, and requires explicit shared-understanding confirmation before any action.

## 0.7.0 - 2026-08-11

- Added the `implementation-quality-governance` skill for risk-proportionate implementation and operational-change quality gates.
- Added the provider-neutral `discover-loops` skill for evidence-backed loop discovery and proposal drafting.
- Added deterministic readiness scoring across reject, manual workflow, normal skill, read-only triage loop, and supervised loop outcomes.
- Added strict V1 loop-contract validation bound to readiness evidence, typed capability categories, least-privilege approvals, portable path/state containment, bounded retention and limits, exact stop states, and draft-only lifecycle state.
- Embedded the exact normalized readiness card and recomputed its canonical digest and scorer outcome; made validation output explicitly structural and semantic-review pending.
- Required exact human approval for every capability and added closed operation-derived external and credential gates plus conservative lifecycle/destructive display defenses.
- Confined writable targets to dedicated loop output roots; rejected control/sensitive/device names, unsafe Unicode, and traversal-capable evidence references.
- Expanded high-confidence secret detection and documented descriptor-relative future-executor requirements beyond realpath checks.
- Replaced caller-authored category/effect claims with a five-operation closed proposal schema whose bindings remain explicitly unbound and non-executable.
- Changed writable scope from directory grants to exact proposal-namespaced files and rejected host-managed mutable state.
- Added adjacent-scalar and generic assignment/query secret scanning plus reproduced unsafe display-name defenses while keeping display text non-authoritative.
- Extended adjacent-scalar detection to a bounded rolling cumulative scan and rejected Unicode control, format, surrogate, and line/paragraph separator categories in all contract text.
- Required read-only action scopes to be stateless before any loop outcome and made writable targets canonical lowercase with casefold duplicate rejection for case-insensitive filesystems.
- Added conservative lifecycle-alias and common-secret detection while documenting that display filters, source provenance/authenticity, registry bindings, future filesystem safety, and verifier independence still require external verification; card digests and scorer outcomes are recomputed structurally.
- Added exact replay assertions and CLI regressions for bounded stdin/files, duplicate keys, invalid bytes/depth/integers, symlinks, special files, diagnostics, unrelated working directories, unsafe autonomy, credentials, permissions, paths, approvals, and lifecycle claims.
- Required Python 3.11 or newer, documented Python 3.12 verification, and aligned Claude validation with the supported `claude plugin validate .` command.
- Kept loop activation, scheduling, credentials, and external side effects outside the package.

## 0.6.0 - 2026-08-10

- Added deterministic two-stage subagent routing and a representative replay set.
- Added bundled Claude Code subagent profiles with model and effort selection.
- Added a repository marketplace for direct Codex installation.
- Corrected orchestration-only boundary contradictions in the skill and portable contract.
- Added mandatory security, migration, public API, and high-impact follow-up overlays.
- Strengthened manifest, profile, documentation, and CI validation.
- Clarified which read-only boundaries are behavioral rather than harness-enforced.

## 0.5.0 - 2026-08-10

- Added detailed role-specific Codex subagent profiles and practitioner-informed routing safeguards.

## 0.4.0 - 2026-08-10

- Made the lead task orchestration-only and added Codex custom-agent routing.

## 0.3.0 - 2026-08-10

- Added provider-neutral model selection and Claude plugin packaging.

## 0.2.0 - 2026-08-10

- Replaced the license text with the canonical Apache License 2.0.

## 0.1.0 - 2026-08-10

- Initial portable orchestration workflow.
