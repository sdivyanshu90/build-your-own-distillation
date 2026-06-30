# Contributing to Distillery

Thanks for your interest in improving Distillery! This guide gets you productive quickly.

## Development setup

```bash
git clone https://github.com/uniiq-ai/distillery.git
cd distillery
make install        # creates .venv and installs ".[dev]"
make install-hooks  # pre-commit hooks (ruff, black, mypy, bandit, gitleaks)
make check          # lint + typecheck + tests — should pass before you start
```

Python 3.10–3.12 is supported. The ML stack (torch/transformers) is installed via the `dev` extra.

## Workflow

1. Create a branch from `main`: `git checkout -b feat/short-description`.
2. Make focused changes with tests.
3. Run the full gate locally: `make check` (lint, types, tests, coverage ≥95%).
4. Update docs (`docs/`, docstrings, `README`) and add a `CHANGELOG.md` entry under **Unreleased**.
5. Open a PR using the template; CI must be green.

### Quality gates

| Command | Checks |
|---|---|
| `make lint` | Ruff + Black (`--check`). Run `make format` to auto-fix. |
| `make typecheck` | mypy (`src/distillery`). |
| `make test` | pytest with coverage; fails under 95%. |
| `make security` | pip-audit + Bandit. |

## Conventions

- **Clean Architecture dependency rule**: inner layers (`domain`, `application`) must not import outer
  layers (`infrastructure`, `api`). Depend on **ports** (`domain/ports.py`), not concretions.
- New behaviour goes through the appropriate layer; wiring happens only in `bootstrap.py`.
- Keep heavy imports (`torch`, `celery`, `boto3`) lazy/local so import time stays fast.
- Line length 100; format with Black; lint with Ruff; type with mypy.
- Public functions/classes get concise docstrings; match the surrounding style.

## Adding a distillation strategy

1. Subclass `distillery.core.strategies.base.DistillationStrategy` and implement `compute_loss`
   (and optionally `setup` / `aux_parameters` / `requires_teacher`).
2. Add the enum value to `distillery.domain.enums.DistillationStrategy` and any cross-field rules to
   `distillery.domain.value_objects.DistillationConfig`.
3. Register a factory in `distillery.core.strategies.registry`.
4. Add unit tests under `tests/unit/` (use the offline `config_only=True` tiny-model path).

See the [developer guide](docs/guides/developer-guide.md) for a complete example.

## Tests

- Markers: `unit`, `integration`, `e2e`, `ml`, `slow`. Run a subset with `pytest -m unit`.
- Favour the offline tiny-model path (`ModelSpec(config_only=True)` + inline datasets) so tests are
  fast and need no network.
- New code should keep meaningful coverage at or above 95%.

## Commit messages

Use clear, imperative subjects (e.g. `Add feature-based layer mapping override`). Conventional
Commits are welcome but not required. Keep PRs focused and reviewable.

## Reporting bugs / requesting features

Use the GitHub issue templates. For security issues, **do not** open a public issue — see
[SECURITY.md](SECURITY.md).

By contributing, you agree your contributions are licensed under the project's
[Apache 2.0 License](LICENSE).
