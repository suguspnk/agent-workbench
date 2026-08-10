# Model Selection and Thinking Effort

Use this reference only when the current harness exposes model, reasoning-effort, or execution-mode controls for child tasks. It is a subagent-routing policy, not permission to change the lead task's model, a user pin, spend limit, provider configuration, or harness default.

## 1. Fill a routing card before selecting

Classify each child packet, not the parent request. Record the values that materially change quality, latency, or risk:

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

The lead must not use prompt length or urgency as a proxy for any field. A long extraction job can stay cheap; a two-file authorization change can require the strongest route. Treat noisy artifacts, shared contracts, external/destructive authority, and unresolved routing as escalation signals even when the diff is small.

## 2. Choose the exact child role

Apply the first matching rule. The roles below are supplied by the optional Codex adapter; use the corresponding native child capability when another harness exposes an equivalent.

| Condition | Child role | Model / effort | Required follow-up |
| --- | --- | --- | --- |
| Read-only map, extraction, classification, or fixed-schema evidence; settled inputs; no design decision; no security or public-contract boundary | `awb_fast_investigator` | Luna / low | Include exact source paths or structured output validation |
| Architecture, ownership, dependency order, or acceptance criteria are not settled | `awb_planner` | Sol / high | Feed a bounded plan to a separate worker |
| Bounded internal implementation; known interface; reversible; focused tests; no unresolved failure hypothesis | `awb_builder` | Terra / medium | `awb_verifier` |
| Multi-component refactor, public API contract, hard diagnosis, competing hypotheses, repeated tool loop, or noisy context that must be distilled | `awb_deep_worker` | Sol / high | `awb_test_engineer` or `awb_reviewer` |
| Schema, persistence, compatibility, backfill, rollout, or rollback work | `awb_migration_worker` | Sol / extra high | `awb_test_engineer` and `awb_reviewer` |
| Independent scope/diff check, deterministic validation, or focused acceptance check | `awb_verifier` | Terra / medium | Return commands and actual outputs |
| Integration, regression, concurrency, or failure-path validation | `awb_test_engineer` | Terra / high | Return coverage gaps and residual risk |
| Consequential correctness, compatibility, or maintainability review | `awb_reviewer` | Sol / high | Findings only; no fixes |
| Authorization, secrets, untrusted input, tenant/data isolation, or privilege-boundary review | `awb_security_reviewer` | Sol / extra high | Findings only; include negative-test gaps |

If rules conflict, prefer the highest-risk condition. Split a mixed packet instead of assigning one broad role: for example, route discovery to `awb_planner`, the migration to `awb_migration_worker`, and security review to `awb_security_reviewer`.

## 3. Constrain context, handoffs, and parallelism

Treat subagents as context boundaries first and a speed mechanism second.

- Send only the source paths, facts, and tools needed for the packet. Put a large log, diff, or artifact at an exact path; do not paste it into every child packet.
- Require a short, factual handoff: status, changed paths, commands, evidence, open questions, and one next decision. Separate observations from recommendations.
- Start one child when work is sequential, capacity is constrained, or one packet determines the next. Parallelize only independent paths with no shared writes and a defined merge/verification plan.
- Keep an efficient role read-only or tightly bounded. Do not give it open-ended investigation, public contracts, security decisions, destructive authority, or a free-form “fix it” instruction.
- When a child fails, revise the packet, context, tool surface, or role first. Do not treat a higher tier as the automatic retry.

## 4. Protect against harmful downgrades

Escalate immediately when a packet crosses a risk boundary or fails its evidence bar. Lower a default only after a replay set shows that a cheaper profile preserves the required outcome.

Maintain a living replay set with known hard cases, easy-but-long inputs, recent failures, ordinary successful packets, irreversible/high-risk work, and cases that changed profile after a routing-policy update. Record an acceptable role range, `must_not_downgrade` flag, required checks, and outcome criteria for each case.

Track both unnecessary escalation (cost without accepted-result gain) and harmful downgrade (a cheaper route that misses the evidence bar, needs recovery, or creates human repair). Prioritize harmful downgrades over savings, and rerun the replay set when routing instructions, profiles, models, or tool environments change.

## 5. Classify the baseline tier

Record the task's highest applicable class. Classify by the work required, not by the length of the prompt.

| Class | Signals | Default capability tier | Default effort |
| --- | --- | --- | --- |
| Deterministic | A local tool or fixed procedure can produce and verify the answer. | No model or efficient | None or low |
| Routine | Narrow scope, stable inputs, reversible outcome, fixed schema or clear edit. | Efficient | Low |
| Bounded | Several related steps, known interfaces, modest ambiguity, ordinary code or analysis. | Balanced | Medium |
| Complex | Novel diagnosis, broad context, cross-system constraints, sustained tool use, or consequential review. | Frontier | High |
| Critical | Security, authorization, migration, financial or production-impacting decision, or difficult work where a missed defect has material cost. | Frontier plus independent verification | High, then maximum only if justified |

Raise the class when any of these are true: the task requires a modality unavailable to a lower tier, the model must make autonomous tool choices, the context is large or contradictory, a false positive or negative is costly, or the result must meet a strict proof, test, or evidence bar. Do not raise it merely because the task is urgent or the prompt is long.

## 6. Map the tier to the current harness

- **Efficient**: the least expensive and lowest-latency exposed model that supports the required context, modality, tools, and structured output.
- **Balanced**: the provider's general-purpose, strong model for normal implementation, analysis, and review.
- **Frontier**: the provider's strongest generally available model for difficult reasoning, long-horizon coding, or high-consequence analysis.

Use provider model IDs only after the harness exposes them. Do not infer a name, capability, price, context limit, reasoning setting, or entitlement from documentation, a role label, or a previous task. If no tier can be observed, write the desired tier and continue without claiming the harness applied it.

### Codex adapter mapping

The optional Codex adapter encodes the tiers as named child roles: `awb_fast_investigator` for efficient/low, `awb_builder` for balanced/medium, `awb_deep_worker` for frontier/high, and `awb_migration_worker` or `awb_security_reviewer` for extra-high-risk work. It also provides `awb_planner`, `awb_verifier`, `awb_test_engineer`, and `awb_reviewer`. The lead task remains unchanged. Use these names only after the adapter has been installed and the configured models are available.

## 7. Set effort separately from the model

Choose the smallest effort that can meet the evidence bar. Effort changes internal work, tool-call behavior, latency, and cost; it is not a visible-answer-length control.

- **None / low**: deterministic transformations, straightforward classification, extraction to a validated schema, quick lookup, or focused code navigation. Keep a deterministic verifier where possible.
- **Medium**: default for bounded multi-step work, ordinary implementation, focused debugging, and routine code review.
- **High**: use for hard debugging, non-trivial design tradeoffs, agentic coding with tool loops, broad review, research synthesis, or significant ambiguity.
- **Maximum**: reserve for the hardest quality-first work with a concrete evaluation or verification plan: critical security or migration review, complex optimization, or a difficult defect that lower effort demonstrably missed. Use a provider's equivalent quality-first mode only when the extra latency and cost are authorized.

For a long cached conversation, avoid changing effort midstream unless the expected quality gain exceeds the lost cache efficiency. If the provider adapts reasoning automatically, treat the requested effort as a preference and still measure the outcome.

## 8. Escalate and de-escalate from evidence

Start at the class default unless a user pin, policy, or prior evaluation says otherwise.

Escalate one dimension at a time after checking the packet, inputs, tool results, and verifier. Escalate the **model tier** for missing capability, context, modality, or persistent reasoning failure. Escalate **effort** when the same capable model needs more exploration or verification. Prefer a better packet, smaller context, deterministic tool, or independent reviewer when that addresses the cause.

De-escalate after representative tasks meet the acceptance bar at a lower tier or effort. Do not generalize from one easy success. Keep separate baselines for materially different task classes, modalities, and tool environments.

Do not retry unchanged work at a higher tier, fan out expensive workers before the work is independently divisible, or use maximum effort as a substitute for missing requirements, weak tests, or unclear authorization.

## 9. Record the decision and learn

For a consequential, repeated, or costly child task, keep this compact routing record in the lead ledger:

```text
task_class: routine | bounded | complex | critical
signals: ambiguity, context, modality, tool autonomy, impact
context_profile: compact | focused | noisy | long-running
parallelism: sequential | independent-read-only | independent-write | dependent
must_not_downgrade: yes | no, with reason
capability_tier: efficient | balanced | frontier | unavailable
effort: none | low | medium | high | maximum | unavailable
user_or_policy_pin: none | description
reason: concise selection rationale
evidence: acceptance result, verifier outcome, latency, token/cost telemetry when available
next_adjustment: retain | lower tier | raise effort | raise tier | redesign packet
```

Evaluate representative tasks with the actual prompts, tools, and data. Compare task success, correctness, completeness, edge cases, required evidence, latency, token usage, and cost. Choose the configuration with the lowest total cost that meets the quality bar; lower model cost is not a win if it increases retries, review failures, or human repair.

## Research basis

This provider-neutral policy follows a common current pattern in first-party guidance: select for capability, speed, and cost; tune reasoning effort separately; and validate on representative evaluations rather than assuming the highest setting wins. It also incorporates recurring practitioner reports: use subagents to bound context, keep low-tier workers narrowly scoped, and prevent cost-driven downgrades until replay evidence supports them. These reports are directional experience data, not a substitute for local measurement. Provider-specific names, defaults, limits, and pricing change frequently; consult the current host documentation before creating an adapter.

- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Anthropic: choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
- [Anthropic: effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Google: Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
- [Codex user discussion: custom subagent roles](https://www.reddit.com/r/codex/comments/1tkpquf/how_i_set_up_custom_subagents_for_codex/)
- [Practitioner discussion: routing regressions and harmful downgrades](https://www.reddit.com/r/AI_Agents/comments/1ub1vl0/routing_agent_work_across_4_llm_tiers/)
- [Practitioner discussion: bounded worker contracts and context](https://www.reddit.com/r/AI_Agents/comments/1so3bs1/sub_agents_with_cheap_model/)
