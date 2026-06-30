"""ASGI application object for production servers.

Gunicorn/Uvicorn import ``distillery.api.asgi:app``. The app is created once at
import time. (For local development with reload, prefer the factory form
``distillery.api.app:create_app`` with ``--factory``.)
"""

from __future__ import annotations

from distillery.api.app import create_app

app = create_app()
