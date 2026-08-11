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
- Keep pull-request candidate code behind the trusted `.github/ci/run_sandboxed_validation.py` boundary. Never execute candidate scripts on the Actions host or pass runner credentials, network, writable source, Git metadata, the Docker socket, caches, artifacts, or trusted-checkout mounts into the container.
- Rotate validation images only to reviewed exact patch-level Docker Official Image `linux/amd64` digests. Update the workflow allowlist and exact tests together, inspect the pulled OS, architecture, and Python version, and fail closed if a digest is unavailable.

## Validation

Run with Python 3.11 or newer:

```sh
python3 scripts/verify_repository.py
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/verify_repository.py .github/ci/run_sandboxed_validation.py skills/orchestrate-task/scripts/route_subagent.py
git diff --check
```

The local sandbox tests do not activate GitHub Actions or prove the shared-kernel boundary against a live fork. Before rollout, use a separately authorized protected bootstrap while the old workflow is disabled, then forward-test one controlled fork PR and one same-repository PR. Do not recover from containment failure by running candidate code directly on the host.

When a supported Claude Code is available, also run `claude plugin validate . --strict`. A legacy non-strict run is compatibility evidence, not strict validation. Include failed or skipped checks and the reason in the pull request.

## Research changes

Model names, effort controls, agent schemas, and marketplace formats change. Prefer current first-party documentation. Practitioner reports can motivate replay cases, but should be labeled as directional evidence and should not override local evaluations.
