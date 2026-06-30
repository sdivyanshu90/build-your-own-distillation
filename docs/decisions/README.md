# Architecture Decision Records

This directory holds the Architecture Decision Records (ADRs) for **Distillery**,
the NLP model-distillation platform. Each ADR captures a single significant
architectural decision: the context that forced it, the decision itself, its
consequences, and the alternatives that were weighed and rejected.

## Index

| #    | Title                                                        | Status   | Summary                                                                                  |
| ---- | ------------------------------------------------------------ | -------- | ---------------------------------------------------------------------------------------- |
| [0001](0001-clean-architecture.md)            | Clean Architecture with Layered Dependencies and Ports         | Accepted | Concentric domain ← application ← adapters layers; dependencies inverted via Protocol ports, wired in one composition root. |
| [0002](0002-distillation-strategies.md)       | Pluggable Distillation Strategies via Strategy Pattern + Registry | Accepted | Response-, feature-, and LLM-teacher distillation behind a common interface and registry; trainer stays strategy-agnostic. |
| [0003](0003-async-workers-celery-redis.md)    | Asynchronous Execution with Celery + Redis                     | Accepted | Long-running training runs off the request path on Celery workers; reliable, idempotent, with an inline mode for dev/tests. |
| [0004](0004-persistence-and-storage.md)       | Persistence (PostgreSQL + SQLAlchemy 2.0) and Pluggable Artifact Storage | Accepted | Relational 3NF tables plus JSONB value objects; explicit mappers, Unit-of-Work, and a swappable artifact-storage port. |

## ADR process and format

We record an ADR whenever a decision meaningfully shapes the system's structure,
its boundaries, or how it is built and operated. ADRs are numbered sequentially
(`NNNN-short-title.md`) and are immutable once accepted: rather than rewriting a
past decision, we add a new ADR that supersedes it.

Each ADR follows a standard format:

- **Title** — the numbered decision.
- **Status** — one of Proposed, Accepted, Superseded (all current ADRs are
  Accepted).
- **Date** — when the decision was accepted.
- **Context** — the forces and constraints that motivated the decision.
- **Decision** — what we decided to do.
- **Consequences** — split into Positive, Negative, and Mitigations.
- **Alternatives considered** — the options evaluated and why they were rejected.
