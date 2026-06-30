# API reference

Base URL: `/` for probes/metrics, `/api/v1` for the application API. Interactive docs:
`/docs` (Swagger UI) and `/redoc`; the raw schema is at `/openapi.json` (disabled when
`DISTILLERY_API__DOCS_ENABLED=false`).

## Authentication

Send **one** of:

- `X-API-Key: <key>` — API keys (recommended for services).
- `Authorization: Bearer <jwt>` — obtain via `POST /api/v1/auth/login`.

Roles form a hierarchy: **`viewer` < `operator` < `admin`**. Endpoints declare a minimum role.
Owners may access their own jobs; admins may access any job.

## Versioning

The application API is versioned by path prefix (`/api/v1`). Breaking changes introduce `/api/v2`;
within a version, changes are additive/backward-compatible.

## Error envelope

Every error returns the same shape with an appropriate status code:

```json
{ "error": { "code": "job_not_found", "message": "…", "details": {}, "request_id": "…" } }
```

| HTTP | `code` examples |
|---|---|
| 400 | `validation_error` |
| 401 | `unauthenticated` |
| 403 | `forbidden` |
| 404 | `not_found`, `job_not_found`, `artifact_not_found` |
| 409 | `conflict`, `invalid_state_transition` |
| 413 | `payload_too_large` |
| 422 | `request_validation_error` (Pydantic body validation) |
| 429 | `rate_limited`, `quota_exceeded` |
| 502 | `teacher_error` |
| 500 | `internal_error`, `training_error` |

## Rate limiting

Fixed-window per-minute limit (default 120), keyed by API key or client IP. Responses include
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`; a 429 adds `Retry-After`.
Probes (`/health`, `/ready`, `/metrics`, docs) are exempt.

## Common headers

`X-Request-ID` (echoed/generated per request; included in logs and error envelopes) and
`X-Response-Time-ms` are returned on every response, plus OWASP secure headers.

---

## Health & metrics (unauthenticated)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness — `200 {status, service, version}` while the process is up. |
| GET | `/ready` | Readiness — verifies DB connectivity; `200`/`503`. |
| GET | `/metrics` | Prometheus exposition format. |

---

## Auth — `/api/v1/auth`

### POST `/auth/login`
Body: `{ "email": "...", "password": "..." }` → `200 { "access_token", "token_type": "bearer", "expires_in" }`.

### POST `/auth/users` _(admin)_
Body: `{ "email", "password" (≥12 chars), "role": "viewer|operator|admin" }` → `201 UserResponse`.

### GET `/auth/me`
→ `200 { "subject", "role", "auth_method" }` for the current principal.

### POST `/auth/api-keys`
Body: `{ "name", "role"?, "expires_at"? }` → `201` with the **plaintext key shown once**:
```json
{ "id": "...", "name": "ci", "prefix": "abcd…", "role": "operator",
  "is_active": true, "created_at": "...", "api_key": "dst_…" }
```
A caller cannot mint a key more privileged than itself.

### GET `/auth/api-keys`
→ `200 [ApiKeyResponse]` (no secrets) for the current user.

---

## Jobs — `/api/v1/jobs` (authentication required)

### POST `/jobs` _(operator)_ → `202 JobResponse`
Create and enqueue a distillation job.

```json
{
  "name": "distilbert-sst2",
  "config": {
    "strategy": "response_based",
    "teacher_type": "huggingface",
    "device": "auto",
    "teacher": { "name_or_path": "textattack/bert-base-uncased-SST-2", "num_labels": 2, "max_seq_length": 128 },
    "student": { "name_or_path": "distilbert-base-uncased", "num_labels": 2, "max_seq_length": 128 },
    "dataset": { "format": "hf_hub", "reference": "glue/sst2", "text_column": "sentence",
                 "label_column": "label", "eval_split": "validation", "max_train_samples": 5000 },
    "training": { "epochs": 3, "train_batch_size": 16, "learning_rate": 5e-5, "warmup_ratio": 0.1 },
    "kd": { "temperature": 2.0, "alpha": 0.5 }
  }
}
```

For `feature_based`, add `"kd": { …, "feature_loss_weight": 0.5, "feature_layer_map": {"1": 2} }`.
For `llm_teacher`, set `"teacher_type": "llm"`, omit `teacher`, and add:
```json
"llm": { "model": "claude-sonnet-4-6", "task_description": "Classify movie review sentiment.",
         "label_names": ["neg", "pos"], "num_samples": 500, "label_existing": false }
```

`JobResponse` (abridged):
```json
{ "id": "...", "name": "...", "status": "queued", "owner_id": "...",
  "progress_percent": 0.0, "config": { ... },
  "evaluation": { "primary_metric": 0.91, "teacher_agreement": 0.94,
                  "compression_ratio": 1.7, "teacher_accuracy_retention": 0.97, ... },
  "resource_usage": { "duration_seconds": 812.3, "teacher_tokens": 0, "device": "cuda" },
  "artifacts": [ { "type": "student_model", "uri": "s3://…", "checksum": null } ],
  "task_id": "…", "created_at": "...", "finished_at": null }
```

### GET `/jobs` → `200 JobListResponse`
Query params: `status` (filter), `mine` (default `true`; admins set `mine=false` to see all),
`limit` (1–100, default 20), `offset` (≥0). Returns `{ items, total, limit, offset, has_more }`.

### GET `/jobs/{job_id}` → `200 JobResponse`
404 `job_not_found` if absent; 403 `forbidden` if not owner/admin.

### GET `/jobs/{job_id}/artifacts` → `200 [ArtifactResponse]`

### POST `/jobs/{job_id}/cancel` _(operator)_ → `200 JobResponse`
Revokes the worker task (best-effort) and moves the job to `cancelled`. 409 if already terminal.

### DELETE `/jobs/{job_id}` _(operator)_ → `204`
Only terminal jobs may be deleted; artifacts are removed (best-effort). 409 if the job is active.

---

## Example session

```bash
KEY=dev-local-admin-key
# create
JOB=$(curl -s -X POST localhost:8000/api/v1/jobs -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' -d @examples/requests/create_job_response_based.json | jq -r .id)
# poll
curl -s localhost:8000/api/v1/jobs/$JOB -H "X-API-Key: $KEY" | jq '.status, .evaluation.primary_metric'
# artifacts
curl -s localhost:8000/api/v1/jobs/$JOB/artifacts -H "X-API-Key: $KEY" | jq '.[].uri'
```

The complete, always-current schema (every field, type and constraint) is the generated
`GET /openapi.json`.
