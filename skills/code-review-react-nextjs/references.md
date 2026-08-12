# React and Next.js Rule Provenance

React and Next behavior can differ by release and router. Confirm the repository versions and whether it uses the App or Pages Router before applying a version-sensitive rule.

| Rule ID | Concept | Applicability / version | Authoritative source | Last verified |
| --- | --- | --- | --- | --- |
| REACT-001 | Rules of Hooks | Changed React components and custom hooks; React versions covered by current docs | [React Rules of Hooks](https://react.dev/reference/rules/rules-of-hooks) | 2026-08-11 |
| REACT-002 | Effect synchronization, dependencies, and cleanup | Changed effects or external synchronization; React versions covered by current docs | [Synchronizing with Effects](https://react.dev/learn/synchronizing-with-effects) | 2026-08-11 |
| NEXT-001 | Server and Client Component boundaries | Next App Router code; use configured Next major | [Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components) | 2026-08-11 |
| NEXT-002 | Cache behavior and invalidation | Next data fetching, rendering, or mutation cache changes; use configured Next major/router | [Next.js caching guide](https://nextjs.org/docs/app/guides/caching-without-cache-components) | 2026-08-11 |
| REACT-003 | Render identity, state preservation, and list keys | Changed component position/type or list membership/order; configured React version | [Preserving and resetting state](https://react.dev/learn/preserving-and-resetting-state), [Rendering lists](https://react.dev/learn/rendering-lists#keeping-list-items-in-order-with-key) | 2026-08-11 |
| REACT-004 | Controlled and uncontrolled inputs | Changed React DOM form value/checked ownership or initialization; configured React version | [React input troubleshooting](https://react.dev/reference/react-dom/components/input#im-getting-an-error-a-component-is-changing-an-uncontrolled-input-to-be-controlled) | 2026-08-11 |
| REACT-005 | Hydration parity | Changed server-rendered markup or client bootstrapping; configured React version | [React `hydrateRoot` caveats](https://react.dev/reference/react-dom/client/hydrateRoot#caveats) | 2026-08-11 |
| NEXT-003 | Loading, streaming, and error boundaries | Changed App Router route segments or asynchronous rendering; configured Next major | [Next loading UI and streaming](https://nextjs.org/docs/app/getting-started/linking-and-navigating#streaming), [Next error handling](https://nextjs.org/docs/app/getting-started/error-handling) | 2026-08-11 |
