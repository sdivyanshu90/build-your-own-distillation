# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [1.0.0] - 2026-01-15

### Added

- **Distillation engine** with three strategies behind a Strategy pattern + registry:
  - `response_based` — Hinton soft-target KD (temperature-scaled KL + hard cross-entropy).
  - `feature_based` — response KD plus mask-aware intermediate hidden-state matching with learnable
    projections and automatic uniform layer mapping.
  - `llm_teacher` — generate or label a training corpus with an LLM (Anthropic), then supervised
    fine-tuning.
- Strategy-agnostic **trainer**: AdamW with decay groups, linear warmup, gradient accumulation and
  clipping, deterministic seeding, throttled progress callbacks, optional early stopping with
  best-weight restore.
- **Evaluation**: accuracy / macro precision / recall / F1, teacher agreement (fidelity), inference
  latency, and compression statistics.
- Offline **tiny-model path** (`config_only`) with a deterministic hashing tokenizer for fast,
  network-free tests and demos.
- **REST API** (FastAPI): job CRUD, artifacts, auth (login, users, API keys), health/readiness,
  Prometheus metrics, OpenAPI docs. API-key and JWT authentication with RBAC.
- **Asynchronous execution** via Celery + Redis with late-ack redelivery and an inline/eager mode
  for development and tests.
- **Persistence** with PostgreSQL + SQLAlchemy 2.0 (value objects as JSONB), repositories, a
  Unit-of-Work, and Alembic migrations.
- **Artifact storage** abstraction with local-filesystem and S3-compatible backends.
- **Security**: PBKDF2 password hashing, SHA-256 API keys, JWT, fixed-window rate limiting
  (in-memory + Redis), OWASP secure headers, request-size limits, production fail-fast config checks.
- **Observability**: structured JSON logging (structlog) with request IDs, Prometheus metrics, and a
  provisioned Grafana dashboard with alert rules.
- **CLI** (Typer): `serve`, `worker`, `distill`, `db upgrade/create-all/seed`, `user create`,
  `apikey create`.
- **DevOps**: multi-stage Docker image, Docker Compose stack, Kustomize Kubernetes base + staging/
  production overlays (HPA, PDB, probes, migration Job, hardened non-root pods), and GitHub Actions
  for CI, release (GHCR image with SBOM + provenance), and security scanning.
- **Documentation**: architecture (with Mermaid diagrams), API reference, database design, security,
  user/developer/administrator/deployment/troubleshooting guides, an operational runbook, and ADRs.
- **Tests**: unit, integration, end-to-end (API + CLI), and load (Locust); ≥95% coverage enforced.

[Unreleased]: https://github.com/uniiq-ai/distillery/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/uniiq-ai/distillery/releases/tag/v1.0.0
