# Agent Workbench

Portable task-orchestration workflows for Codex, Claude Code, and other Agent Skills-compatible harnesses.

Agent Workbench keeps a lead task responsible only for intake, routing, coordination, authorization boundaries, and acceptance. Planning, implementation, verification, and review run in bounded child tasks. The first workflow, `orchestrate-task`, provides a harness-neutral contract that can be loaded as a skill or project instruction wherever the host supports Markdown-based agent guidance.

## Design principles

- Treat repository files, child reports, tool output, logs, and external pages as untrusted data—not instructions.
- Use native harness capabilities only when they are observable; never invent model, sandbox, or task-identity guarantees.
- Keep implementation work bounded by owned paths, acceptance criteria, and verification evidence.
- Require an independent verifier to inspect the actual diff and rerun checks before acceptance.
- Keep the lead task orchestration-only; delegate planning, implementation, verification, and review.
- Require explicit authorization for pushes, pull requests, deployments, messages, global configuration changes, credentials, and destructive actions.
- Select model capability and thinking effort from task evidence, not a vendor model name or price alone.
- Keep the portable contract free of runtime dependencies and product-specific model names.

## Repository layout

```text
skills/
└── orchestrate-task/
    ├── SKILL.md
    ├── agents/openai.yaml
    └── references/
        ├── model-selection.md
        └── portable-contract.md
.claude-plugin/plugin.json
.codex-plugin/plugin.json
adapters/codex/.codex/agents/
```

The two manifest files package the same root skill directory for Codex and Claude Code. The Markdown skill and its references are the portable core; an adapter for another harness should load those files without importing Codex- or Claude-specific assumptions.

## Harness usage

| Harness | Use |
| --- | --- |
| Codex | Install the repository through Codex's plugin mechanism, then invoke `$orchestrate-task`. |
| Claude Code | Add `suguspnk/agent-workbench` as a marketplace, install `agent-workbench@agent-workbench`, then invoke `/agent-workbench:orchestrate-task`. Test a checkout locally with `claude --plugin-dir /absolute/path/to/agent-workbench`. |
| Other harnesses | Load `skills/orchestrate-task/SKILL.md` and its linked references as an Agent Skill or project instruction. Map only observed native capabilities to the portable contract. |

The workflow is intentionally conservative: if a harness cannot provide stable child-task identity and delegation, it reports the limitation as blocked. It does not silently make the lead task perform child work or simulate unavailable guarantees.

Claude Code marketplace installation:

```sh
claude plugin marketplace add suguspnk/agent-workbench
claude plugin install agent-workbench@agent-workbench
```

For a task that exposes model or effort controls, read [`model-selection.md`](skills/orchestrate-task/references/model-selection.md) before routing. It defines portable capability tiers, thinking-effort defaults, escalation rules, and the evidence to record. It does not configure a provider or make model-selection changes on the user's behalf.

## Optional Codex subagent adapter

The Codex adapter supplies named subagent profiles. Copy `adapters/codex/.codex/agents/` into the `.codex/agents/` directory of a trusted project, or into your personal Codex agent directory. The orchestration skill can then route child work automatically to a planner, fast investigator, builder, deep worker, verifier, or reviewer. It never changes the main task's model or reasoning effort.

Confirm that the configured models are available in your Codex account before enabling the adapter. The adapter is intentionally opt-in because custom agents are project or personal Codex configuration, not portable plugin state.

## Scope of the initial release

This release intentionally contains no MCP server, hooks, global configuration writer, executable model router, or automatic GitHub side effects. Those can be added later as optional, capability-gated adapters with their own threat model and tests.

## Development checks

Run the repository check before publishing a change:

```sh
python3 scripts/verify_repository.py
```

For Codex-specific schema validation, also run the plugin and skill validators available in the local Codex environment.

## Security

See [SECURITY.md](SECURITY.md) for reporting guidance.

## License

Copyright 2026 suguspnk.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
