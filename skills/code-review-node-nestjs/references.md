# Node.js and NestJS Rule Provenance

Use the exact Node and Nest versions configured by the repository. Version-specific behavior must be checked against that version's official documentation.

| Rule ID | Concept | Applicability / version | Authoritative source | Last verified |
| --- | --- | --- | --- | --- |
| NODE-001 | Event-loop and worker-pool blocking | Request/event handlers and shared server processes; repository-supported Node release | [Do not block the event loop](https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop) | 2026-08-11 |
| NODE-002 | Node error propagation, callbacks, promises, and EventEmitter errors | Changed Node error boundaries; repository-supported Node release | [Node.js errors](https://nodejs.org/api/errors.html) | 2026-08-11 |
| NEST-001 | Application lifecycle and shutdown hooks | Startup/shutdown, signals, resources, and hook changes; configured Nest major | [NestJS lifecycle events](https://docs.nestjs.com/fundamentals/lifecycle-events) | 2026-08-11 |
| NEST-002 | Exception filters and transport error mapping | Changed Nest controllers, gateways, filters, or exception boundaries; configured Nest major | [NestJS exception filters](https://docs.nestjs.com/exception-filters) | 2026-08-11 |
| NEST-003 | Provider injection scopes and shared lifetime | Changed providers with request, transient, or singleton state; configured Nest major | [NestJS injection scopes](https://docs.nestjs.com/fundamentals/injection-scopes) | 2026-08-11 |
