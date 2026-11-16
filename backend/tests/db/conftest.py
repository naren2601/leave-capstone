"""Fixtures for tests that need a real PostgreSQL.

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
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from leavedesk.db.models import (
    Employee,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Tenant,
)

BACKEND = Path(__file__).resolve().parents[2]
ADMIN_URL = os.environ.get("LEAVEDESK_TEST_DATABASE_URL")

# Every test module in tests/db/ uses this, so it is skipped without a database.
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


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if not ADMIN_URL:
        pytest.skip("LEAVEDESK_TEST_DATABASE_URL is not set")
    with temporary_database() as url:
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture(scope="session")
def engine(database_url) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    """A session whose changes are all rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def org(session):
    """A small company: one manager, two employees and annual leave."""
    tenant = Tenant(name=f"Acme {uuid.uuid4().hex[:6]}")
    session.add(tenant)
    session.flush()

    ravi = Employee(
        tenant_id=tenant.id, code="m1", name="Ravi", email="ravi@acme.dev", is_manager=True
    )
    session.add(ravi)
    session.flush()
    asha = Employee(
        tenant_id=tenant.id, code="e1", name="Asha", email="asha@acme.dev", manager_id=ravi.id
    )
    kiran = Employee(
        tenant_id=tenant.id, code="e2", name="Kiran", email="kiran@acme.dev", manager_id=ravi.id
    )
    annual = LeaveType(
        tenant_id=tenant.id,
        code="ANNUAL",
        name="Annual leave",
        days_per_year=Decimal("18"),
        min_start_offset_days=3,
    )
    session.add_all([asha, kiran, annual])
    session.flush()
    session.add(
        LeaveBalance(
            tenant_id=tenant.id,
            employee_id=asha.id,
            leave_type_id=annual.id,
            year=2026,
            entitled=Decimal("18"),
        )
    )
    session.flush()
    return {"tenant": tenant, "ravi": ravi, "asha": asha, "kiran": kiran, "annual": annual}


@pytest.fixture
def make_request(session, org):
    """make_request(start, end, ...) adds a leave request for Asha and flushes it."""

    def make(start: date, end: date | None = None, **changes) -> LeaveRequest:
        values = {
            "tenant_id": org["tenant"].id,
            "employee_id": org["asha"].id,
            "leave_type_id": org["annual"].id,
            "start_date": start,
            "end_date": end or start,
            "reason": "Family trip",
            "days": Decimal("1"),
            **changes,
        }
        request = LeaveRequest(**values)
        session.add(request)
        session.flush()
        return request

    return make


@pytest.fixture
def rejected(session):
    """with rejected("constraint_name"): ... checks the database refuses the change.

    The change runs in a savepoint, so the test can carry on afterwards.
    """

    @contextmanager
    def check(constraint: str) -> Iterator[None]:
        savepoint = session.begin_nested()
        with pytest.raises(DBAPIError) as caught:
            yield
            session.flush()
        savepoint.rollback()
        diag = getattr(caught.value.orig, "diag", None)
        found = (getattr(diag, "constraint_name", None) or "") + str(caught.value.orig)
        assert constraint in found, f"expected {constraint!r}, got: {caught.value.orig}"

    return check
