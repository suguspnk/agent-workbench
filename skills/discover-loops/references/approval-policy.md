# Approval policy

An approval entry records a future gate; it never grants authority or performs an action during discovery or drafting. No approval overrides a prohibition.

## Always require exact human approval

- `activate` for every proposal.
- `schedule`, separately from `activate`, for every `schedule-proposal` trigger. The trigger remains descriptive and the scheduler remains inactive.
- The exact `id` of every allowed unbound capability proposal, including `workspace.observe` and `workspace.write`.
- The exact `id` of every `external.read` or `external.write` proposal, which must be least-privilege and supervised.
- The exact `id` of every `credential.read` proposal. It must describe host-managed-sensitive input access, least privilege, and supervised outcome.

Lifecycle/irreversible operations have no accepted `operation_id`. Every accepted capability remains `unbound` and non-executable; approval cannot bind it. A separate host-owned registry resolution and activation workflow is required outside this skill. Obvious unsafe display names are denied as defense-in-depth, but `display_name` is non-authoritative and filters cannot prove semantics.

## Never encode credentials

Do not place tokens, passwords, API keys, authorization headers, session material, private keys, credential URLs, or copied credential values in a proposal, approval, readiness card, evidence reference, fixture, or diagnostic. Use only an authorized host-managed logical reference. Secret detection is best-effort; require the host's external secret scan and human review before acceptance.

Keep every proposal draft/pending/inactive. Structural validation recomputes the embedded card's digest and readiness outcome, but it cannot prove display-name semantics, source-card authenticity or provenance, registry bindings, verifier independence, or future execution safety.
