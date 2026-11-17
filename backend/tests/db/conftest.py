"""Fixtures for the database tests: a session that rolls back, and sample rows.

The migrated test database itself comes from tests/conftest.py.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from leavedesk.db.models import (
    Employee,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Tenant,
)


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
