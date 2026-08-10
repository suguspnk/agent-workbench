# Model Selection and Thinking Effort

Use this reference only for child tasks when the harness exposes model, reasoning-effort, or execution-mode controls. It never changes the lead task, a user pin, spend limit, provider configuration, or harness default.

## Contents

- [Routing card](#1-fill-a-routing-card)
- [Two-stage routing](#2-route-in-two-stages)
- [Context and parallelism](#3-constrain-context-handoffs-and-parallelism)
- [Replay protection](#4-protect-against-harmful-downgrades)
- [Capability and effort](#5-map-capability-and-effort)
- [Evidence-driven adjustment](#6-adjust-from-evidence)
- [Routing record](#7-record-the-decision)
- [Research basis](#research-basis)

## 1. Fill a routing card

Classify each child packet, not the parent request:

```text
work_shape: map | plan | extract | implement | test | debug | migrate | review
scope: one file | bounded component | cross-component | cross-system
ambiguity: settled | local unknown | competing hypotheses | open-ended
contract: none | internal | public API | persistent data | security boundary
tool_loop: none | one read/check | repeated local tools | repeated external tools
impact: reversible | user-visible | shared system | production-critical
evidence_bar: syntax | focused test | integration/regression | independent review
context_profile: compact facts | focused source set | noisy logs/large artifacts | long-running history
parallelism: none | independent read-only | independent writes | dependent sequence
change_authority: none | owned local paths | shared contract | external/destructive
router_confidence: high | uncertain | unresolved
```

Prompt length and urgency are not routing signals. A long fixed-schema extraction may remain efficient; a two-file authorization change is critical. If local execution is allowed, save exactly these fields as JSON and run:

```sh
python3 scripts/route_subagent.py --card /path/to/routing-card.json
```

The script is the canonical deterministic implementation of the rules below. Confirm that its role and controls exist in the current harness before spawning. If it cannot run, route manually and record that limitation.

## 2. Route in two stages

Choose a primary role for the packet, then add every applicable risk follow-up. A security or migration requirement is not allowed to disappear because a broader implementation rule matched first.

### Stage A: primary role

| Packet condition | Primary role | Capability / effort |
| --- | --- | --- |
| Settled read-only map or extraction with no public, persistent, security, or change-authority boundary | `awb_fast_investigator` | Efficient / low |
| Explicit planning, open-ended ambiguity, or unresolved routing | `awb_planner` | Frontier / high |
| Bounded internal implementation with settled interfaces and modest blast radius | `awb_builder` | Balanced / medium |
| Difficult debugging, public-contract implementation, cross-component work, competing hypotheses, high blast radius, or long/noisy implementation context | `awb_deep_worker` | Frontier / high |
| Schema, persistence, compatibility, backfill, rollout, or rollback work | `awb_migration_worker` | Frontier / maximum |
| Focused scope/diff inspection or deterministic acceptance check | `awb_verifier` | Balanced / medium |
| Integration, regression, concurrency, failure-path, or high-impact validation | `awb_test_engineer` | Balanced / high |
| Consequential correctness, compatibility, or maintainability review | `awb_reviewer` | Frontier / high |
| Authorization, secrets, untrusted input, tenant/data isolation, or privilege-boundary review | `awb_security_reviewer` | Frontier / maximum |

### Stage B: mandatory follow-ups

- Every implementation role requires `awb_verifier`.
- Migration and persistent-data work additionally require `awb_test_engineer` and `awb_reviewer`.
- Public API implementation additionally requires `awb_reviewer`.
- Security-boundary or external/destructive work additionally requires `awb_security_reviewer`.
- Deep work with integration/regression evidence or shared/production impact additionally requires `awb_test_engineer`.
- An unresolved implementation routes to `awb_planner` first; route the resulting bounded packet again instead of assuming a worker.

Split mixed work into packets. Do not ask a findings-only reviewer to implement, or let an implementer verify its own result.

### Harness mappings

- **Claude Code plugin:** bundled agents appear with scoped names such as `agent-workbench:awb-builder`. They use the family aliases `haiku`, `sonnet`, and `opus` so workspace model allowlists and provider substitution remain observable. Plugin agent tool lists narrow capabilities, but Claude Code does not enforce `permissionMode` for plugin agents.
- **Codex:** the optional adapter exposes underscore names such as `awb_builder` and pins current model/effort profiles. Custom-agent values override parent/default subagent values. Confirm model availability before use.
- **Other harnesses:** map the portable role, capability tier, and effort only to controls the host actually exposes. If no exact role exists, use a native child with an equivalent bounded packet; never emulate child work in the lead.

## 3. Constrain context, handoffs, and parallelism

Treat subagents as context boundaries first and a speed mechanism second.

- Send only the facts, paths, artifacts, and tools required for the packet. Point to large logs or diffs instead of pasting them into every child.
- Require a compact factual handoff: status, changed paths, commands, evidence, risks, open questions, and one next decision.
- Parallelize only independent paths with no shared writes and a defined merge/verification plan. Serialize shared-file, contract, and dependent work.
- Keep efficient roles read-only or tightly bounded. Do not give them open-ended investigation, public contracts, security decisions, destructive authority, or a free-form “fix it” packet.
- For test/review roles with shell access, require before/after working-tree status. Tool allowlists that omit Edit and Write do not make arbitrary shell commands read-only.
- On failure, revise the packet, context, tools, or role before escalating. Never repeat an unchanged prompt merely at higher effort.

## 4. Protect against harmful downgrades

Set `must_not_downgrade` for public APIs, persistent data, security boundaries, production-critical impact, and external/destructive authority. Lower those defaults only after representative replay evidence demonstrates the same acceptance outcome.

The repository replay set lives at `tests/routing-cases.json`. Run it after changing routing rules, profiles, model mappings, or tool environments:

```sh
python3 scripts/route_subagent.py --replay tests/routing-cases.json
```

Add known hard cases, easy-but-long inputs, recent failures, ordinary successes, irreversible work, and cases whose profile changed. Track both unnecessary escalation and harmful downgrade, prioritizing harmful downgrade prevention.

## 5. Map capability and effort

Capability tiers are provider-neutral:

- **Efficient:** lowest-cost, lowest-latency exposed model that supports the required context, modality, tools, and output.
- **Balanced:** strong general-purpose model for bounded implementation and validation.
- **Frontier:** strongest generally available model for difficult reasoning, long-horizon coding, or high-consequence analysis.

Set effort separately:

- **Low:** fixed-schema extraction, classification, quick lookup, or focused navigation.
- **Medium:** bounded multi-step implementation and deterministic verification.
- **High:** hard debugging, design tradeoffs, broad review, agentic tool loops, or substantial ambiguity.
- **Maximum:** only the hardest quality-first security, migration, optimization, or demonstrated lower-effort failure with a concrete evaluation plan.

Do not infer model names, capabilities, context limits, prices, or entitlements. When controls are absent, record the desired tier and effort as unavailable; do not claim they were applied. Keep effort stable within a cached child conversation unless the expected quality gain justifies cache loss.

## 6. Adjust from evidence

Start at the routed default unless a user pin, policy, or representative evaluation says otherwise.

- Escalate model tier for missing capability, context, modality, or persistent reasoning failure.
- Escalate effort when the same capable model needs more exploration or verification.
- Prefer a clearer packet, smaller context, deterministic tool, or independent reviewer when that addresses the cause.
- De-escalate only after representative cases meet the same acceptance bar. Do not generalize from one easy success.
- Never use maximum effort as a substitute for missing requirements, weak tests, unclear authorization, or unbounded scope.

## 7. Record the decision

For consequential, repeated, or costly child work, keep:

```text
primary_role: exact native or portable role
task_class: routine | bounded | complex | critical
signals: ambiguity, context, tool autonomy, contract, and impact
required_followups: exact independent roles
must_not_downgrade: yes | no, with reason
capability_tier: efficient | balanced | frontier | unavailable
effort: low | medium | high | maximum | unavailable
user_or_policy_pin: none | description
reason: concise routing rationale
evidence: acceptance, verifier result, latency, and token/cost telemetry when available
next_adjustment: retain | lower tier | raise effort | raise tier | redesign packet
```

Choose the lowest total-cost configuration that meets the quality bar. A cheaper model is not a saving if it increases retries, review failures, or human repair.

## Research basis

First-party guidance consistently separates capability, latency/cost, and reasoning effort, and recommends evaluation on representative prompts and data. Practitioner reports support bounded mission cards and context isolation, while also showing that nominal routing can be bypassed without explicit profiles and replay/log analysis. Community evidence is directional rather than a substitute for local measurement.

- [OpenAI Codex subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Anthropic: choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
- [Anthropic: effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Anthropic: Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Google: Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
- [Codex practitioner: custom subagent roles and mission cards](https://www.reddit.com/r/codex/comments/1tkpquf/how_i_set_up_custom_subagents_for_codex/)
- [Codex practitioner: automatic model/effort routing](https://www.reddit.com/r/codex/comments/1uvxi3n/i_think_codex_needs_an_auto_modelreasoning/)
- [Claude practitioner report: routing bypass and observability](https://www.reddit.com/r/ClaudeWorkflows/comments/1uf6hdt/workflow_claude_code_model_routing_with_gearbox_a/)
