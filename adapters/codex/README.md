# Codex Subagent Adapter

Copy the `.codex/agents/` directory in this adapter into a trusted project's `.codex/agents/` directory, or into your personal Codex agent directory. It provides fixed model and reasoning-effort settings for named child roles; it does not configure the parent task.

The `orchestrate-task` skill selects a role only after confirming that the harness exposes the role and its configured models. Update a profile locally when your account uses different model availability. Do not copy these profiles into an untrusted project.

| Role | Purpose | Default |
| --- | --- | --- |
| `awb_planner` | Read-only discovery and implementation plan | Sol / high |
| `awb_fast_investigator` | Narrow, repeatable evidence gathering | Luna / low |
| `awb_builder` | Bounded implementation and tests | Terra / medium |
| `awb_deep_worker` | Difficult debugging or design work | Sol / high |
| `awb_test_engineer` | Independent integration and regression validation | Terra / high |
| `awb_verifier` | Scope, diff, and deterministic-check validation | Terra / medium |
| `awb_migration_worker` | Schema, persistence, or compatibility migration | Sol / extra high |
| `awb_reviewer` | Consequential correctness and compatibility review | Sol / high |
| `awb_security_reviewer` | Security-sensitive review | Sol / extra high |
