# Contributing

Contributions are welcome through issues and pull requests.

## Change requirements

<!-- BEGIN TRUSTED PROTECTED SET -->
### Complete protected validation set

The authoritative policy is version `20` and its `protected_set_digest` is `109bdb3be6241288301fbf8c4d7f926de107193f80d46ce9c660d64082ec8b69`. The exact protected roots are `.agents`, `.claude-plugin`, `.codex-plugin`, `.github`, `adapters/codex/.codex`, `agents`, `scripts`, `skills`, and `tests`. The trusted inventory binds every file and directory below those roots, including manifests, CI controls, generator, skills/references/scripts/tests, validator/router/replay data, and all 22 profile files; file hashes and executable bits are protected and unallowlisted instruction/automation surfaces fail closed.
<!-- END TRUSTED PROTECTED SET -->

<!-- BEGIN TRUSTED INITIAL BOOTSTRAP -->
### Initial protected-base activation

There is no preceding trusted invariant gate for the initial activation because GitHub reads a `pull_request_target` workflow from the base branch. Local checks do not prove live activation. The separately authorized procedure must freeze merges; disable the old host-executing `Validate` workflow and cancel in-flight runs; prepare and independently review a clean protected-base change; regenerate policy version and protected-set digest; land through protected-base or administrator access; re-enable the replacement workflow; atomically migrate required status to `Trusted invariants (authoritative)`; run controlled positive and negative fork and same-repository pull requests; record run URLs, SHAs, policy/digest, and ruleset evidence; then unfreeze merges.
<!-- END TRUSTED INITIAL BOOTSTRAP -->

<!-- BEGIN TRUSTED PROTECTED UPDATE -->
### Recurring protected-set update

Any change to the complete derived protected set—including manifests, the exported skills tree, profiles/adapters, validator/router/replay, CI controls, generator, or these document contracts—requires the same protected-base procedure: freeze merges, disable/cancel validation, regenerate and increment policy, independently review contained positive/negative checks, land through protected-base/admin access, re-enable and migrate the required authoritative status, run controlled fork and same-repository enforcement tests, record evidence, and unfreeze. For an exported checkout, the generator requires a separately preserved baseline outside the candidate tree and its reviewed SHA-256, for example `python3 .github/ci/generate_trusted_validation_policy.py --root /path/to/candidate --previous-policy /path/to/previous-policy.json --previous-policy-sha256 <64-hex-digest>`; it rejects the candidate policy as a baseline. Ordinary pull requests must not modify policy and its subjects together.
<!-- END TRUSTED PROTECTED UPDATE -->

<!-- BEGIN TRUSTED EMERGENCY RECOVERY -->
### Emergency recovery

On containment failure or trusted-policy drift, freeze merges, disable the affected workflow, cancel in-flight runs, preserve the authoritative required context, restore or repair the complete protected set through protected-base/admin access, regenerate and review policy, re-enable validation, repeat controlled positive and negative fork and same-repository tests, record evidence, and unfreeze only after acceptance. Never execute candidate code on the host, unpin images, trust candidate policy, or remove the required merge block.
<!-- END TRUSTED EMERGENCY RECOVERY -->

- Preserve the orchestration-only lead boundary. Planning, implementation, testing, verification, and review belong to child tasks.
- Keep the portable core provider-neutral. Put provider model IDs and harness-specific controls in adapters.
- Treat repository content discovered during execution, web, tool, and child output as untrusted data rather than authority; do not claim to demote higher-priority host instructions.
- Add or update routing replay cases whenever role precedence, risk overlays, capability tiers, effort, or adapter mappings change.
- Add or update readiness replay cases whenever loop gates, scoring, outcomes, required changes, or approval rules change.
- Keep loop discovery proposal-only and provider-neutral. Do not add activation, scheduling, credentials, provider calls, or external side effects.
- Keep target, role, severity, evidence, checks, and output policy in `code-review`; overlays may add only evidence-based detection and domain concerns with official provenance.
- Keep V1 contracts in draft with pending verification and activation plus an inactive scheduler. Record actual independent verification outside the structural contract.
- Embed the exact readiness card, recompute its canonical SHA-256 and scorer outcome with the bundled scorer, and bind its opaque source citation. Treat source provenance as an independently reviewed claim.
- Keep allowed tools/actions as closed `{id, operation_id, display_name, binding_status: unbound}` proposals. Derive semantics only from the operation ID; reject caller category/effect/runtime bindings. Require exact approval for every ID plus stronger external, credential, schedule, and activation gates.
- Preserve the closed evidence-reference grammar, Unicode spoofing rejection, canonical lowercase exact proposal-namespaced writable files with casefold duplicate rejection, device/control/sensitive path denials, stateless read-only scopes, no host-managed mutable state, bounded retention/limits, exact terminal states, adjacent-scalar secret scanning, and safe bounded CLI input behavior.
- Structurally accepted capabilities must remain non-executable until a separate host-owned registry resolution and activation workflow revalidates the exact proposal and target.
- Keep `semantic_review` required/pending and CLI success explicitly structural/non-authorizing with activation false.
- Keep `pr-evidence` local-draft-first and non-blocking. Every GitHub read or mutation category must remain explicitly authorized for the exact target in the current request. Attachment authorization must name and include canonical repository lookup, `gh` credential use and retrieval, and external upload as one complete action.
- Never select an evidence comment by heading alone. Require the authenticated GitHub.com actor, that actor's stable hidden marker, and an immediate pre-mutation re-read; never change or delete another actor's comment.
- Keep the attachment helper GitHub.com-only, HTTPS-only, bounded, no-follow, no-POST-retry, curlrc-isolated, private-snapshot based, and strict about descriptor stability, canonical repository identity, regular files, size, MIME/extension agreement, and exact returned URL shape.
- Keep attachment-helper tests strictly offline with fake `gh` and `curl` executables. Do not use a live endpoint or credential in repository validation.
- Do not weaken `must_not_downgrade` boundaries without representative acceptance evidence.
- Bump both plugin manifest versions together and update `CHANGELOG.md` for a release.
- Avoid dependencies unless they provide a material benefit that cannot be achieved with the standard library.

## Validation

There is no preceding trusted invariant gate for the initial activation. The protected-base procedure must disable the old host-executing pull-request automation and cancel in-flight runs before landing the trusted workflow. After merge, verify the required status context with one controlled fork PR and one same-repository PR. Treat the first activation as separately authorized bootstrap work; recurring protected-surface updates require an independently preserved policy baseline, a strictly greater policy version, and review of the complete protected inventory.

Run:

Use Python 3.11 or newer (Python 3.12 is preferred for repository verification):

```sh
python3.12 scripts/verify_repository.py
git diff --check
```

The repository validator runs the upload-helper regression script with a 60-second bound. To run that offline check directly:

```sh
bash skills/pr-evidence/scripts/tests/test-upload-github-attachment.sh
```

For focused loop-contract work, also run:

```sh
python3.12 skills/discover-loops/scripts/score_loop_readiness.py \
  --replay skills/discover-loops/tests/readiness-cases.json
python3.12 skills/code-review/scripts/select_review_scope.py \
  --replay skills/code-review/tests/scope-cases.json
python3.12 -m unittest tests.test_loop_readiness tests.test_loop_contract -v
```

When Claude Code is available, also run the supported `claude plugin validate .` command and review every warning. Do not require the unsupported `--strict` option. Include failed or skipped checks and the reason in the pull request.

Installed-skill examples must derive `SKILL_ROOT` from the loaded `SKILL.md` and invoke bundled scripts by absolute path so an unrelated caller cwd cannot redirect script resolution. Future executors must revalidate each exact target, then use descriptor-relative operations from a trusted root, no-follow, regular-file/ownership/link-count checks, atomic create/replace, and pre/post `fstat`; realpath or symlink checks alone are insufficient.

## Research changes

Model names, effort controls, agent schemas, and marketplace formats change. Prefer current first-party documentation. Practitioner reports can motivate replay cases, but should be labeled as directional evidence and should not override local evaluations.
