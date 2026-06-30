# Sequence diagrams

## 1. Create a distillation job (async, production)

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as FastAPI
    participant Authn as Authenticator
    participant JS as JobService
    participant DB as PostgreSQL
    participant Q as Redis broker
    Client->>API: POST /api/v1/jobs (X-API-Key, config)
    API->>Authn: resolve credentials
    Authn->>DB: lookup API key by prefix, verify hash
    Authn-->>API: Principal(role)
    API->>API: require_role(OPERATOR), validate body (Pydantic)
    API->>JS: create_job(name, config, owner)
    JS->>DB: INSERT job (PENDING→QUEUED) [tx1, commit]
    JS->>Q: enqueue_distillation(job_id)
    Q-->>JS: task_id
    JS->>DB: UPDATE job.task_id [tx2, commit]
    JS-->>API: job (QUEUED)
    API-->>Client: 202 Accepted (JobResponse)
```

## 2. Worker executes the job

```mermaid
sequenceDiagram
    autonumber
    participant Q as Redis broker
    participant W as Celery worker
    participant PS as PipelineService
    participant DB as PostgreSQL
    participant E as Engine
    participant S as Artifact storage
    Q->>W: deliver run_distillation_job(job_id)
    W->>PS: run_job(job_id)
    PS->>DB: load job; if QUEUED → RUNNING [commit]
    loop training (throttled)
        E-->>PS: on_progress(JobProgress)
        PS->>DB: UPDATE progress (≤ every 5% / 3s)
    end
    PS->>E: run(config, work_dir)
    E->>E: build models, data, strategy, train, evaluate
    E-->>PS: EngineResult (eval, usage, artifacts)
    PS->>S: upload artifacts (model, report, config, logs)
    PS->>DB: RUNNING → SUCCEEDED (+eval, +artifacts) [commit]
    Note over PS,DB: On any exception → RUNNING → FAILED (+error)
```

## 3. Failure & redelivery (fault tolerance)

```mermaid
sequenceDiagram
    autonumber
    participant Q as Redis broker
    participant W1 as Worker A (dies)
    participant W2 as Worker B
    participant PS as PipelineService
    participant DB as PostgreSQL
    Q->>W1: deliver job (acks_late)
    W1->>PS: run_job → RUNNING
    W1--xQ: crash before ack
    Q->>W2: redeliver job (reject_on_worker_lost)
    W2->>PS: run_job(job_id)
    PS->>DB: load job; status == RUNNING (not QUEUED)
    PS-->>W2: no-op (idempotent guard); operator may re-queue
```

## 4. User login (JWT)

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as FastAPI
    participant AS as AuthService
    participant DB as PostgreSQL
    User->>API: POST /api/v1/auth/login (email, password)
    API->>AS: login(email, password)
    AS->>DB: get_by_email
    AS->>AS: verify_password (PBKDF2, constant-time)
    AS-->>API: signed JWT (HS256, role claim)
    API-->>User: 200 {access_token, expires_in}
    User->>API: GET /api/v1/jobs (Authorization: Bearer ...)
```
