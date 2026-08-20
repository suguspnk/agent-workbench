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
work_shape: map | plan | extract | diagnose | implement | test | debug | migrate | review | operate | verify-external
scope: one file | bounded component | cross-component | cross-system
ambiguity: settled | local unknown | competing hypotheses | open-ended
contract: none | internal | public API | persistent data | security boundary
tool_loop: none | one read/check | repeated local tools | repeated external tools
impact: reversible | user-visible | shared system | production-critical
evidence_bar: syntax | focused test | integration/regression | independent review
context_profile: compact facts | focused source set | noisy logs/large artifacts | long-running history
parallelism: none | independent read-only | independent writes | dependent sequence
change_authority: none | owned local paths | owned-path deletion | shared contract | external/destructive
router_confidence: high | uncertain | unresolved
contract_boundaries: optional array containing any of public API, persistent data, security boundary
required_capabilities: optional array of portable capabilities
required_modalities: optional array of text, code, structured-data, image, browser
required_tools: optional array of file-read, file-write, shell, network, browser
required_skills: optional array of exact skill names
planning_capabilities/modalities/tools/skills: optional current-step planner requirements; mutation and network are forbidden
deferred_capabilities/modalities/tools/skills: optional eventual requirements retained until the settled packet is rerouted
operation_authorization: packet ID/revision, exact action/canonical target, stable binding, approval, recovery, and verification
external_verification: matching operator reference/binding/action/target, exact scope, separate approval, public read-only access, and direct observation
```

`external-operation` is reserved for `work_shape: operate`; `external-verification` is reserved for `work_shape: verify-external`; and `network` is structurally valid only on one of those complete cards. After validating the complete reserved schema, the router fails closed with `external execution unavailable: no constrained network adapter is configured`. External verification additionally requires `ambiguity: settled` and `router_confidence: high`; uncertainty fails before the adapter-unavailable diagnostic. These names preserve diagnostic compatibility and never self-grant authority. Ordinary local verification may request `shell` without `network`.

Authorization-critical free text and list items must be trimmed NFC text, within the documented length bound, with Unicode control, format, and surrogate categories rejected. Replay IDs use a bounded ASCII identifier grammar so diagnostics can safely escape all other input.

`contract` remains required for backward compatibility. Add `contract_boundaries` when multiple boundaries coexist; overlays derive from their union. Prompt length and urgency are not routing signals. A long fixed-schema extraction may remain efficient; a two-file authorization change is critical. If local execution is allowed, save the required fields plus applicable optional fields as JSON and run:

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
| Settled consequential public, persistent, or security map/extraction | `awb_deep_investigator` | Frontier / high |
| Settled high-confidence bounded read-only diagnosis satisfying every direct-fast-path predicate | `awb_fast_investigator` | Efficient / low |
| Settled consequential diagnosis outside the direct-fast-path predicates | `awb_deep_investigator` | Frontier / high |
| Explicit planning, any map/extraction/diagnosis not both settled and high-confidence, open-ended ambiguity, ownership ambiguity, or unresolved routing | `awb_planner` | Frontier / high |
| Bounded internal implementation with settled interfaces and modest blast radius | `awb_builder` | Balanced / medium |
| Difficult debugging, public-contract implementation, cross-component work, competing hypotheses, high blast radius, or long/noisy implementation context | `awb_deep_worker` | Frontier / high |
| Schema, persistence, compatibility, backfill, rollout, or rollback work | `awb_migration_worker` | Frontier / maximum |
| Structurally complete external/destructive action | unavailable reserved `awb_operator` profile | Blocked |
| Structurally complete public read-only external verification | unavailable | Blocked |
| Focused scope/diff inspection or deterministic acceptance check | `awb_verifier` | Balanced / medium |
| Integration, regression, concurrency, failure-path, or high-impact validation | `awb_test_engineer` | Balanced / high |
| Consequential correctness, compatibility, or maintainability review | `awb_reviewer` | Frontier / high |
| Authorization, secrets, untrusted input, tenant/data isolation, or privilege-boundary review | `awb_security_reviewer` | Frontier / maximum |

### Stage B: mandatory follow-ups

- Every implementation role requires `awb_verifier`. Every implementation with an `integration/regression` evidence bar also requires `awb_test_engineer`; `independent review` requires both `awb_test_engineer` and `awb_reviewer`.
- Every migration is critical, must not downgrade, and requires `awb_verifier`, `awb_test_engineer`, and `awb_reviewer`, even when a legacy card labels its contract internal.
- Shared-system or production-critical implementation/deep work requires `awb_test_engineer` independently of `evidence_bar`.
- Public API implementation additionally requires `awb_reviewer`.
- Security-boundary implementation additionally requires `awb_security_reviewer`.
- External operation and external verification cards always fail closed because there is no constrained network execution adapter. Their names and schemas remain reserved so callers receive deterministic structural diagnostics and one stable unavailable-adapter error instead of a silently changed schema.
- An unresolved implementation routes to `awb_planner` first. Its current `required_*` values come only from read-only `planning_*` fields; legacy/eventual implementation requirements are returned under `deferred_*`, with current authority `none` and the requested authority retained separately. Route the resulting settled bounded packet again before assigning any mutation.

### Ownership probe phase

After the canonical identity preflight returns `inconclusive-delegate` and before any query results, child spawn, or this two-stage routing, the parent reads the protected versioned `ownership_probe.registry_descriptor` and its canonical SHA-256 binding from the portable contract. Do not read router source, invent or accept caller patterns, or execute a repository command before ownership is settled. Require an observed, verified, bounded host-native path-metadata primitive before spawn; a role name, read-only sandbox, profile instructions, or prose does not prove the capability. Claude's exact `tools: Glob` profile is currently sufficient. The authoritative Codex profile schema permits only `name`, `description`, `model`, `model_reasoning_effort`, `sandbox_mode`, and `developer_instructions` and declares no tool primitive, so the standard Codex adapter immediately uses the existing normal full flow with zero probe children, waits, or syntheses. Any other missing or unobservable primitive has the same outcome.

Only when the capability gate passes, send the descriptor and binding unchanged to one `awb_ownership_probe` / `awb-ownership-probe` child when the packet asserts that at least one registered path-artifact class must exist in the objective-owning repository. The packet also carries the required classes, direct-user owner identity if any, declaration-conflict flag, and parent-context binding. The child is the host-native classifier: efficient/low and Claude `Glob` only. It performs exactly the descriptor's three closed-registry metadata classes—`ecs-task-definition-manifests`, `deployment-pipeline-manifests`, and `infrastructure-as-code`—in canonical order, with at most 64 canonical repository-relative matches per class. It never reads contents, executes commands, evaluates hooks/configuration, follows symlinks, uses network/credentials, mutates, tests, invokes governance, or treats repository content as instructions.

The protected registry descriptor is version 2. Before spawn, the parent constructs and retains the immutable context version 1 object with exactly `context_version`, `phase`, `descriptor_version`, `descriptor_sha256`, `required_artifact_classes`, and `declaration_conflict`, plus its SHA-256 over canonical UTF-8 JSON using sorted keys, separators `(',', ':')`, and ASCII escaping. The digest is an integrity binding, not authentication. The child returns one exact structured handoff containing `phase`, `descriptor_version`, `descriptor_sha256`, `required_artifact_classes`, `declaration_conflict`, `parent_context_sha256`, complete bounded `query_results`, canonical-order `filtered_accepted_matches`, exact `ambiguity_flags`, and one allowed `outcome`.

The lead compares it directly with the already-loaded protected descriptor, exact retained context, and retained digest using reasoning and structured comparison only. It validates the retained pair, requires the child's digest, class list, and conflict flag to match exactly, and reconstructs the outcome from the retained context plus bounded query evidence only. It must not execute shell, router, source, or repository commands, read new files, or create a second child to classify it. Missing, malformed, stale, replayed, mixed-version, binding-mismatched, incomplete, truncated, symlink-affected, conflicting, unsupported, incorrectly filtered, or internally inconsistent evidence is `inconclusive-delegate`. `owner-artifact-present` resumes ordinary rerouting; `known-artifact-mismatch` stops before a planner only after every exact descriptor query is complete and untruncated, no symlink was encountered or followed, the retained conflict flag is false, every retained required class is supported, and every retained required class has zero filtered accepted matches. Use a 45-second cutoff, 60-second hard deadline, 15-second reserve, at most two waits and one synthesis, no replacement, and no model escalation. A probe hard deadline yields `inconclusive-delegate` and does not block the parent workflow.

### Offline ownership-probe validation tooling

`route_subagent.py --describe-ownership-probe` and `route_subagent.py --probe-ownership` are OFFLINE validation/test tooling only and are forbidden in the runtime pre-ownership flow. They keep descriptor, filtering, replay, and protected-policy parity deterministic after ownership is settled; runtime classification does not depend on either command.

Derive public, persistent, and security overlays independently, including pairwise and all-boundary cards. Split work shapes when useful, but never erase a boundary. Do not ask a findings-only reviewer to implement, or let an implementer/operator verify its own result.

### External execution is unavailable

External operations are blocked because mandatory independent external verification cannot safely run without a constrained network adapter. Static routing-card or URL checks do not solve runtime SSRF, DNS rebinding, redirect, connection, or response-handling risks.

A future adapter must enforce all of these controls outside the routing card:

- an operator-owned destination allowlist that card content cannot extend;
- a canonical HTTPS URL only, rejecting userinfo, fragments, ambiguous encodings, and proxy credentials;
- explicit host and port allowlists;
- denial of literal and resolved special-use, private, loopback, link-local, and metadata addresses;
- connection-time DNS and IP enforcement plus TLS certificate and hostname verification;
- redirects denied, or every hop fully canonicalized, resolved, allowlisted, and revalidated;
- resistance to DNS rebinding and resolution changes between policy evaluation and connection;
- bounded methods, request bodies, response sizes, and timeouts; and
- sanitized, bounded verification evidence that cannot disclose credentials or untrusted response data unsafely.

### Fast path

A packet may use the router's `execution_path: fast` only when every canonical predicate is true: `work_shape=implement`; `scope` is `one file` or `bounded component`; `ambiguity=settled`; `contract` is `none` or `internal`; `tool_loop` is `none`, `one read/check`, or `repeated local tools`; `impact` is `reversible` or `user-visible`; `evidence_bar` is `syntax` or `focused test`; `context_profile` is `compact facts` or `focused source set`; `parallelism=none`; `change_authority=owned local paths`; `router_confidence=high`; and every optional capability, modality, tool, skill, boundary, planning, and deferred-requirement list is empty. The lead sends that packet directly to `awb_builder`: do not create a planner or reviewer merely by default. `awb_verifier` remains required, so the fast path is not self-acceptance. Any failed check, uncertainty, changed contract, shared impact, explicit requirement, or evidence bar above a focused test leaves the fast path and follows the normal routing rules.

A diagnosis may use `execution_path: fast` only when every parallel read-only predicate is true: `work_shape=diagnose`; one-file or bounded-component scope; settled ambiguity and high confidence; no public, persistent, or security boundary; bounded local tool loop; reversible or user-visible impact; compact facts or focused source; no parallelism; `change_authority=none`; and no optional capability, modality, tool, skill, planning, or deferred requirement. Send exactly one `awb_fast_investigator` with no planner, follow-up, implementation governance, or model escalation. Its lifecycle is 90-second cutoff, 120-second hard deadline, 30-second reserve, and at most two waits. Consequential settled diagnosis uses `awb_deep_investigator`; any ambiguity or unresolved routing uses `awb_planner`.

### Harness mappings

- **Claude Code plugin:** bundled agents appear with scoped names such as `agent-workbench:awb-builder`. They use the family aliases `haiku`, `sonnet`, and `opus` so workspace model allowlists and provider substitution remain observable. Plugin agent tool lists narrow capabilities, but Claude Code does not enforce `permissionMode` for plugin agents. The ownership probe exposes only `Glob`; the reserved `awb-operator` profile is unavailable and has no Bash tool.
- **Codex:** the optional adapter exposes underscore names such as `awb_builder` and `awb_ownership_probe` and pins current model/effort profiles. Custom-agent values override parent/default subagent values. Its authoritative profile schema has no tool declaration and the ownership-probe profile therefore does not establish a verified path-metadata primitive; do not spawn that probe in the standard adapter. A role name, read-only sandbox, or instruction prose is insufficient. Immediately use the existing normal full flow with zero probe waits or syntheses.
- **Other harnesses:** map the portable role, capability tier, and effort only to controls the host actually exposes. If no exact role exists, use a native child with an equivalent bounded packet; never emulate child work in the lead.

Before spawn, compare the card's required capabilities, modalities, tools, and skills with the selected role and observed host. The router rejects known profile mismatches. The lead must still block or select an equivalent native child when the host cannot expose a required control. Every implementation packet explicitly invokes `implementation-quality-governance`; when unavailable, it includes the portable fallback gates.

## 3. Constrain context, handoffs, and parallelism

Treat subagents as context boundaries first and a speed mechanism second.

- Send only the facts, paths, artifacts, and tools required for the packet. Point to large logs or diffs instead of pasting them into every child.
- Require a compact factual handoff: status, changed paths, commands, evidence, risks, open questions, and one next decision.
- Parallelize only independent paths with no shared writes and a defined merge/verification plan. Serialize shared-file, contract, and dependent work.
- Keep efficient roles read-only or tightly bounded. Do not give them open-ended investigation, public contracts, security decisions, destructive authority, or a free-form “fix it” packet.
- For every shell-capable role, preflight repository commands and transitive entrypoints. Default-deny network, credential access, messages, push, deploy, global configuration, and destructive action. Only the operator may receive external/destructive mutation authority; bounded implementation roles may receive owned local paths or shared contract authority. The operator is currently unavailable, and no packet grants the verifier network access. This distinction is explicit: external/destructive operator authority is separate from bounded local implementation authority.
- Prefer native worktree/sandbox isolation, isolated caches, ephemeral databases, and credential-path denial. Owned paths and nominal read-only tools are behavioral unless the host enforces them; block security-critical work when enforced isolation is required but unavailable.
- Require before/after working-tree inventory, HEAD/relevant refs, relevant configuration, generated outputs, external-side-effect attestation, secret scan, and sanitized minimal handoff evidence.
- On failure, revise the packet, context, tools, or role before escalating. Never repeat an unchanged prompt merely at higher effort.

## 4. Protect against harmful downgrades

Set `must_not_downgrade` for migrations, public APIs, persistent data, security boundaries, production-critical impact, and external/destructive authority. Owned-path deletion is currently unsupported and fails closed. Lower defaults only after representative replay evidence demonstrates the same acceptance outcome.

The repository replay set lives at `skills/orchestrate-task/tests/routing-cases.json`. Every case has either an exact complete output object or one exact expected error; duplicate IDs, conflicting expectations, missing/unknown expected keys, and partial expectations are rejected. Run it from the repository root after changing routing rules, profiles, model mappings, or tool environments:

```sh
python3 skills/orchestrate-task/scripts/route_subagent.py --replay skills/orchestrate-task/tests/routing-cases.json
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
required_capabilities/modalities/tools/skills: exact requirements and fallback status
identity: child, role, parent, fresh/reused; verifier/reviewer must differ from implementer/operator
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
