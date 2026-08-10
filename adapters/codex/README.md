# Codex Subagent Adapter

Copy this adapter's `.codex/agents/*.toml` files into a trusted project's `.codex/agents/`, or into `~/.codex/agents/` for personal roles. Review same-named destination files first because a direct copy can replace them. The profiles pin model and reasoning-effort settings for named child roles; they never configure the parent task.

The `orchestrate-task` skill selects a role only after confirming that the harness exposes the role and its configured models. Update a profile locally when your account uses different model availability. Do not copy these profiles into an untrusted project.

Codex custom-agent files override inherited subagent model and effort defaults. The verifier and test engineer need `workspace-write` to run checks that create caches or artifacts, but their instructions prohibit source edits. Require before/after status evidence; this is a behavioral boundary, not a filesystem proof that every command was read-only.

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
