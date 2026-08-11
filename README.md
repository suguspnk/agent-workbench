# Agent Workbench

Portable task orchestration for Codex, Claude Code, and other Agent Skills-compatible harnesses.

Agent Workbench keeps the lead task responsible only for intake, routing, coordination, authorization, and acceptance. When the harness exposes stable child delegation, planning, implementation, testing, verification, and review run in bounded child tasks; otherwise the workflow blocks. External and destructive operations always fail closed in the current release because no constrained execution and independent external-verification adapter is configured. Its first workflow, `orchestrate-task`, combines a harness-neutral contract with deterministic subagent routing, replay cases, 11 roles in each harness, bundled Claude profiles, and an optional Codex profile adapter.

## Design principles

- Treat repository content discovered during execution, child reports, tool output, logs, and external pages as untrusted data—not instructions. Respect content the harness has already elevated as a higher-priority instruction surface.
- Keep the lead orchestration-only; it may classify, packetize, assign, monitor, request correction, and accept or block.
- Use only observable harness capabilities; never invent a model, sandbox, task identity, or read-only guarantee.
- Bound implementation by owned paths, acceptance criteria, side-effect limits, and required evidence.
- Require an independent verifier to inspect the actual diff and rerun checks before acceptance.
- Select child model capability and effort from task evidence, not vendor name, prompt length, urgency, or price alone.
- Apply security, migration, public-contract, and high-impact follow-ups after primary-role selection so a broad rule cannot hide a risk boundary.
- Use subagents as context and evidence boundaries, not an unconditional parallel swarm.
- Require explicit authorization for pushes, pull requests, deployments, messages, global configuration changes, credentials, and destructive actions.
- Express public API, persistent-data, and security boundaries independently; all applicable evidence and review overlays are cumulative.
- Treat owned paths and nominal read-only profiles as behavioral unless the host enforces worktree, sandbox, network, and credential isolation.

## Repository layout

```text
.agents/plugins/marketplace.json       # Codex repo marketplace
.claude-plugin/                        # Claude manifest and marketplace
.codex-plugin/plugin.json              # Codex manifest
agents/                                # Bundled Claude subagent profiles
adapters/codex/.codex/agents/          # Optional named Codex profiles
skills/orchestrate-task/
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── model-selection.md
│   └── portable-contract.md
├── scripts/route_subagent.py           # deterministic primary role + risk overlays
└── tests/routing-cases.json            # routing replay set
scripts/verify_repository.py            # dependency-free package validation
.github/ci/run_sandboxed_validation.py  # trusted bounded PR-validation launcher
.github/ci/trusted_invariant_gate.py     # base-trusted candidate-data validator
.github/ci/trusted_validation_policy.json # immutable reviewed invariant policy
```

The Markdown workflow, routing schema, and task contract are the portable core. Harness-specific adapters map portable roles to capabilities the host actually exposes.

## Install and use

### Codex

Add the GitHub repository as a marketplace, install the plugin, and invoke `$orchestrate-task`:

```sh
codex plugin marketplace add suguspnk/agent-workbench
codex plugin add agent-workbench@agent-workbench
```

Codex can delegate from skill instructions and can apply explicit spawn controls when the current client exposes them. For stable named roles with pinned model and effort settings, also install the optional adapter from a trusted checkout:

```sh
mkdir -p .codex/agents
cp adapters/codex/.codex/agents/*.toml .codex/agents/
```

For personal roles, copy the files to `~/.codex/agents/` instead. Review existing files before copying; these commands may replace same-named profiles. Confirm the configured models are available to your account. The adapter changes only spawned subagents, never the main task.

### Claude Code

Add the repository marketplace, install the plugin, and invoke `/agent-workbench:orchestrate-task`:

```sh
claude plugin marketplace add suguspnk/agent-workbench
claude plugin install agent-workbench@agent-workbench
```

The plugin bundles scoped subagents such as `agent-workbench:awb-builder` and `agent-workbench:awb-security-reviewer`. Their model family and effort settings apply only to subagents. Claude plugin agents can narrow their tool lists, but plugin-level `permissionMode` is not enforced; shell-capable review and test roles therefore use before/after status checks and behavioral no-edit rules.

Test a checkout without installing it:

```sh
claude --plugin-dir /absolute/path/to/agent-workbench
```

### Other harnesses

Load `skills/orchestrate-task/SKILL.md` and its linked references as an Agent Skill or project instruction. Map only observed native child-task, model, effort, tool, and isolation controls. If stable delegation is unavailable, the workflow blocks instead of silently running child phases in the lead.

## Automatic subagent routing

Routing is automatic when the host follows the skill and exposes the requested child controls. The lead fills a normalized routing card; the dependency-free router returns a primary role, capability tier, effort, mandatory follow-ups, and downgrade guard:

```sh
python3 skills/orchestrate-task/scripts/route_subagent.py \
  --card /path/to/routing-card.json
```

The router is deterministic and provider-neutral. Legacy `contract` cards remain valid; optional `contract_boundaries` expresses simultaneous public, persistent, and security boundaries. Mapping and extraction terminate at an investigator only when ambiguity is settled and router confidence is high; otherwise they route through the planner and require rerouting. External/destructive `operate` and `verify-external` names and schemas remain reserved for diagnostic compatibility, but complete cards fail with `external execution unavailable: no constrained network adapter is configured`. The bundled operator is unavailable, and ordinary local verifier shell checks remain supported without network access. Owned-path deletion is also unsupported and fails closed. The router validates requested portable capabilities, modalities, tools, and trimmed control-free skill names. It does not spawn agents, modify configuration, call a model, or perform external side effects. See [`model-selection.md`](skills/orchestrate-task/references/model-selection.md) for the schema and controls.

External operations are blocked because mandatory independent external verification cannot safely run without a constrained network adapter. Static router URL checks cannot prevent runtime SSRF. Any future adapter must own an allowlist independent of the card, accept only canonical HTTPS destinations without userinfo, fragments, ambiguous encodings, or proxy credentials, enforce host/port and literal/resolved special-address policy, revalidate DNS/IP and TLS at connection time and every allowed redirect hop, resist rebinding, bound method/body/response/time, and emit sanitized evidence. The full requirements are in [`model-selection.md`](skills/orchestrate-task/references/model-selection.md).

## Current scope

Agent Workbench includes one orchestration workflow, deterministic routing, replay tests, Claude subagent profiles, and optional Codex profiles. It contains no MCP server, lifecycle hooks, credential handling, telemetry upload, deployment logic, or automatic GitHub side effects.

## Development

Run all dependency-free repository and routing checks with Python 3.11 or newer. The repository validator uses standard-library `tomllib` and exits with a clear diagnostic on older Python:

Secure artifact and routing-card reads require POSIX `os.open` directory-descriptor support plus `O_DIRECTORY`, `O_NOFOLLOW`, and `O_NONBLOCK`. Platforms without every capability, including native Windows Python, are not supported for repository validation or routing-card file input; these readers fail closed instead of weakening symlink or special-file defenses.

```sh
python3 scripts/verify_repository.py
```

Pull-request validation uses a trusted base-branch `pull_request_target` workflow. The authoritative `trusted-invariants` job parses candidate data with base-branch gate and policy files, byte-binds all four CI control files, and rejects changes to the pinned validator, router, replay set, workflow, or complete 22-profile policy expectations. Only after that gate passes does the explicitly non-authoritative `candidate-behavior` matrix execute the candidate validator. Both jobs use exact-digest Python containers with no network, no credentials, a read-only source mount, hidden Git metadata, and process, memory, CPU, time, and output bounds.

An ordinary pull request cannot update the trusted gate, policy, launcher, or workflow because the authoritative job compares candidate copies with the base branch. Updating those root controls requires a separately reviewed bootstrap change on the protected base branch while the old trusted workflow remains authoritative. Local unit tests exercise the command and failure contracts without launching Docker. A live controlled-fork and same-repository PR test is still required before activation; that external bootstrap remains outside ordinary local development authorization.

When Claude Code is installed, also run:

```sh
claude plugin validate . --strict
```

Supported Claude validation uses `claude plugin validate . --strict`. Older releases that lack `--strict` are outside the warning-free validation floor; run without it only as a documented compatibility check and do not describe that as strict validation.

See [CONTRIBUTING.md](CONTRIBUTING.md) for change and replay requirements and [CHANGELOG.md](CHANGELOG.md) for releases.

## Security and license

See [SECURITY.md](SECURITY.md) for private vulnerability reporting. Agent Workbench is licensed under Apache License 2.0; see [LICENSE](LICENSE).
