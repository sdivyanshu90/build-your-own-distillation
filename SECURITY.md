# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.x | ✅ |
| < 1.0 | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Email **info@uniiq.ai** with:

- a description of the issue and its impact,
- steps to reproduce (proof-of-concept if possible),
- affected version/commit, and
- any suggested remediation.

You will receive an acknowledgement within **3 business days**. We aim to provide an initial
assessment within **7 days** and to ship a fix or mitigation for confirmed, high-severity issues
within **30 days**, coordinating disclosure with you.

## Scope

In scope: the Distillery application code (API, worker, engine, CLI), default configuration, Docker
image, and Kubernetes manifests in this repository.

Out of scope: vulnerabilities in third-party dependencies (report upstream; we track them via
Dependabot and `pip-audit`), and issues requiring a misconfiguration explicitly warned against in
the docs (e.g. committing the example Kubernetes `Secret`, using a weak `JWT_SECRET`, or disabling
production fail-fast checks).

## Hardening & disclosure

Distillery is built security-first: hashed credentials, RBAC, OWASP secure headers, strict input
validation, rate limiting, non-root hardened containers, and CI security scanning (pip-audit,
Bandit, CodeQL, Trivy, gitleaks). See [docs/security.md](docs/security.md) for the full security
architecture.

Confirmed vulnerabilities are documented in the [CHANGELOG](CHANGELOG.md) and GitHub Security
Advisories after a fix is released. We credit reporters who wish to be acknowledged.
