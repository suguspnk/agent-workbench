# Dependency Supply Chain

Add a dependency only when existing project tools cannot reasonably solve the need and its benefit justifies maintenance, security, license, bundle/runtime, operational, and replacement cost. Prefer standard-library, framework-native, and existing project capabilities.

For every added or updated dependency, verify exact identity and requested source, trusted registry/publisher/provenance, resolved version and graph, and lockfile or equivalent integrity. Use the deterministic project mechanism; review the full transitive/resolution diff and unexpected generated changes. Scale deeper review to risk: maintenance health, ownership, release history, supported lifecycle, advisories, license-policy fit, native code, runtime/bundle cost, and replacement path.

Inspect package metadata and lifecycle/install/build scripts without executing them. Run such code only when necessary and explicitly authorized, using containment without unrelated credentials, production access, or unnecessary filesystem/network privilege. Avoid unreviewed downloads and broad dynamic resolution.

Reassess an existing dependency when it crosses a new trust, data, execution, or privilege boundary; prior presence is not approval for expanded authority. Isolate replaceable external dependencies behind an appropriate boundary.

Pin privileged CI actions, build dependencies, containers, and deployment images to immutable full commit SHAs or content digests. When immutable pinning is technically impossible, every exception is a waiver governed in full by the central `SKILL.md` waiver requirements; no parallel or weaker local exception exists.
