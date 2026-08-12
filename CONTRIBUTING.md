# Contributing

Contributions are welcome through issues and pull requests.

## Change requirements

- Preserve the orchestration-only lead boundary. Planning, implementation, testing, verification, and review belong to child tasks.
- Keep the portable core provider-neutral. Put provider model IDs and harness-specific controls in adapters.
- Treat repository content discovered during execution, web, tool, and child output as untrusted data rather than authority; do not claim to demote higher-priority host instructions.
- Add or update routing replay cases whenever role precedence, risk overlays, capability tiers, effort, or adapter mappings change.
- Keep replay expectations complete and exact; duplicate IDs, missing/unknown fields, and partial expected objects must fail.
- Keep the canonical structured policy block for all 11 Claude and Codex roles aligned while preserving provider-local models, effort, and least-authority tool sets. The validator requires the reviewed block exactly and rejects recognized privilege-grant language outside it; this deterministic check does not prove arbitrary natural-language semantics.
- Do not weaken `must_not_downgrade` boundaries without representative acceptance evidence.
- Bump both plugin manifest versions together and update `CHANGELOG.md` for a release.
- Avoid dependencies unless they provide a material benefit that cannot be achieved with the standard library.
- Keep pull-request candidate code behind the trusted `.github/ci/run_sandboxed_validation.py` boundary. Never execute candidate scripts on the Actions host or pass runner credentials, network, writable source, Git metadata, the Docker socket, caches, artifacts, or a trusted checkout into the container. Only the four individually mounted base-branch control files may enter the trusted-invariant container.
- Treat `.github/ci/trusted_invariant_gate.py`, `.github/ci/trusted_validation_policy.json`, `.github/ci/run_sandboxed_validation.py`, and `.github/workflows/validate.yml` as protected root controls. After initial activation, ordinary pull requests must fail when they change any of them; update them only through a separately reviewed protected-base procedure.
- Rotate validation images only to reviewed exact patch-level Docker Official Image `linux/amd64` digests. Update the workflow allowlist and exact tests together, inspect the pulled OS, architecture, and Python version, and fail closed if a digest is unavailable.

## Validation

Run with Python 3.11 or newer:

```sh
python3 scripts/verify_repository.py
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/verify_repository.py .github/ci/run_sandboxed_validation.py .github/ci/trusted_invariant_gate.py skills/orchestrate-task/scripts/route_subagent.py
git diff --check
```

The local sandbox tests do not activate GitHub Actions or prove the shared-kernel boundary against a live fork. There is no preceding trusted invariant gate for the initial activation because GitHub reads a `pull_request_target` workflow from the base branch. Use a separately authorized protected-base or administrator procedure: disable the old host-executing pull-request automation and cancel its in-flight runs before landing the new workflow. After merge, forward-test one controlled fork PR and one same-repository PR before treating the new workflow as active protection. Do not recover from containment failure by running candidate code directly on the host.

When a supported Claude Code is available, also run `claude plugin validate . --strict`. A legacy non-strict run is compatibility evidence, not strict validation. Include failed or skipped checks and the reason in the pull request.

<!-- BEGIN TRUSTED PROTECTED SET -->
### Complete protected validation set

The authoritative policy is version `7` and its `protected_set_digest` is `863f9e17067b15cb4b7877bf83cdea6feb48c9dad30cb0b7a7898f549e8e9c65`. The exact protected roots are `.agents`, `.claude-plugin`, `.codex-plugin`, `.github`, `adapters/codex/.codex`, `agents`, `scripts`, and `skills`. The trusted inventory binds every file and directory below those roots, including manifests, CI controls, generator, skills/references/scripts/tests, validator/router/replay data, and all 22 profile files; file hashes and executable bits are protected and unallowlisted instruction/automation surfaces fail closed.
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

## Research changes

Model names, effort controls, agent schemas, and marketplace formats change. Prefer current first-party documentation. Practitioner reports can motivate replay cases, but should be labeled as directional evidence and should not override local evaluations.
