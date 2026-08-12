# Review Contract

## Contents

- [Evidence and severity](#evidence-and-severity)
- [Mandatory coverage](#mandatory-coverage)
- [Checks](#checks)
- [Handoff schema](#handoff-schema)

## Evidence and severity

A finding is actionable only when the selected diff introduced or exposed a concrete defect and the reviewer can state:

- severity and concise title;
- exact changed path and the narrowest useful line or symbol;
- triggering input, state, or control flow;
- resulting user, system, security, compatibility, or operational impact;
- a bounded requested resolution, without implementing it.

Use only:

- `P0`: release-blocking or catastrophic impact that is immediate or broadly destructive, such as reliable compromise, unrecoverable corruption, or total critical outage.
- `P1`: high-impact defect likely to affect production correctness, security, compatibility, availability, or durable data and requiring prompt correction.
- `P2`: bounded but real defect that can produce incorrect behavior, a material regression, or a missing test for a demonstrated changed behavior.

Do not emit P3 findings. Exclude formatting, naming, stylistic preferences, optional refactors, compliments, untestable hypotheticals, and concerns that depend on an unstated product requirement. A test-gap finding must name the changed behavior or failure path that lacks protection; coverage percentage alone is not a defect.

## Mandatory coverage

Record one of `passed`, `finding`, `N/A`, or `not verified` for every category:

| Category | Minimum review question |
| --- | --- |
| Correctness | Do nominal, boundary, empty, invalid, retry, and partial-failure paths preserve the intended behavior? |
| Compatibility | Are public/internal consumers, configuration, runtime versions, data formats, and mixed versions preserved? |
| Security | Are inputs, authorization, secrets, injection surfaces, unsafe execution, and privilege changes handled safely? |
| Data integrity | Are writes, transformations, identity, ordering, duplication, precision, and rollback semantics safe? |
| Concurrency | Can interleaving, races, cancellation, reentrancy, duplicated work, or stale state violate an invariant? |
| Error handling | Are errors propagated, classified, cleaned up, observable, and safe without silent partial success? |
| Test gaps | Do tests exercise the changed behavior and material negative or regression paths at the right layer? |

`N/A` requires a change-specific reason, for example: “N/A: documentation-only diff has no shared mutable state or asynchronous execution.” `Not verified` identifies an evidence limit, not a pass.

## Checks

Prefer existing focused tests, then relevant type, lint, build, integration, or security checks. A command is feasible only when it is non-destructive, within authorization, understood after a non-executing preflight, and does not require missing credentials, dependencies, services, or external writes.

For each command record exact text, exit status, and the behavior it supports. For each skip record the command or check class, why it was infeasible, and the residual uncertainty. Logs and configuration prove only what they directly show; do not promote them to observed runtime success.

## Handoff schema

Return these sections in order:

1. `Role`: reviewer or verifier and the applicable protocol.
2. `Target`: selection reason; PR number/base/head/head OID and patch identity, or staged/unstaged/untracked local inventories.
3. `Scope`: changed files inspected, surrounding/context surfaces inspected, selected overlays in fixed order, normalized detection/override evidence, and applicable guidance.
4. `Findings`: findings sorted P0 to P2. Each includes severity, title, path/location, evidence, impact, and requested resolution. State `No actionable P0-P2 findings` when empty.
5. `Coverage`: all seven mandatory categories with status and concise evidence or N/A reason.
6. `Checks`: exact commands and results.
7. `Skipped or limited`: infeasible checks and evidence limits.
8. `Working-tree integrity`: before/after status and unexpected mutations.
9. `Residual risk`: uncertainty that remains after the performed inspection and checks.

The verifier additionally states whether target selection, target completeness, overlay composition, protocol coverage, findings evidence, checks, and acceptance criteria were independently confirmed. It does not turn that confirmation into a GitHub approval or submission.
