# Output contract

Prepare a candidate for `docs/tech-stack-standards.md` under the confirmed repository root. On the
current Codex and Claude plugin surfaces this contract is draft-only: the skill does not write,
replace, or roll back the canonical target because those hosts do not expose the required
exclusive conditional writer. A separately authorized human or host-owned writer may apply a
validated candidate after revalidating this contract. The candidate must use this order:

1. `# Tech Stack Standards`
2. Purpose and precedence statement: advisory AI-agent context that cannot override host
   instructions, repository-local contracts, maintainers, tests, policies, or source code.
3. `## Run Scope and Limitations`: run type, checked date, discovery/research budgets, inspected
   roots, exclusions, offline/source constraints, and known uncertainty.
4. `## Detected Stack`: one row per component with role, name, declared version, resolved version,
   runtime version, confidence, delta, and repository evidence.
5. `## Change Summary`: complete `added`, `changed`, `removed`, `renamed`, and `unchanged` lists;
   use `None` explicitly for empty classes.
6. Linked table of contents for current component sections.
7. One section per current component with Overview, Applicability, Best Practices, Common
   Pitfalls, and Sources.
8. `## Retained Manual Content` when a removed or renamed component's manual block no longer has a
   natural current section.
9. `## Generation Record`: checked date, full/partial/no-op trigger, refreshed/retained/blocked
   components, and limits. Do not claim freshness beyond the recorded evidence scope.

## Evidence and citation grammar

- Repository evidence must be a repository-relative path plus stable locator, never an absolute
  path: ``package.json` (`dependencies.react`)`` or
  ``.github/workflows/validate.yml` (`jobs.validate`)``.
- End each generated practice and pitfall with one or more direct supporting Markdown links. Keep
  citations adjacent to the supported claim rather than relying on a section bibliography. These
  are claim-level citations, not section-level attribution.
- For every distinct web source, include a Sources record with publisher, page title/topic,
  canonical public URL, version applicability, authority type (`primary` or labeled `secondary`),
  and checked date.
- Use `not declared`, `not resolved`, `not observed`, or `unknown` rather than inventing versions.
  Confidence is exactly `runtime-observed`, `resolved`, `declared`, or `unknown`.
- Delta is exactly `added`, `changed`, `removed`, `renamed`, or `unchanged`. A rename record names
  both identities and cites the evidence connecting them.

## Manual-content preservation

Manual content is opt-in and delimited by a unique stable identifier:

```markdown
<!-- BEGIN MANUAL: deployment-notes -->
This text is maintained by people and is not regenerated.
<!-- END MANUAL: deployment-notes -->
```

Treat each complete block, including markers and all intervening bytes, as opaque manual content.
Preserve it byte-for-byte. Do not normalize whitespace, links, headings, identifiers, or line
endings inside a block. IDs must use lowercase ASCII letters, digits, and hyphens, be unique, and
match across the pair. Reject nested, duplicate, unmatched, reversed, or malformed markers and
stop without writing.

Keep a block in its existing component when that component remains. If generated headings change,
place the intact block at the corresponding semantic position without changing block order. If
the component is removed or the mapping is ambiguous, move the intact block to Retained Manual
Content, label its former generated component outside the block, and disclose the move. Never
discard a block because its surrounding generated section became stale.

## Pre-write validation

Reject the draft unless:

- every current component has exactly one Detected Stack row and section;
- every prior/current component has exactly one delta classification;
- all version cells and confidence values follow the grammar and expose conflicts;
- every generated practice/pitfall has adjacent applicable-source support;
- all repository citations are relative and all public URLs are sanitized;
- every extracted manual block appears exactly once with identical bytes;
- no private/sensitive material is present; and
- headings, anchors, source records, run scope, and advisory precedence are internally consistent.

## Future host-owned application (not performed by this skill)

The following procedure is retained as requirements for a future host-owned writer. It is not an
invocation instruction for this skill. The current skill must stop before step 1 can mutate or
replace a target and must report `not applied`.

1. Resolve the trusted repository root independently, open and `fstat` a trusted root directory
   descriptor, and derive the fixed `docs/tech-stack-standards.md` path only from that descriptor.
   Walk to the `docs` parent descriptor one component at a time with descriptor-relative,
   no-follow directory opens; `fstat` every descriptor and require an expected-owner directory.
   Reject traversal, a changed descriptor identity, an out-of-root target,
   a symlink, or any special file. If `docs` is absent, create it only through an authorized
   descriptor-relative safe operation, then open and validate its descriptor again.
2. Before reading an existing target, open its final name relative to the trusted parent descriptor
   without following links and `fstat` the resulting descriptor. Require a regular file with a single link owned by the
   expected owner; reject symlinks, hard-linked files, devices, sockets, FIFOs, and other special files. Snapshot its
   exact bytes plus a cryptographic digest and complete file identity
   and version metadata. For an absent target, snapshot that absence through the same parent
   descriptor.
3. Acquire a host-provided exclusive conditional-replacement guarantee that covers the target
   contents and parent namespace from snapshot through replacement. A check followed by a normal
   rename is insufficient: it can overwrite a same-inode concurrent manual edit or follow a parent
   substitution. If this guarantee is unavailable, stop without writing and report the limitation.
4. Create the complete validated draft as a new regular temporary file through the trusted parent
   descriptor using descriptor-relative exclusive creation and restrictive default permissions.
   Flush it when supported, re-open it without following links, `fstat` it as a regular file with a single link owned
   by the expected owner, and validate the exact bytes. Do not overwrite through a followed path.
5. Immediately before replacement, re-`fstat` the root and parent descriptors and re-open the
   target descriptor without following links when the snapshot had a target; otherwise revalidate
   its absence through the trusted parent descriptor. Require the same trusted parent identity and
   the same regular-file-with-a-single-link and expected-owner properties when present. Compare the
   target's complete identity/version and exact digest to the snapshot, or confirm it remains absent;
   abort if it changed, including a same-inode content modification. Perform an atomic same-directory replace only by
   a descriptor-relative operation covered by the conditional-replacement guarantee;
   an absent snapshot must fail rather than overwrite if a target appeared.
6. Re-open the final target relative to the trusted parent descriptor without following links and
   `fstat` it before and after reading. Require a regular file with a single link owned by the
   expected owner, validate the final bytes, compare every manual block to the pre-edit snapshot,
   and inspect the exact repository diff. Report unexpected or unrelated changes; never clean or
   revert user work. If this run's replacement must be rolled back after a failed post-write
   check, do so only with a host-provided exclusive conditional-replacement guarantee covering the
   target and parent namespace, after re-opening the target without following links and proving by
   complete identity/version metadata and exact digest that it is exactly the artifact written by
   this run. If that guarantee or proof is unavailable, abort the rollback, preserve the current
   target, and report the unsafe state; never use an automatic or path-based rollback.

Forward regression coverage for an implementation of this procedure must demonstrate that it
aborts without replacement when (a) another writer modifies the original target in place while
preserving its inode, and (b) another actor substitutes the `docs` parent between snapshot and
replacement. It must also demonstrate that, after this run has replaced the target, another writer
edits that replacement before a post-write validation failure: the rollback must abort and preserve
the other writer's bytes. Exercise all races against the descriptor-relative path; a path-only or
identity-only test is insufficient.

An approved patch/edit tool may be used only when its filesystem guarantees meet these checks and
the final diff is inspected. A successful save proves only that this advisory artifact passed the
recorded structural and evidence checks; it does not authorize or implement its recommendations.
