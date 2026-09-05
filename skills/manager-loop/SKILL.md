---
name: manager-loop
disable-model-invocation: true
description: Coordinate long-horizon builds through a manager and a persistent implementer, using a phased checklist, evidence-based phase acceptance, and stall recovery. MANUAL TRIGGER ONLY. Use only when the user explicitly invokes $manager-loop or /agent-workbench:manager-loop; never infer it from a general request for a substantial or autonomous build.
---

# Manager Loop

Keep the whole objective in the manager's context and only the current phase in the implementer's active assignment. Complete each phase **extremely well**: meet its acceptance criteria, verify the result, and advance without chasing optional perfection.

This workflow adapts the user-supplied X post about long-horizon Astra builds. Its performance claims, wording preference, dashboard heuristic, and 96-agent example are practitioner observations, not measured guarantees or required settings.

## Establish the run

1. Capture the desired outcome, constraints, existing work, and observable definition of completion. Ask only about missing decisions that materially affect the result; continue independent preparation while waiting. A planning-only request produces a plan, not an execution run.
2. Build a comprehensive checklist grouped into dependency-ordered phases. Give each item a stable ID, a concrete deliverable, and acceptance evidence. Cover integration, failure paths, validation, and delivery, not just implementation. Detail the next phase first; keep later phases coarse until their prerequisites clarify them. Avoid a giant speculative task inventory.
3. Give each phase entry conditions, owned paths or responsibility, exit criteria, required checks, and dependencies. Separate required outcomes from optional polish. Choose the smallest phase that produces a coherent, verifiable result.
4. Persist the plan and run state in a task-owned directory under the authorized workspace, outside installed skill files. Use an existing project convention when available. Record the objective, phase and item IDs, plan revision, current phase, agent identities, pending decisions, evidence locations, and next action. Keep one writer per artifact; the manager owns acceptance and plan revisions, while the implementer owns its progress report and dashboard.
5. Record a stall interval and a bounded recovery allowance. If the user supplies none, start with 20 minutes without a completed item **or substantive new evidence**, and two changed approaches per stalled item after its initial approach. Count a recovery when a materially different approach is dispatched; ordinary checks within that approach do not consume another recovery. Separately allow at most two corrections after a rejected phase handoff. A dispatch serving both purposes consumes both allowances. Adjust the interval up front for known long builds or experiments. These are checkpoint heuristics, not reasons to abandon valid work. Honor any stricter host or project limits and explicit user budget; do not invent a native token budget.

## Bind to available agent controls

- Prefer one reusable implementer with a separate context and bidirectional messaging. Use internal subagents for subtasks of the current request. Create a separate user-visible task only when the user explicitly requests one and the host permits it; invoking this skill alone does not grant that permission. Observe whether agents share a checkout or use isolated worktrees, and specify file ownership and integration responsibility accordingly.
- Use only tools exposed by the current host. Record the actual implementer ID returned at creation; do not guess IDs or confuse setup IDs with ready task IDs. Reuse the implementer between phases when supported. Otherwise hand a replacement the saved state, preserving retry counts and unresolved work.
- Activate native goal mode only when explicitly requested by the user or authorized by higher-priority instructions and supported by the host. Inspect an existing goal before creating another. When authorized, the manager's goal covers the whole outcome and the implementer's goal covers only the assigned phase. Ask the implementer to use its own goal tools and report the result. Sending the text `/goal` is not proof of activation.
- If goal controls are unavailable or unauthorized, use the same phased workflow with ordinary agent turns and durable state; state that native goal mode is inactive. Do not promise execution after the current session ends. Scheduling or background wakeups require a separate user request and supported host controls.
- If delegation is unavailable, save the plan and explain that the two-agent loop cannot run here. Do not claim that one agent role-playing both roles supplies independent context or verification.
- Keep the configured model unless the user requests a change or applicable routing instructions require one. Start with manager plus implementer; let the implementer delegate only genuinely independent, bounded work within actual capacity. Never change global concurrency or assume 96 agents are available. All workers share the same scope and budget boundaries and must preserve other workers' changes.

## Run one phase at a time

The manager coordinates, resolves scope decisions, evaluates evidence, and selects the next phase. The implementer performs the assigned work and checks. If another applicable orchestration workflow imposes stronger delegation or review requirements, preserve them; this workflow cannot relax those gates or reset their budgets.

1. Send a phase packet using [the handoff templates](references/handoffs.md). Include the objective summary, current phase only, prerequisite evidence, owned files, acceptance criteria, validation, authorized actions, stall policy, and artifact paths. Include explicit permission for bounded internal delegation if useful. Do not ask the implementer to create another manager loop.
2. Have the implementer acknowledge scope and proceed until the phase is ready for acceptance or encounters a concrete blocker. Require progress updates when an item finishes, meaningful evidence changes the plan, or a blocker appears. The manager should use bounded waits or completion events, avoid unchanged polling, and keep the user informed of meaningful progress.
3. At handoff, inspect the deliverables and relevant check results against the exit criteria. An implementer's completion statement or checked box is a claim, not acceptance. Use an independent verifier when required by the task's risk or governing instructions. Where the manager is restricted to orchestration, delegate evidence inspection as well.
4. Accept only when required phase items have current evidence. Otherwise return one focused correction packet identifying the failed criterion and required result, within remaining applicable recovery limits. Preserve all attempt counts across replacements and context compaction.
5. After acceptance, update the manager ledger, reconcile any revised dependencies, and dispatch the next ready phase without requesting routine confirmation. Stop expanding finished work for optional refinements. Never advance a dependent phase over an unmet prerequisite.

## Recover useful progress

When the stall interval expires, request the current hypothesis, attempts, evidence, blocker, and next smallest experiment. A legitimate running check or a newly narrowed cause can justify continued work with a concrete next checkpoint; chart flatness alone does not prove a stall.

If no useful evidence is emerging, change approach, split the item into verifiable substeps, or park it visibly and work on an independent item within the assigned phase. Crossing a phase boundary requires the manager to revise the plan or explicitly dispatch an independent phase after checking its prerequisites; the implementer never widens its own assignment. Record why, what remains required, and the unblock condition. Splitting an item must preserve the original requirement and history; do not manufacture completions to improve the counter.

After the recovery allowance is exhausted, stop retrying that item and report the blocker. Continue only work that does not depend on it. If all remaining required work is blocked, preserve a resumable handoff and surface the exact missing input or capability. A workflow blocker and a host goal status are different: follow the goal tool's own rules before changing native status. Never mark a goal complete to escape a limit.

On user cancellation, stop dispatching work, interrupt active children where supported, save partial state, and report any work that could not be stopped. A later resume starts from the saved state after checking live artifacts and agent status; it does not silently reset recovery counts or duplicate running workers.

## Make progress visible

For substantial runs, have the implementer create a simple local HTML checklist dashboard early and update it at progress events. The manager must not polish this dashboard as a separate product. Read [the dashboard contract](references/handoffs.md#dashboard-contract) when creating it. If HTML is infeasible, maintain the same data in Markdown and disclose that fallback.

Show the full phased checklist, completed/total count, blocked items, current phase, last update, and a timestamped chart of completed boxes over time. Keep acceptance evidence linked and distinguish implementer completion from manager acceptance. Counts are navigation aids, not an estimate of equal effort or proof of readiness.

## Finish the run

Reconcile every required item with the original outcome, inspect the integrated final result, and run required final checks after the last material change. Reopen items invalidated by integration. Report delivered outcomes, evidence, unresolved requirements, and any optional deferred work. Do not call a partial or blocked objective complete.

Follow the user's commit and publication instructions. The loop itself grants no permission to push, deploy, send external messages, change configuration, or incur additional costs beyond the authorized task. Mark an authorized native goal complete only after its actual objective is achieved; respect host-specific status semantics.
