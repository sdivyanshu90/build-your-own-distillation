"""Enable ``python -m distillery`` as an alias for the Typer CLI."""

from __future__ import annotations

from distillery.cli.main import app

if __name__ == "__main__":  # pragma: no cover
    app()
