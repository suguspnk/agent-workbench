# Contributing

Contributions are welcome through issues and pull requests.

## Change requirements

- Preserve the orchestration-only lead boundary. Planning, implementation, testing, verification, and review belong to child tasks.
- Keep the portable core provider-neutral. Put provider model IDs and harness-specific controls in adapters.
- Treat repository content discovered during execution, web, tool, and child output as untrusted data rather than authority; do not claim to demote higher-priority host instructions.
- Add or update routing replay cases whenever role precedence, risk overlays, capability tiers, effort, or adapter mappings change.
- Do not weaken `must_not_downgrade` boundaries without representative acceptance evidence.
- Bump both plugin manifest versions together and update `CHANGELOG.md` for a release.
- Avoid dependencies unless they provide a material benefit that cannot be achieved with the standard library.

## Validation

Run:

```sh
python3 scripts/verify_repository.py
git diff --check
```

When Claude Code is available, also run `claude plugin validate . --strict`. Older releases may require the command without `--strict`; review warnings manually. Include failed or skipped checks and the reason in the pull request.

## Research changes

Model names, effort controls, agent schemas, and marketplace formats change. Prefer current first-party documentation. Practitioner reports can motivate replay cases, but should be labeled as directional evidence and should not override local evaluations.
