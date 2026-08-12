# React Native Rule Provenance

React Native and Expo behavior is version- and platform-sensitive. Use the repository versions, deployment targets, native projects, and supported device matrix.

| Rule ID | Concept | Applicability / version | Authoritative source | Last verified |
| --- | --- | --- | --- | --- |
| RN-001 | Platform-specific files and resolution | Shared/native modules with platform variants; configured React Native version | [Platform-specific code](https://reactnative.dev/docs/platform-specific-code) | 2026-08-11 |
| RN-002 | Native accessibility semantics | Changed interactive UI on supported iOS/Android targets; configured React Native version | [React Native accessibility](https://reactnative.dev/docs/accessibility) | 2026-08-11 |
| RN-003 | FlatList rendering and invalidation contract | Changed virtualized lists, keys, data, or rendering dependencies; configured React Native version | [FlatList](https://reactnative.dev/docs/flatlist) | 2026-08-11 |
| RN-004 | Android runtime permissions | Changed permission-gated Android behavior; configured React Native and Android target versions | [PermissionsAndroid](https://reactnative.dev/docs/permissionsandroid) | 2026-08-11 |
| RN-005 | Deep-link handling | Changed URL schemes, initial URLs, or runtime link listeners; configured React Native version | [React Native Linking](https://reactnative.dev/docs/linking) | 2026-08-11 |
| RN-006 | Application foreground/background state | Changed AppState transitions or subscriptions; configured React Native version | [React Native AppState](https://reactnative.dev/docs/appstate) | 2026-08-11 |
| RN-007 | Keyboard avoidance and safe-area layout | Changed keyboard/safe-area containers on supported platforms; configured React Native version | [KeyboardAvoidingView](https://reactnative.dev/docs/keyboardavoidingview), [SafeAreaView](https://reactnative.dev/docs/safeareaview) | 2026-08-11 |
| RN-008 | App-state and external-system effect cleanup | Changed subscriptions, background/foreground transitions, or asynchronous native callbacks owned by React effects | [React Native AppState](https://reactnative.dev/docs/appstate), [React `useEffect`](https://react.dev/reference/react/useEffect#connecting-to-an-external-system) | 2026-08-11 |
