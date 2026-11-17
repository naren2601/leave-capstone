"""PostgresLeaveRepository: the Day 1 service working on real PostgreSQL rows."""

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from leavedesk.api.state import SEED_PEOPLE
from leavedesk.db import models as db
from leavedesk.db.repository import PostgresLeaveRepository
from leavedesk.db.seed import seed_tenant
from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    NotFoundError,
    OverlappingLeaveError,
)
from leavedesk.domain.models import DayPart, LeaveRequest, LeaveStatus, LeaveType, Manager
from leavedesk.domain.service import LeaveService
from tests.postgres import requires_postgres

pytestmark = requires_postgres

TODAY = date(2026, 11, 9)  # a Monday
MONDAY, WEDNESDAY = date(2026, 11, 16), date(2026, 11, 18)


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def repo(session) -> PostgresLeaveRepository:
    tenant_id = seed_tenant(session, "Repository tests", SEED_PEOPLE, TODAY.year)
    return PostgresLeaveRepository(session, tenant_id, TODAY.year)


@pytest.fixture
def service(repo) -> LeaveService:
    return LeaveService(repo, today=lambda: TODAY)


def balance_and_ledger(repo, employee="e1", leave_type=LeaveType.ANNUAL):
    balance = repo.find_balance(employee, leave_type)
    ledger = repo.ledger_total(employee, leave_type)
    return balance, ledger


def assert_balance_matches_ledger(repo, employee="e1", leave_type=LeaveType.ANNUAL):
    balance, ledger = balance_and_ledger(repo, employee, leave_type)
    assert Decimal(str(balance.entitled)) == ledger["entitled"]
    assert Decimal(str(balance.pending)) == ledger["pending"]
    assert Decimal(str(balance.used)) == ledger["used"]


def movements(session, repo, with_request_only: bool = False) -> list[str]:
    """This tenant's ledger movements, oldest first. Other tests' tenants are ignored."""
    query = select(db.LeaveLedger.movement).where(db.LeaveLedger.tenant_id == repo.tenant_id)
    if with_request_only:
        query = query.where(db.LeaveLedger.leave_request_id.is_not(None))
    return list(session.scalars(query.order_by(db.LeaveLedger.id)))


# Employees


def test_employees_come_back_as_domain_objects(repo):
    ravi = repo.get_employee("m1")
    asha = repo.get_employee("e1")

    assert isinstance(ravi, Manager)
    assert asha.manager_id == "m1"
    assert [e.id for e in repo.list_employees()] == ["e1", "e2", "e3", "m1", "m2"]


def test_unknown_employee_is_not_found(repo):
    with pytest.raises(NotFoundError):
        repo.get_employee("nobody")


@pytest.mark.parametrize(
    "request_id", ["LR-999", "not-a-uuid", "0190c4c8-0000-7000-8000-000000000000"]
)
def test_unknown_request_is_not_found(repo, request_id):
    with pytest.raises(NotFoundError):
        repo.get_request(request_id)


# Balances always equal the sum of the ledger


def test_seeded_balances_start_with_an_entitlement(repo, session):
    balance, ledger = balance_and_ledger(repo)

    assert balance.entitled == 18 and balance.available == 18
    assert ledger == {"entitled": Decimal("18.0"), "pending": 0, "used": 0}


def test_full_life_of_a_request_is_in_the_ledger(repo, service, session):
    first = run(service.apply("e1", LeaveType.ANNUAL, MONDAY, WEDNESDAY, "Family trip"))
    assert_balance_matches_ledger(repo)

    run(service.approve(first.id, "m1"))
    assert_balance_matches_ledger(repo)

    nov_23, nov_24 = date(2026, 11, 23), date(2026, 11, 24)
    second = run(service.apply("e1", LeaveType.ANNUAL, nov_23, nov_23, "Bank work"))
    run(service.reject(second.id, "m1", "Release week"))
    third = run(service.apply("e1", LeaveType.ANNUAL, nov_24, nov_24, "Bank work"))
    run(service.cancel(third.id, "e1"))

    assert_balance_matches_ledger(repo)
    balance = repo.find_balance("e1", LeaveType.ANNUAL)
    assert (balance.used, balance.pending, balance.available) == (3, 0, 15)
    # apply, approve; apply, reject; apply, cancel
    request_movements = movements(session, repo, with_request_only=True)
    assert request_movements == ["RESERVE", "CONSUME", "RESERVE", "RELEASE", "RESERVE", "RELEASE"]


def test_cancelling_approved_leave_restores_used_days(repo, service, session):
    request = run(service.apply("e1", LeaveType.ANNUAL, MONDAY, WEDNESDAY, "Family trip"))
    run(service.approve(request.id, "m1"))

    run(service.cancel(request.id, "e1"))

    assert repo.get_request(request.id).status is LeaveStatus.CANCELLED
    assert repo.find_balance("e1", LeaveType.ANNUAL).available == 18
    assert movements(session, repo)[-1] == "RESTORE"
    assert_balance_matches_ledger(repo)


def test_half_days_are_stored_exactly(repo, service):
    request = run(service.apply("e1", LeaveType.CASUAL, MONDAY, MONDAY, "Bank work", DayPart.AM))

    assert repo.get_request(request.id).days == 0.5
    assert repo.find_balance("e1", LeaveType.CASUAL).available == 5.5
    assert_balance_matches_ledger(repo, leave_type=LeaveType.CASUAL)


def test_requests_round_trip(repo, service):
    saved = run(service.apply("e1", LeaveType.SICK, MONDAY, WEDNESDAY, "Fever and rest"))

    loaded = repo.get_request(saved.id)

    assert loaded == saved
    assert [r.id for r in repo.requests_for("e1")] == [saved.id]
    assert repo.requests_for("e2") == []


# The database catches what the domain cannot see: races


def _sneak_in(repo, request_id, **changes) -> LeaveRequest:
    """Save a request directly, skipping the service's checks (as a race would)."""
    values = {
        "id": request_id,
        "employee_id": "e1",
        "leave_type": LeaveType.ANNUAL,
        "start_date": MONDAY,
        "end_date": WEDNESDAY,
        "reason": "Family trip",
        "days": 3,
    } | changes
    request = LeaveRequest(**values)
    repo.save_request(request)
    return request


def test_overlap_missed_by_the_service_is_still_rejected(repo, session):
    _sneak_in(repo, repo.next_request_id())

    savepoint = session.begin_nested()
    with pytest.raises(OverlappingLeaveError):
        _sneak_in(repo, repo.next_request_id(), start_date=WEDNESDAY, end_date=WEDNESDAY, days=1)
    savepoint.rollback()


def test_overspend_missed_by_the_service_is_still_rejected(repo, session):
    request = _sneak_in(repo, repo.next_request_id())
    balance = repo.find_balance("e1", LeaveType.ANNUAL)
    balance.pending = 19  # more than the 18 days entitled

    savepoint = session.begin_nested()
    with pytest.raises(InsufficientBalanceError):
        repo.save_changes(request, balance)
    savepoint.rollback()


# Tenants never see each other's data


def test_tenants_are_isolated(session, repo, service):
    run(service.apply("e1", LeaveType.ANNUAL, MONDAY, WEDNESDAY, "Family trip"))
    other_id = seed_tenant(session, "Another company", SEED_PEOPLE, TODAY.year)
    other = PostgresLeaveRepository(session, other_id, TODAY.year)

    assert other.requests_for("e1") == []
    assert other.find_balance("e1", LeaveType.ANNUAL).available == 18


def test_seeding_twice_changes_nothing(session):
    first = seed_tenant(session, "Seed twice", SEED_PEOPLE, TODAY.year)
    count = session.scalar(select(func.count()).select_from(db.Employee))

    assert seed_tenant(session, "Seed twice", SEED_PEOPLE, TODAY.year) == first
    assert session.scalar(select(func.count()).select_from(db.Employee)) == count


# No N+1 queries


class QueryCounter:
    def __init__(self, session: Session) -> None:
        self.count = 0
        self.connection = session.connection()

    def __enter__(self):
        event.listen(self.connection, "before_cursor_execute", self._count)
        return self

    def __exit__(self, *exc):
        event.remove(self.connection, "before_cursor_execute", self._count)

    def _count(self, *args):
        self.count += 1


def _queries_to_list(repo, session, employee="e1") -> int:
    session.expire_all()
    with QueryCounter(session) as counter:
        repo.requests_for(employee)
    return counter.count


def test_listing_requests_takes_the_same_queries_for_1_or_many(repo, service, session):
    run(service.apply("e1", LeaveType.SICK, MONDAY, MONDAY, "Fever and rest"))
    one = _queries_to_list(repo, session)

    for day in (17, 18, 19, 20):
        run(service.apply("e1", LeaveType.SICK, date(2026, 11, day), date(2026, 11, day), "Fever"))
    many = _queries_to_list(repo, session)

    assert one == many  # not one extra query per request


def test_listing_employees_does_not_load_managers_one_by_one(repo, session):
    session.expire_all()
    with QueryCounter(session) as counter:
        employees = repo.list_employees()

    assert len(employees) == 5
    assert counter.count == 2  # employees, then all their managers in one query
