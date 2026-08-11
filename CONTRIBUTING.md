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

## Validation

Run with Python 3.11 or newer:

```sh
python3 scripts/verify_repository.py
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/verify_repository.py skills/orchestrate-task/scripts/route_subagent.py
git diff --check
```

When a supported Claude Code is available, also run `claude plugin validate . --strict`. A legacy non-strict run is compatibility evidence, not strict validation. Include failed or skipped checks and the reason in the pull request.

## Research changes

Model names, effort controls, agent schemas, and marketplace formats change. Prefer current first-party documentation. Practitioner reports can motivate replay cases, but should be labeled as directional evidence and should not override local evaluations.
