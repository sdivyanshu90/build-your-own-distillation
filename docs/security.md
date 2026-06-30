# Security

This document describes Distillery's security architecture and how it addresses the OWASP Top 10
and supply-chain risks. Report vulnerabilities per [SECURITY.md](../SECURITY.md).

## Authentication

Two mechanisms, both resolved by `infrastructure.security.Authenticator` into a `Principal`:

- **API keys** — format `dst_<token>` (256 bits of entropy). Only a short **prefix** (indexed) and
  the **SHA-256 digest** are stored; the plaintext is shown exactly once at creation. Because keys
  are high-entropy, a fast cryptographic hash with constant-time comparison is appropriate (a slow
  KDF would needlessly tax every request). Keys carry a role and optional expiry, and stamp
  `last_used_at`.
- **JWT** (HS256, PyJWT) — issued at `POST /auth/login` after password verification; carries `sub`
  and `role`, with `iss`, `iat`, `exp`; verified with required-claims enforcement.

**Passwords** are hashed with **PBKDF2-HMAC-SHA256** (600k iterations, per-user salt, versioned
encoding) and verified in constant time. Argon2id is a documented drop-in upgrade.

## Authorization (RBAC)

Roles: `viewer` < `operator` < `admin` (ranked). Endpoints enforce a minimum role via the
`require_role` dependency; resource-level checks ensure owners access only their own jobs (admins any).
A principal cannot mint an API key more privileged than itself.

## Secrets management

- All secrets come from the environment / a secret manager — never the code or VCS. `.env` is
  gitignored; only `.env.example` (placeholders) is committed.
- `SecretStr` wraps secrets in settings so they don't leak via logs/`repr`.
- Bootstrap API keys are provided as plaintext config but **hashed at startup**; never stored in clear.
- Kubernetes: the committed `secret.example.yaml` is a **template** — use AWS Secrets Manager / Vault
  / Sealed Secrets / External Secrets in real clusters. The LLM/AWS keys are mounted as a Secret.
- **Production fail-fast**: the app refuses to start in `production` with a weak/default JWT secret
  (<32 chars) or `debug=true`.

## Input validation

- Every request body and query param is validated by **Pydantic** (types, ranges, enums, cross-field
  rules). Invalid input → `422 request_validation_error` with safe, structured details.
- Domain value objects are `frozen`/`extra="forbid"`, rejecting unknown fields and mutation.
- Request **body size** is capped (`max_request_body_bytes`, default 10 MiB → `413`).

## OWASP Top 10 mapping

| Risk | Mitigation |
|---|---|
| A01 Broken access control | RBAC + per-resource ownership checks; least-privilege keys. |
| A02 Cryptographic failures | PBKDF2 passwords, SHA-256 keys, TLS in transit, `SecretStr`. |
| A03 Injection | SQLAlchemy parameterised queries (no string SQL); Pydantic validation. |
| A04 Insecure design | Clean Architecture, explicit state machine, fail-fast prod config. |
| A05 Security misconfiguration | Secure-by-default headers, docs off in prod, non-root containers. |
| A06 Vulnerable components | `pip-audit`, Dependabot, Trivy image scans, pinned base images. |
| A07 Auth failures | Constant-time checks, key expiry, JWT exp/iss validation, rate limiting. |
| A08 Integrity failures | Artifact SHA-256 checksums; SBOM + provenance on release images. |
| A09 Logging/monitoring | Structured logs with `request_id`, metrics, alert rules, audit events. |
| A10 SSRF | `trust_remote_code` defaults **off**; model/dataset refs are explicit, not user-fetched URLs by default. |

## Web hardening

The `SecurityHeadersMiddleware` sets, on every response:
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`,
`Strict-Transport-Security` (2 years, includeSubDomains), `Cache-Control: no-store`, `X-XSS-Protection: 0`.
CORS is allow-list driven (`DISTILLERY_API__CORS_ORIGINS`).

- **CSRF**: the API is token-authenticated (API key / bearer), not cookie-based, so it is not
  susceptible to classic CSRF; do not introduce cookie auth without CSRF protection.
- **XSS**: the API returns JSON only; rendering is the client's responsibility.
- **Rate limiting**: fixed-window per key/IP (Redis-backed in production) to blunt brute force/DoS.

## Container & runtime hardening

- Non-root user, **read-only root filesystem**, dropped Linux capabilities, `seccompProfile:
  RuntimeDefault`, `allowPrivilegeEscalation: false`, namespace `pod-security: restricted`.
- Minimal slim base image; `tini` as PID 1.
- Service account token automount disabled.

## Supply-chain security

- **Dependency management**: pinned lower bounds in `pyproject.toml`; Dependabot for pip, GitHub
  Actions, and Docker; `pip-audit` in CI.
- **Static analysis**: Bandit (`pyproject` config) and Ruff's `S` (bandit) ruleset.
- **Secret scanning**: gitleaks (pre-commit + CI), `detect-private-key` hook.
- **Image scanning**: Trivy (CRITICAL/HIGH) with SARIF upload; **SBOM + provenance** attestations on
  released images.
- **Code scanning**: CodeQL on every push/PR and weekly.

## Auditing

Domain events (`JobStarted/Progressed/Completed/Failed`) are published to the structured log,
forming a tamper-evident-ready audit trail keyed by `request_id`/`job_id`. Ship logs to a central,
append-only store (e.g. Loki/CloudWatch) for retention and SIEM integration.
