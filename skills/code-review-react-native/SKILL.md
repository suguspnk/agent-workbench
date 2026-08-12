---
name: code-review-react-native
description: "Add React Native and Expo-specific defect concerns to the code-review core when mobile dependencies, config, native trees, or platform files provide evidence. This overlay never implies the React web/Next.js overlay."
---

# React Native Review Overlay

Use only with `$code-review` and the implied JavaScript/TypeScript overlay. The core owns target selection, role protocol, severity, evidence, checks, and output.

Select from React Native/Expo imports or dependencies, Metro/Expo/RN config, native `android`/`ios` trees, platform-specific source files, or an explicit caller override at the nearest package/config boundary. This selection never implies React web/Next.js.

Read [references](references.md), then apply the mapped concerns relevant to the changed code.

## Mapped review concerns

- [RN-001] Compare `.native`, `.ios`, `.android`, and generic implementations plus native project/config changes for supported-platform parity and fallback resolution.
- [RN-002] Verify accessibility labels, roles, state/value, grouping, focus, touch target, and platform-specific behavior for changed interaction semantics.
- [RN-003] For `FlatList`, inspect stable keys, `renderItem` data dependencies, `extraData`, item layout assumptions, pagination/retry behavior, and virtualization settings where changed behavior demonstrates correctness or performance risk.
- [RN-004] Check Android runtime permission declarations and request/result handling where permission-sensitive behavior changes.
- [RN-005] Check deep-link URL handling, supported schemes, and initial/runtime link paths where linking changes.
- [RN-006] Check foreground/background transitions and listener cleanup where AppState behavior changes.
- [RN-007] Check keyboard avoidance and safe-area layout behavior on supported platforms where those containers change.
- [RN-008] Check cleanup and stale state across mount/unmount, background/foreground transitions, and asynchronous native callbacks where applicable.

Do not report device folklore, visual taste, or performance speculation without a reproducible affected path. Send only evidence-backed defects to the core contract.
