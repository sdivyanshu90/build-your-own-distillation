# Deployment architecture

## Local (Docker Compose)

One image, multiple roles. `make up` starts the full stack.

```mermaid
flowchart TB
    subgraph compose [docker-compose]
      migrate[migrate (one-shot)] --> api
      api[api :8000] --- worker[worker]
      api --> pg[(postgres :5432)]
      worker --> pg
      api --> redis[(redis :6379)]
      worker --> redis
      api --> artifacts[(artifacts volume)]
      worker --> artifacts
      prom[prometheus :9090] --> api
      graf[grafana :3000] --> prom
    end
```

Startup order is enforced with healthchecks: `migrate` runs after `postgres` is healthy and must
complete before `api`/`worker` start (`depends_on: service_completed_successfully`).

## Kubernetes (Kustomize)

```mermaid
flowchart TB
    subgraph ns [namespace: distillery]
      ing[Ingress + TLS] --> svc[Service: distillery-api]
      svc --> apipods[Deployment: api x3-10 + HPA + PDB]
      job[Job: distillery-migrate (PreSync)]
      workerpods[Deployment: worker x2-4 + PDB]
      cm[ConfigMap] --- apipods
      cm --- workerpods
      sec[Secret] --- apipods
      sec --- workerpods
    end
    apipods --> pg[(Managed PostgreSQL)]
    workerpods --> pg
    apipods --> redis[(Managed Redis)]
    workerpods --> redis
    workerpods --> s3[(S3 bucket)]
    apipods -. scrape .-> prom[Prometheus]
```

### What's in `deploy/kubernetes/`

| Resource | Purpose |
|---|---|
| `namespace.yaml` | Namespace with `pod-security: restricted`. |
| `serviceaccount.yaml` | Dedicated SA, token automount disabled. |
| `configmap.yaml` | Non-secret config (env, queue URLs, storage backend). |
| `secret.example.yaml` | **Template** for secrets (DB URL, JWT, API keys, AWS). Use a real secret manager. |
| `deployment-api.yaml` | API: startup/liveness/readiness probes, resources, non-root, read-only FS, topology spread. |
| `deployment-worker.yaml` | Worker: long `terminationGracePeriod`, `celery inspect ping` liveness. |
| `service.yaml` | ClusterIP for the API. |
| `ingress.yaml` | nginx ingress + cert-manager TLS. |
| `hpa-api.yaml` | Autoscale API on CPU/memory. |
| `pdb.yaml` | PodDisruptionBudgets for API and worker. |
| `migration-job.yaml` | Alembic migrations as a pre-deploy Job (Argo PreSync hook annotations). |
| `overlays/staging`, `overlays/production` | Per-env image tags, replica counts, resources, env flags. |

Deploy:

```bash
kubectl apply -k deploy/kubernetes/overlays/staging
kubectl apply -k deploy/kubernetes/overlays/production
```

### Image

A single multi-stage image (`deploy/docker/Dockerfile`) builds a venv with CPU PyTorch, runs as a
non-root user with a read-only root filesystem, and dispatches roles via `entrypoint.sh`
(`api` | `worker` | `beat` | `migrate`). `tini` reaps zombies and forwards signals.

### Scaling & rollout

- **API**: HPA 3→10 on 70% CPU / 80% memory; rolling update `maxUnavailable: 0`.
- **Workers**: scale on queue depth (KEDA/Prometheus adapter recommended); can scale to zero.
- **Migrations**: run as a gate before rollout; never auto-`create_all` in production.
- **Rollback**: `kubectl rollout undo deploy/distillery-api` (and worker); migrations are
  forward-compatible within a release — see the [deployment guide](../guides/deployment-guide.md).

### External managed services (production)

- **PostgreSQL**: managed (RDS/Cloud SQL) with automated backups + PITR and TLS.
- **Redis**: managed (ElastiCache/Memorystore) with TLS + AUTH.
- **Object storage**: S3/GCS/R2 with versioning + lifecycle rules.
- **Secrets**: AWS Secrets Manager / Vault / External Secrets Operator (not the example Secret).
