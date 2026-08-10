# Model Selection and Thinking Effort

Use this reference only when the current harness exposes model, reasoning-effort, or execution-mode controls. It is a routing policy, not permission to change a user pin, spend limit, provider configuration, or harness default.

## 1. Classify before selecting

Record the task's highest applicable class. Classify by the work required, not by the length of the prompt.

| Class | Signals | Default capability tier | Default effort |
| --- | --- | --- | --- |
| Deterministic | A local tool or fixed procedure can produce and verify the answer. | No model or efficient | None or low |
| Routine | Narrow scope, stable inputs, reversible outcome, fixed schema or clear edit. | Efficient | Low |
| Bounded | Several related steps, known interfaces, modest ambiguity, ordinary code or analysis. | Balanced | Medium |
| Complex | Novel diagnosis, broad context, cross-system constraints, sustained tool use, or consequential review. | Frontier | High |
| Critical | Security, authorization, migration, financial or production-impacting decision, or difficult work where a missed defect has material cost. | Frontier plus independent verification | High, then maximum only if justified |

Raise the class when any of these are true: the task requires a modality unavailable to a lower tier, the model must make autonomous tool choices, the context is large or contradictory, a false positive or negative is costly, or the result must meet a strict proof, test, or evidence bar. Do not raise it merely because the task is urgent or the prompt is long.

## 2. Map the tier to the current harness

- **Efficient**: the least expensive and lowest-latency exposed model that supports the required context, modality, tools, and structured output.
- **Balanced**: the provider's general-purpose, strong model for normal implementation, analysis, and review.
- **Frontier**: the provider's strongest generally available model for difficult reasoning, long-horizon coding, or high-consequence analysis.

Use provider model IDs only after the harness exposes them. Do not infer a name, capability, price, context limit, reasoning setting, or entitlement from documentation, a role label, or a previous task. If no tier can be observed, write the desired tier and continue without claiming the harness applied it.

## 3. Set effort separately from the model

Choose the smallest effort that can meet the evidence bar. Effort changes internal work, tool-call behavior, latency, and cost; it is not a visible-answer-length control.

- **None / low**: deterministic transformations, straightforward classification, extraction to a validated schema, quick lookup, or focused code navigation. Keep a deterministic verifier where possible.
- **Medium**: default for bounded multi-step work, ordinary implementation, focused debugging, and routine code review.
- **High**: use for hard debugging, non-trivial design tradeoffs, agentic coding with tool loops, broad review, research synthesis, or significant ambiguity.
- **Maximum**: reserve for the hardest quality-first work with a concrete evaluation or verification plan: critical security or migration review, complex optimization, or a difficult defect that lower effort demonstrably missed. Use a provider's equivalent quality-first mode only when the extra latency and cost are authorized.

For a long cached conversation, avoid changing effort midstream unless the expected quality gain exceeds the lost cache efficiency. If the provider adapts reasoning automatically, treat the requested effort as a preference and still measure the outcome.

## 4. Escalate and de-escalate from evidence

Start at the class default unless a user pin, policy, or prior evaluation says otherwise.

Escalate one dimension at a time after checking the packet, inputs, tool results, and verifier. Escalate the **model tier** for missing capability, context, modality, or persistent reasoning failure. Escalate **effort** when the same capable model needs more exploration or verification. Prefer a better packet, smaller context, deterministic tool, or independent reviewer when that addresses the cause.

De-escalate after representative tasks meet the acceptance bar at a lower tier or effort. Do not generalize from one easy success. Keep separate baselines for materially different task classes, modalities, and tool environments.

Do not retry unchanged work at a higher tier, fan out expensive workers before the work is independently divisible, or use maximum effort as a substitute for missing requirements, weak tests, or unclear authorization.

## 5. Record the decision and learn

For a consequential, repeated, or costly task, keep this compact routing record in the lead ledger:

```text
task_class: routine | bounded | complex | critical
signals: ambiguity, context, modality, tool autonomy, impact
capability_tier: efficient | balanced | frontier | unavailable
effort: none | low | medium | high | maximum | unavailable
user_or_policy_pin: none | description
reason: concise selection rationale
evidence: acceptance result, verifier outcome, latency, token/cost telemetry when available
next_adjustment: retain | lower tier | raise effort | raise tier | redesign packet
```

Evaluate representative tasks with the actual prompts, tools, and data. Compare task success, correctness, completeness, edge cases, required evidence, latency, token usage, and cost. Choose the configuration with the lowest total cost that meets the quality bar; lower model cost is not a win if it increases retries, review failures, or human repair.

## Research basis

This provider-neutral policy follows a common current pattern in first-party guidance: select for capability, speed, and cost; tune reasoning effort separately; and validate on representative evaluations rather than assuming the highest setting wins. Provider-specific names, defaults, limits, and pricing change frequently; consult the current host documentation before creating an adapter.

- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Anthropic: choosing a model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
- [Anthropic: effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Google: Gemini thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
