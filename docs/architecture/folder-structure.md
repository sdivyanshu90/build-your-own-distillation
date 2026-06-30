# Folder structure

A file-by-file tour of the repository.

```
build-your-own-distillation/
├── pyproject.toml            # Packaging, deps/extras, ruff/black/mypy/pytest/coverage config
├── Makefile                  # Developer task runner (install, lint, test, run, up, migrate…)
├── docker-compose.yml        # Full local stack
├── alembic.ini               # Alembic configuration (URL injected from settings)
├── .env.example              # Environment template (all DISTILLERY_* variables)
├── .pre-commit-config.yaml   # Pre-commit hooks (ruff, black, mypy, bandit, gitleaks…)
│
├── src/distillery/
│   ├── __init__.py           # Package docstring + version re-export
│   ├── __main__.py           # `python -m distillery` → CLI
│   ├── version.py            # Single source of truth for the version
│   ├── bootstrap.py          # Composition root: wires adapters → services (the only wiring point)
│   │
│   ├── config/
│   │   └── settings.py       # Pydantic settings; nested groups; production fail-fast checks
│   │
│   ├── domain/               # PURE business model (no framework imports)
│   │   ├── enums.py          # JobStatus, DistillationStrategy, ModelTask, TeacherType, Role…
│   │   ├── exceptions.py     # DistilleryError hierarchy with stable codes
│   │   ├── value_objects.py  # Frozen, validated: ModelSpec, DatasetSpec, DistillationConfig, KD…
│   │   ├── entities.py       # DistillationJob (state machine), User, ApiKey, Artifact
│   │   ├── events.py         # Domain events (JobStarted/Progressed/Completed/Failed)
│   │   └── ports.py          # Interfaces: repositories, UoW, storage, queue, engine, publisher
│   │
│   ├── application/
│   │   ├── dto.py            # Page (pagination)
│   │   └── services/
│   │       ├── job_service.py       # Create/list/get/cancel/delete jobs
│   │       ├── pipeline_service.py  # Execute a job end-to-end (worker entry point)
│   │       └── auth_service.py      # Users, login, API keys
│   │
│   ├── core/                 # The distillation engine (imports torch/transformers)
│   │   ├── losses.py         # ResponseDistillationLoss, FeatureDistillationLoss
│   │   ├── models.py         # ModelBundle, build_model, tiny offline path, HashingTokenizer
│   │   ├── data.py           # Dataset loading, label resolution, tokenisation, dataloaders
│   │   ├── trainer.py        # Strategy-agnostic training loop (+ early stopping)
│   │   ├── evaluation.py     # Metrics, teacher agreement, latency, compression
│   │   ├── engine.py         # DefaultDistillationEngine (orchestration + artifacts)
│   │   └── strategies/
│   │       ├── base.py            # DistillationStrategy interface
│   │       ├── response_based.py  # Hinton soft-target KD
│   │       ├── feature_based.py   # + hidden-state alignment
│   │       ├── llm_teacher.py     # SupervisedStrategy (post LLM data-gen)
│   │       └── registry.py        # enum → strategy factory (Open/Closed)
│   │
│   ├── teachers/llm/
│   │   ├── base.py           # LLMClient protocol + LLMResponse
│   │   ├── anthropic_client.py  # Anthropic adapter (retries, token accounting)
│   │   ├── prompts.py        # Generation/labelling prompt templates (strict JSON)
│   │   └── dataset_builder.py   # Fan-out generation/labelling → rows + token count
│   │
│   ├── infrastructure/
│   │   ├── events.py         # Logging/Null/Collecting event publishers
│   │   ├── db/
│   │   │   ├── base.py            # Declarative base, naming convention, JSONB type
│   │   │   ├── models.py          # ORM models
│   │   │   ├── session.py         # Engine + session factory
│   │   │   ├── mappers.py         # ORM ⇄ domain mapping (persistence ignorance)
│   │   │   ├── repositories.py    # Repositories + SqlAlchemyUnitOfWork
│   │   │   └── seed.py            # ensure_schema + bootstrap seeding
│   │   ├── storage/          # base (hashing/size), local, s3 + build_storage factory
│   │   ├── queue/            # celery_app, tasks, adapters (Celery + Inline)
│   │   ├── observability/    # logging (structlog), metrics (Prometheus)
│   │   └── security/         # passwords, api_keys, tokens (JWT), authentication, rate_limit
│   │
│   ├── api/
│   │   ├── app.py            # create_app factory (middleware, routers, OpenAPI, lifespan)
│   │   ├── asgi.py           # module-level app for gunicorn/uvicorn
│   │   ├── deps.py           # DI: services, auth, RBAC
│   │   ├── errors.py         # Domain → HTTP error envelope
│   │   ├── middleware.py     # Request context, metrics, rate limit, security headers, body limit
│   │   ├── schemas/          # Request/response models (common, auth, jobs)
│   │   └── routers/          # health, auth, jobs
│   │
│   └── cli/
│       └── main.py           # Typer CLI (serve, worker, distill, db, user, apikey)
│
├── migrations/               # Alembic env + initial schema
├── tests/                    # unit/ · integration/ · e2e/ · load/ · conftest.py
├── deploy/                   # docker/ · kubernetes/ · monitoring/
├── docs/                     # architecture/ · api/ · guides/ · operations/ · decisions/
├── examples/                 # Config + request examples + SDK snippet
└── .github/                  # workflows (ci/release/security), dependabot, templates
```
