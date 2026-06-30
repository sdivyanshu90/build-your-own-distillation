# ADR-0004: Persistence (PostgreSQL + SQLAlchemy 2.0) and Pluggable Artifact Storage

## Status

Accepted

## Date

2026-01-15

## Context

Distillery must durably track users, API keys, jobs, and artifacts with strong
integrity guarantees, while also recording structures that evolve frequently and
are mostly read back as a whole (job configuration, progress, evaluation
results, resource usage). Separately, it produces large model artifacts that do
not belong in a relational row. We need a persistence design that stays stable
as features evolve and a storage approach suited to large binary objects across
dev and prod.

## Decision

We use **PostgreSQL with SQLAlchemy 2.0**, taking a hybrid relational/JSONB
schema:

- Identity, ownership, and lifecycle tables (`users`, `api_keys`, `jobs`,
  `artifacts`) are modelled relationally in 3NF.
- Evolving, read-mostly structures (`config`, `progress`, `evaluation`,
  `resource_usage`) are stored as **JSONB** value objects, keeping the schema
  stable and writes atomic.

Migrations use **Alembic** with a fixed constraint-naming convention so that
autogenerate produces stable, predictable diffs. The ORM is kept separate from
domain entities through explicit mappers (persistence ignorance), so the domain
does not depend on SQLAlchemy. A **Unit-of-Work** pattern provides a single
transaction spanning multiple repositories.

For artifacts we define a pluggable **`ArtifactStorage` port**: a local
filesystem implementation for development and an S3-compatible implementation
for production.

## Consequences

### Positive

- ACID guarantees and relational integrity for jobs, keys, and ownership.
- JSONB absorbs schema churn for evolving structures without migrations.
- Explicit mappers keep the domain framework-free and testable.
- Unit-of-Work makes multi-repository writes transactional and consistent.
- Storage backends are swappable per environment behind one port.

### Negative

- JSONB columns are less queryable/constrainable than normalized columns.
- Explicit mappers add boilerplate versus an active-record style.
- Two storage implementations must be kept behavior-compatible.

### Mitigations

- Reserve JSONB for genuinely evolving, read-mostly data; keep anything needing
  integrity or ad-hoc querying relational.
- The shared `ArtifactStorage` port and fixed naming convention reduce drift
  between environments and keep migrations predictable.

## Alternatives considered

- **Full normalization** of all structures: rejected — produces sparse tables
  and constant schema churn for fast-evolving config/progress data.
- **A document database**: rejected — we need ACID transactions and relational
  integrity for jobs and API keys.
- **Storing artifacts in the database**: rejected — large blobs belong in object
  storage, not relational rows.
