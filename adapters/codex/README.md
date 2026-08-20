# Codex Subagent Adapter

Copy this adapter's `.codex/agents/*.toml` files into a trusted project's `.codex/agents/`, or into `~/.codex/agents/` for personal roles. Review same-named destination files first because a direct copy can replace them. The profiles pin model and reasoning-effort settings for named child roles; they never configure the parent task.

The `orchestrate-task` skill selects a role only after confirming that the harness exposes the role, required capabilities/modalities/tools/skills, and configured models. Update a profile locally when your account uses different model availability. Do not copy these profiles into an untrusted project.

Codex custom-agent files override inherited subagent model and effort defaults. The builder, deep worker, and migration worker use `workspace-write` for explicitly owned implementation changes. The verifier and test engineer also use `workspace-write`, but only so behavioral validation can run checks that create caches or artifacts; their instructions do not grant implementation authority. All five must report generated paths and before/after mutation evidence. Ownership classification is not a subagent role: the lead may make one zero-argument call to the protected bundled `awb_ownership.scan_required_artifacts` MCP tool when its exact registration is observed. If the tool is missing, use the normal full flow immediately with zero probe children or waits. The retained `awb_ownership_probe` profile is deprecated for runtime use and must never be spawned. The operator profile is reserved but unavailable, and the verifier explicitly refuses external use; no profile receives network or external execution authority. Ordinary local verifier shell checks remain supported. Use native worktree/sandbox isolation, isolated caches or databases, and credential-path denial where available.

| Role | Purpose | Default |
| --- | --- | --- |
| `awb_planner` | Read-only discovery and implementation plan | Sol / high |
| `awb_fast_investigator` | Narrow, repeatable evidence gathering | Luna / low |
| `awb_ownership_probe` | Deprecated compatibility profile; never runtime-spawned | Luna / low |
| `awb_deep_investigator` | Consequential settled mapping/extraction | Sol / high |
| `awb_builder` | Bounded implementation and tests | Terra / medium |
| `awb_deep_worker` | Difficult debugging or design work | Sol / high |
| `awb_test_engineer` | Independent integration and regression validation | Terra / high |
| `awb_verifier` | Scope, diff, and deterministic-check validation | Terra / medium |
| `awb_migration_worker` | Schema, persistence, or compatibility migration | Sol / extra high |
| `awb_operator` | Reserved unavailable external/destructive operator | Sol / extra high |
| `awb_reviewer` | Consequential correctness and compatibility review | Sol / high |
| `awb_security_reviewer` | Security-sensitive review | Sol / extra high |

External operations are blocked because mandatory independent external verification cannot safely run without a constrained network adapter. A future adapter must independently enforce the full runtime SSRF controls documented in [`model-selection.md`](../../skills/orchestrate-task/references/model-selection.md); static card or URL validation is not sufficient.
