# Loop contract

Use this V1 structure only after the bundled scorer returns `read_only_triage_loop` or `supervised_loop`. The artifact is always a proposal. Validation checks structural relationships; it cannot prove semantic truth, source provenance, authorization, future filesystem safety, or verifier independence.

```json
{
  "artifact_type": "loop-contract-proposal",
  "schema_version": "1.0",
  "proposal_id": "ci-triage-v1",
  "objective": "Read recurring CI failures and draft a bounded local report.",
  "evidence_refs": ["source:ci-triage-readiness-v1", "workspace:fixtures/ci-runs-2026-07.json"],
  "readiness": {
    "outcome": "supervised_loop",
    "card": {
      "recurrence": "repeated-history",
      "value": "demonstrated",
      "boundary": "bounded",
      "completion_check": "deterministic",
      "action_scope": "local-reversible",
      "permission_scope": "least-privilege",
      "state_scope": "bounded",
      "stop_rule": "explicit",
      "requested_autonomy": "supervised",
      "data_handling": "ordinary"
    },
    "card_ref": "source:ci-triage-readiness-v1",
    "card_sha256": "e36f29ffce36af9a123d653a47730bef41f4fc84880f7087a6d435758f76bbef",
    "permission_scope": "least-privilege",
    "requested_autonomy": "supervised",
    "data_handling": "ordinary"
  },
  "semantic_review": {"required": true, "status": "pending"},
  "trigger": {"type": "event-proposal", "description": "A completed CI run has a failed job."},
  "inputs": ["CI metadata", "authorized failure logs"],
  "scope": {
    "allowed_paths": [
      "reports/loop-output/ci-triage-v1/report.json",
      "reports/loop-output/ci-triage-v1/state.json"
    ],
    "allowed_tools": [
      {"id": "ci-observer", "operation_id": "workspace.observe", "display_name": "CI observer proposal", "binding_status": "unbound"},
      {"id": "report-writer", "operation_id": "workspace.write", "display_name": "Report writer proposal", "binding_status": "unbound"}
    ],
    "allowed_actions": [
      {"id": "write-triage-report", "operation_id": "workspace.write", "display_name": "Write triage report proposal", "binding_status": "unbound"}
    ],
    "prohibited_actions": ["activate", "schedule", "install", "publish", "rerun-ci", "message", "merge", "deploy"]
  },
  "state": {
    "kind": "workspace-file",
    "location": "reports/loop-output/ci-triage-v1/state.json",
    "retention": {"mode": "bounded", "max_records": 30, "max_age_days": 30}
  },
  "acceptance": {
    "checks": ["Every failure has exactly one supported category."],
    "verifier": {"required": true, "status": "pending"}
  },
  "dry_run": {
    "cases": [
      {"id": "known-timeout", "description": "A historical timeout fixture.", "expected_evidence": "One timeout category and no external write."}
    ],
    "pass_condition": "All cases satisfy every acceptance check.",
    "result": "pending",
    "evidence_refs": []
  },
  "limits": {"max_iterations": 10, "max_retries": 1, "max_elapsed_minutes": 15},
  "terminal_states": ["complete", "blocked", "needs-approval", "failed"],
  "approvals": [
    {"action": "activate", "required": true, "approver": "human"},
    {"action": "ci-observer", "required": true, "approver": "human"},
    {"action": "report-writer", "required": true, "approver": "human"},
    {"action": "write-triage-report", "required": true, "approver": "human"}
  ],
  "rollback": "Discard proposal artifacts and leave source systems unchanged.",
  "metrics": ["classification accuracy", "human corrections", "elapsed minutes"],
  "lifecycle": {"proposal_status": "draft", "activation_status": "pending", "scheduler_status": "inactive"}
}
```

## Readiness and semantic review

- `artifact_type` is exactly `loop-contract-proposal`.
- `readiness` embeds the exact closed normalized card. The validator invokes the bundled scorer, canonically serializes the normalized card as sorted compact JSON, recomputes SHA-256, and requires the declared digest and loop outcome to match.
- Permission, autonomy, data handling, action scope, and state scope must agree across the embedded card and contract. No `reject`, `manual_workflow`, or `normal_skill` result can yield a contract.
- `card_ref` must appear exactly in `evidence_refs`. Its identity and provenance remain external-review claims; the digest and scorer outcome are structurally recomputed.
- `semantic_review` is exactly `{"required": true, "status": "pending"}`. Successful CLI output is only `structurally_valid: true`, `semantic_review_required: true`, and `activation_allowed: false`; it never emits a generic authorization-like `valid` field.

## Evidence references

References are opaque citations, never authorization to open or dereference anything. Use only `workspace:<portable-relative-path>` for a syntactically safe workspace citation or `source:<bounded-lowercase-logical-id>` for a provider-neutral source identifier. Reject every other scheme, traversal, controls, drives/colons, backslashes, URLs, and credential-bearing references. Syntax proves neither existence, authenticity, permission, nor provenance.

## Closed unbound capability proposals

Every allowed tool/action is a closed `{id, operation_id, display_name, binding_status}` object. `id` is the approval identity. `display_name` is non-authoritative human-facing text. `binding_status` is exactly `unbound`; runtime bindings, provider IDs, executable references, commands, and bound status are not accepted in V1.

Only these provider-neutral operations exist:

| `operation_id` | Derived category/effect | Rule |
|---|---|---|
| `workspace.observe` | observation / read-only | The only operation allowed in read-only triage. |
| `workspace.write` | local-workspace / local-reversible | Supervised; requires exact file targets. |
| `external.read` | external-system / read-only | Supervised, least privilege, exact approval. |
| `external.write` | external-system / external-reversible | Supervised, least privilege, exact approval. |
| `credential.read` | credential-access / read-only | Host-managed-sensitive input, supervised, least privilege, exact approval. |

Category and effect are derived solely from `operation_id`; callers cannot supply them. Lifecycle administration (`lifecycle-administration`) and irreversible operations have no accepted ID. Every capability requires an exact approval keyed to its `id`.

All accepted capabilities remain unbound and non-executable. A separate out-of-scope activation workflow must resolve an approved proposal against a host-owned operation registry, independently revalidate the exact contract/target/authority, and create any runtime binding. Structural validation never performs or authorizes that resolution.

`read_only_triage_loop` permits only `workspace.observe`, no writable paths, and no mutable state. `supervised_loop` permits bounded `workspace.write`, `external.read`, `external.write`, or `credential.read` consistent with the recomputed readiness card. Host-managed-sensitive describes input/credential references only, never mutable host state.

Obvious lifecycle, destructive, and reproduced unsafe display names are denied as defense-in-depth, and declared prohibited-action phrases are enforced against display names. This finite filter does not define or prove semantics; `display_name` never grants capability.

## Paths, state, limits, and stops

- `allowed_paths` contains exact writable files only, never directory or descendant grants. Each target is exactly `loop-data/<proposal_id>/<filename>` or `reports/loop-output/<proposal_id>/<filename>`, with canonical lowercase components, one filename component, and an allowlisted extension: `.json`, `.jsonl`, `.csv`, `.txt`, or `.log`. Duplicate targets are rejected by casefold identity so case-insensitive filesystems cannot alias two declarations. Read-only evidence belongs in opaque evidence references.
- Paths use canonical portable relative syntax. Reject controls, backslashes, drives/colons, absolute/home/environment paths, wildcards, empty/dot/dotdot segments, repeated/trailing separators, trailing dot/space, and ambiguous normalization.
- Reject agent instructions, package/build/manifests, executable control files, sensitive-name segments, and case-insensitive Windows device basenames including extension variants: `CON`, `PRN`, `AUX`, `NUL`, `CLOCK$`, `COM1..9`, and `LPT1..9`. Workspace state must exactly equal one listed writable file and requires an approved `workspace.write` proposal. Parent directory targets never authorize descendants.
- A future executor must revalidate the exact target and use descriptor-relative operations from a trusted root with no-follow behavior, regular-file, ownership, and link-count checks; atomic create/replace; and pre/post `fstat` verification. Realpath or symlink checks alone are insufficient.
- State is only `none` or `workspace-file`. No state requires empty location and `{"mode":"none"}` retention. Workspace state requires bounded retention. Mutable `host-managed` state is rejected in V1.
- Terminal states are exactly `complete`, `blocked`, `needs-approval`, and `failed`. Limits are `max_iterations` 1..50, `max_retries` 0..5, and `max_elapsed_minutes` 1..240.
- Any non-pending dry-run result requires evidence references, without proving provenance.

## Lifecycle and detection limits

Every contract prohibits `activate`, `schedule`, `install`, and `publish`. A `schedule-proposal` requires distinct exact `schedule` and `activate` approvals but remains inactive. Verifier and semantic review stay pending; lifecycle stays draft/pending/inactive.

Free text rejects Unicode control, format, and surrogate characters plus line/paragraph separators (categories `Cc`, `Cf`, `Cs`, `Zl`, and `Zp`). High-confidence secret patterns cover common unencrypted/encrypted/PGP private keys, credential URLs, authorization headers, JWTs, GitHub, OpenAI, Hugging Face, npm, PyPI, Slack, GitLab, Stripe live, Google, and AWS credentials plus long generic secret assignments/query values. Bounded recursive scanning also uses a rolling 8,192-character cap to check canonical adjacent scalar concatenations fragmented across any number of consecutive strings. Detection remains best-effort: require host-managed input references, an external secret scan, and independent human review.

Run the bundled validator with Python 3.11 or newer from the `SKILL_ROOT` derived from the installed `SKILL.md`, never arbitrary caller cwd.
