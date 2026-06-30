# ADR-0003: Asynchronous Execution with Celery + Redis

## Status

Accepted

## Date

2026-01-15

## Context

Distillation training is long-running and CPU/GPU-bound. Running it inside an API
request would block the request, tie up web workers, offer no isolation, and
make horizontal scaling impossible. We need to move training off the request
path while keeping the system reliable in the face of worker crashes and
redeliveries.

## Decision

We execute training asynchronously using Celery with Redis. The API only
enqueues a job; dedicated workers pick it up and run it through the
`PipelineService`.

Reliability settings:

- `task_acks_late` together with `reject_on_worker_lost` so a task that dies with
  its worker is redelivered rather than lost.
- `worker_prefetch_multiplier = 1` for fair dispatch of long tasks across
  workers (no greedy prefetching).

The pipeline is idempotent: it only proceeds if the job is still in the `QUEUED`
state, so a redelivered task will not double-run work that already progressed.

Redis serves three roles: the Celery broker, the result backend, and the store
for the distributed rate limiter.

For development and tests we provide an `InlineTaskQueue` (eager mode) that runs
jobs synchronously in-process, removing the need for a broker and workers during
local iteration.

## Consequences

### Positive

- The API stays responsive; training never blocks request handling.
- Workers can be scaled independently and isolated from the web tier.
- Late acks + reject-on-worker-loss + idempotency give at-least-once delivery
  without duplicate side effects.
- One infrastructure component (Redis) covers broker, results, and rate limiting.

### Negative

- Operational footprint: a broker and worker fleet must be deployed and
  monitored.
- Asynchronous flows are harder to trace and debug than synchronous calls.
- Redis becomes a critical shared dependency across several concerns.

### Mitigations

- The `InlineTaskQueue` eager mode makes local dev and tests synchronous and
  broker-free.
- Idempotent, status-gated pipeline execution makes redeliveries safe.

## Alternatives considered

- **RQ / Arq / Dramatiq**: viable task queues, but Celery's maturity, late-ack
  semantics, and ecosystem fit our reliability needs; Redis is already required.
- **Running training in-process in the API**: rejected — it blocks the API,
  provides no isolation, and cannot scale independently.
