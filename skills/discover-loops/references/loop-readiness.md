# Loop readiness

Use this exact normalized card before drafting a loop. Include every field exactly once and no unknown fields.

```json
{
  "recurrence": "repeated-history",
  "value": "demonstrated",
  "boundary": "bounded",
  "completion_check": "deterministic",
  "action_scope": "read-only",
  "permission_scope": "least-privilege",
  "state_scope": "none",
  "stop_rule": "explicit",
  "requested_autonomy": "supervised",
  "data_handling": "ordinary"
}
```

## Closed fields

| Field | Allowed values |
|---|---|
| `recurrence` | `none`, `one-example`, `repeated-history` |
| `value` | `unclear`, `plausible`, `demonstrated` |
| `boundary` | `open-ended`, `partial`, `bounded` |
| `completion_check` | `subjective`, `human-review`, `deterministic` |
| `action_scope` | `read-only`, `local-reversible`, `external-read-only`, `external-reversible`, `irreversible` |
| `permission_scope` | `none`, `least-privilege`, `broad` |
| `state_scope` | `none`, `bounded`, `unclear` |
| `stop_rule` | `explicit`, `human-only`, `missing` |
| `requested_autonomy` | `advisory`, `supervised`, `automatic` |
| `data_handling` | `ordinary`, `host-managed-sensitive`, `embedded-secret` |

Use `repeated-history` only for multiple traceable occurrences and `demonstrated` only for evidence of useful impact. Requested autonomy is advisory input to classification, never authority. Do not round uncertainty toward safety.

## Deterministic gates

The scorer preserves five outcomes: `reject`, `manual_workflow`, `normal_skill`, `read_only_triage_loop`, and `supervised_loop`. `activation_allowed` is always `false`.

- Reject automatic autonomy, embedded secrets, or absence of both recurrence and value evidence.
- Keep irreversible actions, broad permission, unclear state, retained state paired with read-only action scope, missing stop rules, unclear value, and inconsistent external/sensitive permissions manual.
- External read/write work and host-managed-sensitive input data require least privilege; broad or no permission cannot produce a loop.
- Loop outcomes require repeated history, demonstrated value, bounded scope, supervised requested autonomy, and an explicit stop rule.
- Ordinary read-only triage, external read-only work, and host-managed-sensitive credential reads require `state_scope: none`; bounded or unclear state cannot produce a loop from a read-only action scope. Resolve unclear state to none and remove retained state before reconsidering such a proposal. Sensitive access remains supervised and requires deterministic completion evidence.
- Supervised loops are limited to closed unbound local write, external read/write, or credential-read proposals with deterministic completion evidence. Host-managed-sensitive describes input access, not mutable host state.
- External actions and credential access require exact future human approvals; every loop proposal requires independent dry-run evidence and separate human activation.

Scores summarize the normalized choices but never override hard or manual gates. The replay file has an exact closed schema and asserts the entire typed scorer output, not selected fields.

When a loop outcome becomes a proposal, embed this exact card in the contract. Canonically serialize the normalized object as UTF-8 sorted compact JSON, compute lowercase SHA-256, and let the contract validator invoke this same bundled scorer to recompute both digest and outcome. The cited source and provenance still require external review.
