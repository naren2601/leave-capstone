"""Day 3, step 6: the indexes are used, and lists do not get slower per team member.

Uses the performance seeder at a smaller size (5,000 requests), so it runs in a
few seconds. The real 100,000-row measurements are in PERF.md.
"""

import json
import re
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from leavedesk.db import models as db
from leavedesk.db.perf import seed
from leavedesk.db.repository import PostgresLeaveRepository
from leavedesk.domain.models import LeaveStatus
from tests.postgres import requires_postgres

pytestmark = requires_postgres


@pytest.fixture(scope="module")
def perf_tenant(engine) -> int:
    name = f"Perf test {uuid.uuid4().hex[:6]}"
    with Session(engine) as session, session.begin():
        seed(session, name, managers=10, reports=49, per_employee=10)
    with Session(engine) as session:
        return session.scalar(select(db.Tenant.id).where(db.Tenant.name == name))


def plan_of(session: Session, query) -> str:
    """The plan as JSON text. enable_seqscan=off asks: CAN an index serve this query?"""
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    session.execute(select(1))  # start the transaction, so SET LOCAL applies
    session.connection().exec_driver_sql("SET LOCAL enable_seqscan = off")
    plan = session.connection().exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql).scalar()
    return json.dumps(plan)


def test_the_pending_queue_uses_the_pending_index(engine, perf_tenant):
    with Session(engine) as session:
        repo = PostgresLeaveRepository(session, perf_tenant, 2026)
        team = {e.id for e in repo.direct_reports("m3")}
        query = repo.request_page_query(
            repo.request_list_query(team, LeaveStatus.PENDING), descending=False, limit=21
        )
        assert "ix_leave_requests_pending" in plan_of(session, query)


def test_history_and_keyset_use_the_history_index(engine, perf_tenant):
    with Session(engine) as session:
        repo = PostgresLeaveRepository(session, perf_tenant, 2026)
        history = repo.request_list_query({"e7"}, None)
        first = session.scalars(repo.request_page_query(history, False, 3)).all()
        after = (first[-1].start_date, str(first[-1].id))
        query = repo.request_page_query(history, False, 3, after=after)
        plan = plan_of(session, query)

    assert "ix_leave_requests_history" in plan
    # The cursor is part of the index condition: rows before it are never read.
    conditions = re.findall(r'"Index Cond": "([^"]*)"', plan)
    assert any("start_date" in condition for condition in conditions)


def test_name_search_can_use_the_trigram_index(engine, perf_tenant):
    # Without the tenant filter: in this small test tenant the planner may rightly
    # prefer the tenant index. With 10,000 employees it picks trigrams (PERF.md).
    with Session(engine) as session:
        query = select(db.Employee).where(db.Employee.name.ilike("%meena kh%"))
        assert "ix_employees_name_trgm" in plan_of(session, query)


def test_a_bigger_team_does_not_mean_more_queries(engine, perf_tenant):
    """No N+1: listing a manager's team costs the same few queries for 1 or 49 reports."""

    def queries_for(employee_ids: set[str]) -> int:
        statements = []
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            with Session(engine) as session:
                repo = PostgresLeaveRepository(session, perf_tenant, 2026)
                reports = {e.id for e in repo.direct_reports("m5")}
                repo.page_requests(set(list(sorted(reports))[: len(employee_ids)]), None, False, 20)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    assert queries_for({"one"}) == queries_for(set(range(49)))
