"""Distillery command-line interface.

Grouped commands:

* ``distillery serve`` / ``worker`` — run the API server / Celery worker.
* ``distillery db upgrade|create-all|seed`` — manage the database.
* ``distillery user create`` / ``apikey create`` — provision credentials.
* ``distillery distill <config>`` — run a distillation locally (no DB/queue),
  ideal for experimentation and reproducible offline runs.

Run ``distillery --help`` (or any subcommand with ``--help``) for details.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import typer

from distillery.version import __version__

app = typer.Typer(
    name="distillery",
    help="Distillery — NLP model distillation platform.",
    no_args_is_help=True,
    add_completion=False,
)
db_app = typer.Typer(help="Database management commands.", no_args_is_help=True)
user_app = typer.Typer(help="User management commands.", no_args_is_help=True)
key_app = typer.Typer(help="API key management commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(user_app, name="user")
app.add_typer(key_app, name="apikey")


def _echo(message: str) -> None:
    typer.echo(message)


def _load_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        return cast("dict[str, Any]", yaml.safe_load(text))
    return cast("dict[str, Any]", json.loads(text))


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------
@app.command()
def version() -> None:
    """Print the Distillery version."""
    _echo(__version__)


@app.command()
def serve(
    host: str = "0.0.0.0",  # noqa: S104
    port: int = 8000,
    reload: bool = False,
    workers: int = 1,
) -> None:
    """Run the API server (Uvicorn)."""
    import uvicorn

    uvicorn.run(
        "distillery.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
    )


@app.command()
def worker(concurrency: int = 2, loglevel: str = "INFO") -> None:
    """Run a Celery worker that executes distillation jobs."""
    from distillery.infrastructure.queue.celery_app import celery_app

    celery_app.worker_main(
        argv=["worker", f"--concurrency={concurrency}", f"--loglevel={loglevel}"]
    )


@app.command()
def distill(
    config: Path = typer.Argument(..., help="Path to a job config (JSON or YAML)."),
    output: Path = typer.Option(Path("./artifacts/local"), help="Output directory."),
) -> None:
    """Run a distillation locally from a config file (no database or queue)."""
    from distillery.core.engine import DefaultDistillationEngine
    from distillery.domain.value_objects import DistillationConfig

    cfg = DistillationConfig.model_validate(_load_config_file(config))
    output.mkdir(parents=True, exist_ok=True)
    _echo(f"Running {cfg.strategy.value} distillation -> {output}")

    def on_progress(p: Any) -> None:
        _echo(f"  step {p.current_step}/{p.total_steps} ({p.percent:.1f}%) {p.message}")

    result = DefaultDistillationEngine().run(cfg, work_dir=output, on_progress=on_progress)
    report = result.evaluation
    _echo("\nResults:")
    _echo(f"  accuracy           : {report.primary_metric:.4f}")
    _echo(f"  teacher agreement  : {report.teacher_agreement:.4f}")
    _echo(f"  compression ratio  : {report.compression.compression_ratio:.2f}x")
    _echo(f"  student params     : {report.compression.student_params:,}")
    _echo(f"  duration (s)       : {result.resource_usage.duration_seconds}")
    _echo(f"  artifacts          : {[a.type.value for a in result.artifacts]}")


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------
@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply Alembic migrations up to ``revision``."""
    from alembic import command
    from alembic.config import Config

    ini = Path.cwd() / "alembic.ini"
    if not ini.exists():
        raise typer.BadParameter("alembic.ini not found in the current directory")
    command.upgrade(Config(str(ini)), revision)
    _echo(f"Database upgraded to {revision}")


@db_app.command("create-all")
def db_create_all() -> None:
    """Create all tables directly (development convenience; prefer migrations)."""
    from distillery.config.settings import get_settings
    from distillery.infrastructure.db.seed import ensure_schema
    from distillery.infrastructure.db.session import create_db_engine

    ensure_schema(create_db_engine(get_settings().database))
    _echo("Schema created.")


@db_app.command("seed")
def db_seed() -> None:
    """Seed the system user and bootstrap API keys from configuration."""
    from distillery.bootstrap import get_uow_factory
    from distillery.config.settings import get_settings
    from distillery.infrastructure.db.seed import seed_bootstrap

    added = seed_bootstrap(get_uow_factory(), get_settings().security)
    _echo(f"Seed complete ({added} bootstrap key(s) added).")


# ---------------------------------------------------------------------------
# user / apikey
# ---------------------------------------------------------------------------
@user_app.command("create")
def user_create(
    email: str,
    password: str = typer.Option(..., prompt=True, hide_input=True),
    role: str = "viewer",
) -> None:
    """Create a user."""
    from distillery.bootstrap import build_auth_service
    from distillery.domain.enums import Role

    user = build_auth_service().create_user(email=email, password=password, role=Role(role))
    _echo(f"Created user {user.email} (id={user.id}, role={user.role.value})")


@key_app.command("create")
def apikey_create(
    owner_email: str,
    name: str = "cli",
    role: str = "operator",
) -> None:
    """Issue an API key for an existing user (prints the secret once)."""
    from distillery.bootstrap import build_auth_service, get_uow_factory
    from distillery.domain.enums import Role

    with get_uow_factory()() as uow:
        user = uow.users.get_by_email(owner_email)
    if user is None:
        raise typer.BadParameter(f"No user with email {owner_email}")
    api_key, secret = build_auth_service().create_api_key(
        owner_id=user.id, name=name, role=Role(role)
    )
    _echo(f"API key created (prefix={api_key.prefix}).")
    _echo(f"  SECRET (store now, shown once): {secret}")


if __name__ == "__main__":  # pragma: no cover
    app()
