# ADR-0001: Clean Architecture with Layered Dependencies and Ports

## Status

Accepted

## Date

2026-01-15

## Context

Distillery is a production NLP model-distillation platform that has to combine
heavyweight machine-learning code (PyTorch/Transformers), web/API code, a task
queue, object storage, a relational database, and observability/security
concerns. If these are allowed to intermingle freely, the core distillation
logic becomes impossible to test without spinning up frameworks and external
services, and swapping any one component (e.g. the storage backend) ripples
across the whole codebase. We need a structure that isolates business logic from
delivery and infrastructure details.

## Decision

We adopt Clean Architecture with concentric layers and a strict dependency rule:

- **domain** (innermost, pure): entities, value objects, events, ports, and
  exceptions. Depends only on the standard library and Pydantic.
- **application**: use-case services that orchestrate the domain.
- **adapters** (outermost): the core distillation engine plus infrastructure
  (db, queue, storage, observability, security).

The dependency rule is that inner layers never import outer layers. Outward
dependencies are inverted through `Protocol`-based "ports" declared in
`domain/ports.py`, which adapters implement. Wiring happens in exactly one
composition root, `src/distillery/bootstrap.py`. Heavy dependencies (torch,
celery, boto3) are pulled in via lazy imports so they stay out of import time.

## Consequences

### Positive

- The engine and domain are unit-testable without frameworks or live services.
- Adapters (storage, queue, db) are swappable behind their ports.
- A single composition root makes the system's wiring explicit and auditable.
- Lazy imports keep startup fast and the domain free of heavy dependencies.

### Negative

- More indirection and boilerplate (ports, mappers, explicit wiring).
- Contributors must understand the layering before adding code.

### Mitigations

- Keep the approach pragmatic rather than dogmatic: only introduce a port where
  a swap or test seam genuinely pays off, and avoid ceremony elsewhere.

## Alternatives considered

- **A conventional layered/MVC structure** without dependency inversion:
  simpler up front, but couples business logic to frameworks and infrastructure,
  making the engine hard to test and components hard to replace.
- **A single monolithic package** with no enforced boundaries: lowest friction
  initially, but degrades quickly as ML, web, and infra code intermix.
