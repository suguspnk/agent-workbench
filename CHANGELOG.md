# Changelog

All notable changes to Agent Workbench are documented here. Versions follow semantic versioning.

## Unreleased

## 0.10.1 - 2026-08-25

- Removed the root `.mcp.json` from the distributable Codex plugin so the unsupported ownership transport remains truly unregistered; retained its descriptor only as a protected offline test fixture.

## 0.10.0 - 2026-08-24

- Added a bounded ownership preflight that resolves canonical repository matches and mismatches before expensive planner setup while preserving fail-closed provenance rules.
- Made simple read-only diagnosis use one fast investigator and made unresolved deployment-artifact work request the exact owning repository before planning, with zero probe children or waits.
- Added and hardened a metadata-only ownership scanner with deterministic replay and security coverage, while keeping its unsupported Codex MCP transport disabled until the host can bind a trustworthy workspace root.
- Expanded protected-policy, routing, race-safety, tamper, and regression coverage for the new orchestration boundary.

## 0.9.0 - 2026-08-19

- Hardened orchestration routing, role contracts, secure repository readers, bounded diagnostics, and replay coverage across Codex and Claude adapters.
- Added fail-closed trusted pull-request validation with pinned container images, an independently baseline-bound protected-surface policy, and candidate behavior checks that cannot self-authorize.
- Reconciled the protected inventory and validator with the current `main` skill tree, code-review contracts, manifests, and profile surfaces.

## 0.8.0 - 2026-08-11

- Added the opt-in `pr-evidence` skill for privacy-safe, non-blocking local pull-request evidence preparation.
- Required separate, current authorization for artifact upload, evidence-comment creation or update, duplicate or attachment cleanup, credential rotation, and security notification.
- Added authenticated-actor plus stable-marker comment ownership guidance, immediate pre-mutation re-reads, and an explicit unresolved concurrent-duplicate limitation.
- Added a GitHub.com-only upload helper with strict repository and file validation, a 25 MiB raster/video allowlist, private temporary credential storage, bounded HTTPS-only upload behavior, sanitized diagnostics, and exact result-URL validation.
- Recorded the user-attachment endpoint as `needs-confirmation` and treated HTTP `201 Created` as the upload result without a follow-up GET.
- Added strict offline fake-`gh` and fake-`curl` regression coverage and wired it into bounded repository validation. No live endpoint behavior was tested.
- Added the provider-neutral `code-review` core with deterministic PR-or-local scope selection, P0-P2 evidence rules, mandatory coverage, check recording, and auditable reviewer/verifier handoffs.
- Added composable JavaScript/TypeScript, Node.js/NestJS, React/Next.js, and React Native overlays with monorepo-aware detection and official rule provenance.
- Made the code-review core the mandatory operational contract for both `awb-reviewer` and `awb-verifier` provider profiles.
- Added deterministic scope replay and focused unit coverage for explicit and discovered targets, failure/ambiguity handling, overlay composition, and caller overrides.
- Added the `implementation-quality-governance` skill, public capability metadata, and repository guard for risk-proportionate implementation and operational-change quality gates.
- Added the self-contained `ui-ux-pro-max` skill with bundled design data, full rule references, stack-specific guidance, and standard-library search and design-system tools.
- Made skill script resolution portable across unrelated working directories through an explicit trusted absolute skill root.
- Required explicit stack selection and user-visible `html-tailwind` fallback labeling instead of silent stack inference.
- Made design-system persistence fail closed without write authorization, an absolute existing project root, and an explicit no-overwrite or force choice; preflight now covers every target and rejects symlink redirection.
- Added source-data validation, inherited and persistence regression tests, unrelated-directory smoke coverage, and upstream MIT license attribution for Next Level Builder's version 2.13.0 content.
- Added the explicitly invoked, draft-only `tech-stack-standards` skill for bounded, evidence-backed repository stack guidance with a human-application handoff.
- Enforced manual-only Codex invocation with `policy.allow_implicit_invocation: false` and retained the existing three plugin-level default prompts.
- Added declared, resolved, and runtime-observed version confidence; complete added/changed/removed/renamed/unchanged classification; repository-relative evidence; and claim-level, version-applicable source citations.
- Added fail-closed privacy, untrusted-repository, offline/thin-source, bounded freshness, manual-content preservation, and safe in-repository target replacement contracts.
- Added dependency-free package verification and unit coverage for invocation policy, source/package alignment when the personal source is present, and required safety/output semantics.

## 0.7.0 - 2026-08-11

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
