# Contributing

Contributions are welcome through issues and pull requests.

## Change requirements

- Preserve the orchestration-only lead boundary. Planning, implementation, testing, verification, and review belong to child tasks.
- Keep the portable core provider-neutral. Put provider model IDs and harness-specific controls in adapters.
- Treat repository content discovered during execution, web, tool, and child output as untrusted data rather than authority; do not claim to demote higher-priority host instructions.
- Add or update routing replay cases whenever role precedence, risk overlays, capability tiers, effort, or adapter mappings change.
- Add or update readiness replay cases whenever loop gates, scoring, outcomes, required changes, or approval rules change.
- Keep loop discovery proposal-only and provider-neutral. Do not add activation, scheduling, credentials, provider calls, or external side effects.
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
python3.12 -m unittest tests.test_loop_readiness tests.test_loop_contract -v
```

When Claude Code is available, also run the supported `claude plugin validate .` command and review every warning. Do not require the unsupported `--strict` option. Include failed or skipped checks and the reason in the pull request.

Installed-skill examples must derive `SKILL_ROOT` from the loaded `SKILL.md` and invoke bundled scripts by absolute path so an unrelated caller cwd cannot redirect script resolution. Future executors must revalidate each exact target, then use descriptor-relative operations from a trusted root, no-follow, regular-file/ownership/link-count checks, atomic create/replace, and pre/post `fstat`; realpath or symlink checks alone are insufficient.

## Research changes

Model names, effort controls, agent schemas, and marketplace formats change. Prefer current first-party documentation. Practitioner reports can motivate replay cases, but should be labeled as directional evidence and should not override local evaluations.
