"""Declarative base and shared column types.

A consistent constraint-naming convention is configured so that Alembic produces
stable, predictable migration names. A portable JSON type stores value objects:
native ``JSONB`` on PostgreSQL, generic ``JSON`` elsewhere (e.g. SQLite in tests).
"""

from __future__ import annotations

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

# JSONB on Postgres (indexable, efficient); plain JSON on other backends.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = metadata
