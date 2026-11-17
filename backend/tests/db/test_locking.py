"""Proof that SELECT ... FOR UPDATE makes concurrent changes take turns.

Transaction A loads a request (which locks it) and holds the lock. Transaction B
tries to approve the same request and must wait. Only when A finishes does B carry
on, and by then it sees A's change.
"""

import asyncio
import threading
import uuid
from datetime import date

from sqlalchemy.orm import Session

from leavedesk.api.state import SEED_PEOPLE
from leavedesk.db.repository import PostgresLeaveRepository
from leavedesk.db.seed import seed_tenant
from leavedesk.domain.exceptions import InvalidTransitionError
from leavedesk.domain.models import LeaveStatus, LeaveType
from leavedesk.domain.service import LeaveService
from tests.postgres import requires_postgres

pytestmark = requires_postgres

TODAY = date(2026, 11, 9)


def test_a_locked_request_makes_the_second_approval_wait(engine):
    with Session(engine) as setup, setup.begin():
        tenant_id = seed_tenant(setup, f"Locking {uuid.uuid4().hex[:6]}", SEED_PEOPLE, TODAY.year)
        repo = PostgresLeaveRepository(setup, tenant_id, TODAY.year)
        service = LeaveService(repo, today=lambda: TODAY)
        request = asyncio.run(
            service.apply("e1", LeaveType.ANNUAL, date(2026, 11, 16), date(2026, 11, 18), "Trip!")
        )

    a_has_lock, a_may_finish = threading.Event(), threading.Event()
    outcome = {}

    def transaction_a():
        with Session(engine) as session, session.begin():
            repo = PostgresLeaveRepository(session, tenant_id, TODAY.year)
            service = LeaveService(repo, today=lambda: TODAY)
            repo.get_request(request.id)  # SELECT ... FOR UPDATE: the row is now locked
            a_has_lock.set()
            a_may_finish.wait(timeout=10)
            asyncio.run(service.approve(request.id, "m1"))

    def transaction_b():
        a_has_lock.wait(timeout=10)
        with Session(engine) as session, session.begin():
            service = LeaveService(
                PostgresLeaveRepository(session, tenant_id, TODAY.year), today=lambda: TODAY
            )
            try:
                asyncio.run(service.approve(request.id, "m1"))
                outcome["b"] = "approved"
            except InvalidTransitionError:
                outcome["b"] = "already approved"

    a = threading.Thread(target=transaction_a)
    b = threading.Thread(target=transaction_b)
    a.start()
    b.start()

    b.join(timeout=0.5)
    assert b.is_alive(), "B should be waiting for A's lock"

    a_may_finish.set()
    a.join(timeout=10)
    b.join(timeout=10)

    assert outcome["b"] == "already approved"
    with Session(engine) as check:
        repo = PostgresLeaveRepository(check, tenant_id, TODAY.year)
        assert repo.get_request(request.id).status is LeaveStatus.APPROVED
        assert repo.find_balance("e1", LeaveType.ANNUAL).used == 3
