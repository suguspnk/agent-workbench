# Deterministic Scope Selection

The selector consumes collected facts and returns one target plus ordered overlays. It performs no Git, GitHub, network, or filesystem discovery.

## Collect facts without side effects

When no target is explicit:

- On an attached branch, use `gh pr view --json number,baseRefName,headRefName,headRefOid,files` to probe the current branch association. A successful “no pull request” response is conclusive absence only when it is distinguishable from authentication, network, tool, and parsing failures.
- At detached HEAD, read `git rev-parse HEAD`, list candidate PR metadata with a read-only GitHub query, filter exact `headRefOid` matches, and require uniqueness.
- For a selected PR, record its patch using a read-only diff query and retain the number, base ref, head ref, head OID, and file list.
- For local scope, collect `git diff --name-only`, `git diff --cached --name-only`, and `git ls-files --others --exclude-standard`, preserving the three inventories separately. Inspect both tracked diffs and each enumerated untracked file.
- When the selected patch changes or deletes package dependencies or source imports, collect the pre-change values from the PR base or local diff preimage into `before_manifests`/`before_imports` and the post-change values into `manifests`/`imports`. Do not treat an uncollected preimage as evidence that nothing was removed.

Do not run GitHub review/comment/merge commands. Discovery failure returns `pr-discovery-unavailable`; it never becomes local fallback.

## Scope card

Use Python 3.11 or newer. The JSON object has exactly:

```json
{
  "target_request": {"kind": "auto"},
  "git": {"branch": "feature-or-null", "head_oid": "commit-oid"},
  "pr_probe": {"status": "ok", "candidates": []},
  "local_changes": {"staged": [], "unstaged": [], "untracked": []},
  "workspace_files": [],
  "manifests": [{"path": "package.json", "dependencies": []}],
  "before_manifests": [{"path": "package.json", "dependencies": []}],
  "imports": {"src/file.ts": ["module-specifier"]},
  "before_imports": {"src/file.ts": ["module-specifier"]},
  "overlay_override": "auto"
}
```

`target_request` is one of `{"kind":"auto"}`, `{"kind":"local"}`, or `{"kind":"pr","pr":PR}`. A `PR` has exactly `number`, `base_ref`, `head_ref`, `head_oid`, `files`, and `patch`. `patch` is a string and may be empty for a valid zero-diff PR response. `pr_probe.status` is `ok` or `unavailable`; unavailable probes contain no candidates.

`workspace_files` enumerates the relevant package/config evidence needed for the selected changed files, not arbitrary unrelated repository contents. Each `manifests` entry contains the post-change declared dependency names. Optional `before_manifests` contains the corresponding pre-change names when the patch changes or removes dependencies. `imports` contains post-change statically observed module specifiers for selected changed source files; optional `before_imports` contains their pre-change specifiers. Omit the optional fields when no pre-change evidence is available. The selector reports only set differences as normalized `removed-dependency:` and `removed-import:` evidence.

Paths are repository-relative and normalized by the selector. Raw manifest paths or import-map keys that normalize to the same path, including `./` and slash/backslash aliases, make the card ambiguous and are rejected rather than overwritten.

`overlay_override` is `auto`, `{"add":[IDs]}`, or `{"exact":[IDs]}`. Known IDs are `javascript-typescript`, `node-nestjs`, `react-nextjs`, and `react-native`. The result records normalized `caller-override:add`, `caller-override:exact`, and specialist-to-JavaScript/TypeScript implication evidence.

Run:

```sh
python3.11 "$SKILL_ROOT/scripts/select_review_scope.py" --card /path/to/scope-card.json
```

The output reports selection status/reason, exactly one target or `null`, selected changed files, overlays in fixed order, and normalized evidence per overlay. `needs_input` stops the review until the target is resolved.

## Detection rules

Use the nearest ancestor containing current/pre-change `package.json` or a recognized JS/framework config for each changed file. Do not leak dependencies or framework signals across sibling package boundaries. Detection evaluates both current evidence and normalized removals so deleting a framework dependency/import still activates its review overlay. React Native or Expo removal evidence suppresses React-web inference in the same way as current RN/Expo evidence.

- JavaScript/TypeScript: changed JS/JSX/MJS/CJS/TS/TSX/MTS/CTS files or JS/TS configuration.
- Node.js/NestJS: a changed code/config file plus Node built-in imports, server dependencies, any real `@nestjs/` dependency/import namespace, or `nest-cli.json`. A generic `.js`/`.ts` extension alone is insufficient.
- React web/Next.js: React DOM or Next imports/dependencies/config, or React evidence at a boundary without React Native/Expo evidence. React Native evidence alone is insufficient.
- React Native: React Native, `expo`, `expo-*`, or `@expo/*` imports/dependencies; Metro/Expo/RN config; native `android`/`ios` trees; or platform-specific source files. Standard Expo `app.json` counts only with Expo dependency/import evidence. Native-tree evidence is attributed only when the native file's nearest package/config boundary equals the changed file's boundary.

Specific review rules come from each overlay's authoritative references, not from this detector.
