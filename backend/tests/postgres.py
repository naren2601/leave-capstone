"""Shared helpers for tests that need a real PostgreSQL.

Set LEAVEDESK_TEST_DATABASE_URL to a server where this user may create
databases, for example the db service from docker-compose.yml:

    LEAVEDESK_TEST_DATABASE_URL=postgresql+psycopg://leavedesk:<password>@localhost:5432/postgres

Each test session creates a fresh, uniquely named database, runs every Alembic
migration on it, and drops it at the end. Without the variable these tests are
skipped, so the rest of the suite still runs anywhere.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("LEAVEDESK_TEST_DATABASE_URL")

# Marks tests that need PostgreSQL, so they are skipped without a database.
requires_postgres = pytest.mark.skipif(
    not ADMIN_URL, reason="LEAVEDESK_TEST_DATABASE_URL is not set"
)


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.attributes["database_url"] = url
    return config


@contextmanager
def temporary_database() -> Iterator[str]:
    """Create an empty database, yield its URL, then drop it."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    name = f"leavedesk_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
