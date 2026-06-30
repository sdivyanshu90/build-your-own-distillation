# Distillery documentation

**Distillery** distils large NLP teacher transformers into small, fast student models — exposed as a
hardened REST API with asynchronous training workers, durable job tracking, and full observability.

New here? Start with the [project README](https://github.com/uniiq-ai/distillery#readme) for a
quickstart, then dive into:

## Architecture
- [Overview](architecture/overview.md) — design goals, layering, components, NFRs, rationale.
- [Folder structure](architecture/folder-structure.md) — file-by-file tour.
- [Sequence diagrams](architecture/sequence-diagrams.md) · [Data flow](architecture/data-flow.md) ·
  [Deployment](architecture/deployment.md)

## Reference
- [API reference](api/reference.md) — endpoints, auth, errors, examples.
- [Database design](database.md) — ER diagram, schema, migrations.
- [Security](security.md) — auth, OWASP, secrets, supply chain.

## Guides
- [User guide](guides/user-guide.md) · [Developer guide](guides/developer-guide.md)
- [Administrator guide](guides/administrator-guide.md) · [Deployment guide](guides/deployment-guide.md)
- [Troubleshooting](guides/troubleshooting.md)

## Operations
- [Runbook](operations/runbook.md) — on-call procedures, alerts, DR.
- [Architecture Decision Records](decisions/README.md)

## The three distillation strategies

| Strategy | Idea |
|---|---|
| `response_based` | Match the teacher's softened logits (KL) + ground-truth cross-entropy. |
| `feature_based` | Response KD **plus** intermediate hidden-state alignment. |
| `llm_teacher` | An LLM generates/labels a corpus; the student is then supervised fine-tuned. |
