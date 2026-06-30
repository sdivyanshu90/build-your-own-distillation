# Troubleshooting

A problem → cause → fix reference for operators and integrators running **Distillery** in
development, Compose, or Kubernetes. Every symptom below maps to a concrete cause and a tested fix,
with the exact environment variables and commands to check.

> **First rule of debugging Distillery:** grab the `request_id`. Every API response carries an
> `X-Request-ID` header, every error body embeds the same value at `error.request_id`, and every log
> line is JSON containing it. With one ID you can pivot from a failed call straight to the relevant
> logs.

```bash
# Pull the request id out of a failing call
curl -s -D- -o /dev/null -X POST localhost:8000/api/v1/jobs -H "X-API-Key: $KEY" | grep -i x-request-id

# Then find every log line for that request (logs are JSON)
kubectl logs deploy/distillery-api  | grep <request_id>
kubectl logs deploy/distillery-worker | grep <job_id>
```

**See also:** [Operations runbook](../operations/runbook.md) ·
[Architecture overview](../architecture/overview.md) · [Security](../security.md) ·
[Deployment guide](deployment-guide.md) · [Administrator guide](administrator-guide.md).

---

## The error envelope

Every API error — regardless of layer — returns the same JSON shape. Read `error.code` first; it is
more precise than the HTTP status.

```json
{ "error": { "code": "job_not_found", "message": "…", "details": {}, "request_id": "…" } }
```

| HTTP | `error.code` values | Meaning |
|---|---|---|
| 400 | `validation_error` | Malformed request the router rejected. |
| 401 | `unauthenticated` | Missing or invalid credentials. |
| 403 | `forbidden` | Authenticated but role too low, or not the resource owner. |
| 404 | `not_found`, `job_not_found`, `artifact_not_found` | No such route/job/artifact. |
| 409 | `conflict`, `invalid_state_transition` | Action not legal for the current job state. |
| 413 | `payload_too_large` | Request body exceeded the size cap. |
| 422 | `request_validation_error` | Pydantic body/config validation failed (see [Validation](#validation-422--400)). |
| 429 | `rate_limited`, `quota_exceeded` | Throttled — back off and retry. |
| 502 | `teacher_error` | The LLM/HuggingFace teacher failed. |
| 500 | `training_error`, `internal_error` | Training failed, or an unexpected server error. |

---

## Quick reference: problem → cause → fix

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 unauthenticated` | Missing/invalid `X-API-Key` or expired/invalid JWT | Send a valid key or `Authorization: Bearer <jwt>`; re-login at `POST /api/v1/auth/login`. |
| `403 forbidden` | Role below the endpoint's minimum, or not the job owner | Use an `operator`/`admin` key; only owners (or admins) can read/cancel/delete a job. |
| `422 request_validation_error` | Config violates a cross-field rule | Fix the offending field — see [Validation](#validation-422--400). |
| `413 payload_too_large` | Request body over the 10 MiB cap | Use `inline` only for small data; reference `hf_hub`/`jsonl`/`csv` datasets instead. |
| Job stuck in `queued` | Worker down or broker unreachable | Check workers up + Redis reachable (`DISTILLERY_QUEUE__BROKER_URL`); see [Stuck in QUEUED](#job-stuck-in-queued). |
| Job stuck in `running` after a crash | Worker died mid-run; job not auto-completed | Manually re-queue or cancel — see [Stuck in RUNNING](#job-stuck-in-running-after-a-worker-crash). |
| Job `failed`, code `teacher_error` | LLM teacher error: missing/invalid API key, rate limit, malformed model JSON | Set `DISTILLERY_LLM__ANTHROPIC_API_KEY`; see [teacher_error](#failed-teacher_error). |
| Job `failed`, code `training_error` | Empty dataloader or OOM | Check dataset; reduce batch/sample size — see [training_error / OOM](#failed-training_error--oom). |
| `GET /ready` → `503` | PostgreSQL unreachable | Check DB connectivity and `DISTILLERY_DATABASE__URL` — see [Readiness 503](#readiness-503--db-connectivity). |
| `429 rate_limited` | Per-minute request limit hit | Honor `Retry-After`; raise `DISTILLERY_SECURITY__RATE_LIMIT_PER_MINUTE`. |
| `distillery db upgrade` fails | DB unreachable or a pending revision | Verify `DISTILLERY_DATABASE__URL`; re-run `alembic upgrade head`. |
| App refuses to start in production | Weak/default JWT secret (<32 chars) or `DISTILLERY_DEBUG=true` | Read the startup error; fix the named setting. |
| Docker image very large / no GPU | Image ships CPU PyTorch wheels | Expected; for GPU rebuild on a CUDA base and set `device=cuda`. |

---

## Authentication (401 / 403)

Distillery accepts **either** an API key or a JWT:

- `X-API-Key: dst_<token>` — long-lived, role-bearing key.
- `Authorization: Bearer <jwt>` — short-lived token from `POST /api/v1/auth/login`.

Roles are ranked **`viewer` < `operator` < `admin`**. Distinguish the two failure modes:

- **`401 unauthenticated`** — the credential is missing, malformed, or invalid (wrong key, expired
  JWT). Re-issue or re-login.
- **`403 forbidden`** — the credential is valid but **the role is too low**, or you are **not the
  owner** of the targeted job.

| Action | Minimum role |
|---|---|
| Read jobs / artifacts (your own) | `viewer` (owner) |
| Create / cancel / delete a job | `operator` |
| Create users (`POST /auth/users`) | `admin` |

```bash
# Who am I, and what role does this credential carry?
curl -s localhost:8000/api/v1/auth/me -H "X-API-Key: $KEY"
```

If a freshly created key fails, confirm it has not expired and that the issuer did not try to mint a
key more privileged than itself (rejected by design). See [Security](../security.md) for the auth
model.

---

## Validation (422 / 400)

A `422 request_validation_error` means the job configuration broke a **cross-field rule**. The
`error.details` payload names the offending field. The rules that trip people up most:

| Rule | Applies to | Requirement |
|---|---|---|
| Shared tokenizer/vocabulary | `response_based`, `feature_based` | Teacher and student must share a tokenizer/vocabulary. A mismatch is rejected. |
| Equal `num_labels` | `response_based`, `feature_based` | Teacher and student must have the **same** `num_labels`. |
| Feature loss weight | `feature_based` | `kd.feature_loss_weight` must be **> 0**. |
| LLM teacher wiring | `llm_teacher` | `teacher_type=llm`, an `llm` config block, and `student.num_labels == len(llm.label_names)`. |
| Inline dataset | `inline` datasets | `inline_rows` must be **non-empty**. |
| Referenced dataset | `hf_hub`, `jsonl`, `csv` | A `reference` must be provided. |

Checklist when you hit a 422:

1. **Strategy vs. teacher.** `llm_teacher` requires `teacher_type=llm` and an `llm` block;
   `response_based`/`feature_based` expect a HuggingFace classifier teacher.
2. **Label arithmetic.** For `llm_teacher`, `student.num_labels` must equal the number of entries in
   `llm.label_names`. For the logit/feature strategies, teacher and student `num_labels` must match.
3. **Feature weight.** `feature_based` with `kd.feature_loss_weight <= 0` is rejected — set it `> 0`.
4. **Dataset source.** Inline data needs `inline_rows`; `hf_hub`/`jsonl`/`csv` need a `reference`.

> A plain `400 validation_error` (vs. `422`) means the router rejected the request before
> domain-level config checks — usually a malformed body.

---

## Job stuck in QUEUED

A job that never leaves `queued` means the work was accepted but no worker picked it up. The cause is
almost always **the worker is not running** or **the broker (Redis) is unreachable**.

Lifecycle for reference: `pending → queued → running → succeeded | failed | cancelled`.

**Diagnose:**

```bash
# Are workers alive and responding?
celery -A distillery.infrastructure.queue.celery_app:celery_app inspect ping
celery -A distillery.infrastructure.queue.celery_app:celery_app inspect active

# Is the broker reachable? (matches DISTILLERY_QUEUE__BROKER_URL, e.g. redis://...:6379/0)
redis-cli -u "$DISTILLERY_QUEUE__BROKER_URL" ping     # expect PONG

# Are worker pods/containers up?
kubectl get pods -l app=distillery-worker
kubectl logs deploy/distillery-worker
```

**Fix:**

1. Start/scale workers: `make run-worker` (local) or
   `kubectl scale deploy/distillery-worker --replicas=N`.
2. Confirm `DISTILLERY_QUEUE__BROKER_URL` points at a reachable Redis and restore Redis if down.
3. Once a worker is healthy the queued job is consumed automatically.

---

## Job stuck in RUNNING (after a worker crash)

Workers use Celery **`acks_late` + `reject_on_worker_lost`**: if a worker dies mid-run the task is
redelivered. The pipeline, however, only proceeds when the job is still **`QUEUED`**. A job left in
**`RUNNING`** after a crash will therefore **not** auto-resume — it needs manual intervention.

**Fix:** manually re-queue or cancel the affected job (then re-create it). Use the `request_id`/
`job_id` to confirm from the logs that the worker actually died rather than still working.

```bash
kubectl logs deploy/distillery-worker | grep <job_id>
# Cancel via the API (operator role), then re-create the job:
curl -s -X POST localhost:8000/api/v1/jobs/<job_id>/cancel -H "X-API-Key: $KEY"
```

---

## FAILED: teacher_error

`teacher_error` (also surfaced as HTTP `502` on synchronous teacher calls) means the **LLM teacher
failed**. Usual causes:

- **Missing/invalid API key** — `DISTILLERY_LLM__ANTHROPIC_API_KEY` unset or wrong.
- **Rate limits** from the upstream LLM provider.
- **Malformed JSON** returned by the model (the response could not be parsed).

**Fix:**

```bash
# Confirm the key is present in the worker environment
kubectl exec deploy/distillery-worker -- printenv | grep DISTILLERY_LLM__
```

1. Set a valid `DISTILLERY_LLM__ANTHROPIC_API_KEY` and restart workers.
2. If rate-limited upstream, lower `DISTILLERY_LLM__MAX_CONCURRENCY` and/or retry later;
   `DISTILLERY_LLM__MAX_RETRIES` and `DISTILLERY_LLM__REQUEST_TIMEOUT_SECONDS` govern resilience.
3. For malformed-JSON failures, re-run; persistent failures usually indicate a prompt/label mismatch
   (revisit `llm.label_names`).

---

## FAILED: training_error / OOM

`training_error` (HTTP `500` class) covers failures inside the training loop. The two common ones:

- **Empty dataloader** — the dataset resolved to zero usable rows. Re-check the dataset
  `reference`/`inline_rows` and any filtering.
- **Out of memory (OOM)** — the model + batch did not fit in available memory.

**OOM remedies (apply in order):**

1. Reduce `training.train_batch_size`.
2. Cap the workload: set `training.max_train_samples` and/or `training.max_steps`.
3. Use a **smaller student** model.
4. Fall back to CPU with `device=cpu` (slower but memory-bound differently).

---

## Readiness 503 / DB connectivity

- **`GET /ready` → `503`** means **PostgreSQL is unreachable**. Readiness runs a real `SELECT 1`
  against the database.
- **`GET /health`** is dependency-free — it returns `200` whenever the process is up. If `/health`
  is `200` but `/ready` is `503`, the app is alive but cannot reach its database.

**Diagnose & fix:**

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/ready    # 503 → DB down
# Check the configured URL the app actually uses:
kubectl exec deploy/distillery-api -- printenv | grep DISTILLERY_DATABASE__URL
```

1. Verify `DISTILLERY_DATABASE__URL` host/port/credentials/database name.
2. Confirm the Postgres instance is up and reachable from the API network/security group.
3. Check pool settings if connections are exhausted (`DISTILLERY_DATABASE__POOL_SIZE`,
   `MAX_OVERFLOW`, `POOL_TIMEOUT_SECONDS`).

Kubernetes uses `/ready` as the readiness probe, so a `503` will pull the pod out of rotation — fix
the DB and the pod re-enters service automatically.

---

## Rate limited (429)

Distillery enforces a **fixed-window, per-minute** limit (default **120**), keyed by **API key or
client IP**. A `429` response includes `Retry-After` plus `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, and `X-RateLimit-Reset`. Probe endpoints (`/health`, `/ready`, `/metrics`,
docs) are exempt.

**Fix:**

1. **Clients:** honor `Retry-After`; spread requests; avoid hot polling loops on job status.
2. **Operators:** raise the ceiling via `DISTILLERY_SECURITY__RATE_LIMIT_PER_MINUTE` and restart the
   API.

```bash
curl -s -D- -o /dev/null localhost:8000/api/v1/jobs -H "X-API-Key: $KEY" | grep -i x-ratelimit
```

---

## Migration failures

Migrations run via `distillery db upgrade` (equivalently `alembic upgrade head`). Failures usually
mean the **database is unreachable** or there is a **pending/unapplied revision**.

```bash
distillery db upgrade        # or: alembic upgrade head
```

**Fix:**

1. Verify `DISTILLERY_DATABASE__URL` and that Postgres is reachable.
2. Re-run the upgrade; resolve any pending revision conflicts.
3. **Kubernetes:** the migration `Job` must succeed **before** the rollout proceeds — inspect it:

```bash
kubectl logs job/distillery-migrate     # name per your manifests/overlay
```

---

## Production startup refusal

Distillery **fails fast** at startup in `production`. It will refuse to start when:

- The **JWT secret is weak/default** (`DISTILLERY_SECURITY__JWT_SECRET` shorter than **32 chars**), or
- **Debug mode is on** (`DISTILLERY_DEBUG=true`).

The startup error **names the offending setting**. Read it and fix that exact variable.

```bash
# Generate a strong secret:
python -c "import secrets; print(secrets.token_urlsafe(64))"
# Set DISTILLERY_SECURITY__JWT_SECRET to the result and DISTILLERY_DEBUG=false in production.
```

See [Security](../security.md) for the full fail-fast policy.

---

## Image size / GPU

- The Docker image is **large because of PyTorch**, and it installs **CPU torch wheels** by default.
  This is expected.
- For **GPU** training, base the image off a **CUDA** image and set **`device=cuda`** (via
  `DISTILLERY_TRAINING__DEVICE=cuda` or per-job `training.device`).

If training is unexpectedly slow on a GPU host, confirm you are running the CUDA-based image and that
`device` is actually `cuda` (not the default CPU wheels). See the
[Deployment guide](deployment-guide.md) for image build details.
