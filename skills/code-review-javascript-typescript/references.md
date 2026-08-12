# JavaScript and TypeScript Rule Provenance

Apply the repository's configured TypeScript and runtime versions. The sources below define the concepts; they do not override repository contracts.

| Rule ID | Concept | Applicability / version | Authoritative source | Last verified |
| --- | --- | --- | --- | --- |
| JSTS-001 | Control-flow narrowing and type guards | TypeScript code whose branches refine unions, nullability, or unknown input; current TypeScript handbook | [TypeScript narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html) | 2026-08-11 |
| JSTS-002 | Strict-family compiler checks | Any changed `tsconfig` or code whose safety depends on strict null/type checking; use the repository compiler version | [TypeScript `strict`](https://www.typescriptlang.org/tsconfig/strict.html) | 2026-08-11 |
| JSTS-003 | Module resolution, package exports, and emit/runtime alignment | Module or package configuration changes; use the repository TypeScript and runtime versions | [TypeScript module reference](https://www.typescriptlang.org/docs/handbook/modules/reference.html) | 2026-08-11 |
| JSTS-004 | Promise and async completion/rejection semantics | Changed asynchronous control flow; ECMAScript language semantics plus repository runtime support | [ECMAScript Promise objects](https://tc39.es/ecma262/multipage/control-abstraction-objects.html#sec-promise-objects) | 2026-08-11 |
| JSTS-005 | Type erasure and runtime trust boundaries | Dynamic or external values represented only by compile-time types; current TypeScript handbook | [TypeScript erased types](https://www.typescriptlang.org/docs/handbook/2/basic-types.html#erased-types) | 2026-08-11 |
| JSTS-006 | Discriminated unions, exhaustiveness, and boundary guards | TypeScript unions, optional/null/indexed values, and type guards at dynamic boundaries; current TypeScript handbook | [TypeScript narrowing](https://www.typescriptlang.org/docs/handbook/2/narrowing.html) | 2026-08-11 |

Repository configuration controls exact emit, module resolution, lib definitions, and compatibility. When those details matter, cite the checked config/version and the relevant official option page rather than generalizing from this table.
