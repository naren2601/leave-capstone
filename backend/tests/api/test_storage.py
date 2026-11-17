"""Day 3: the API really stores its data in PostgreSQL."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from leavedesk.api.main import create_app
from leavedesk.db import models as db
from tests.api.conftest import TODAY
from tests.postgres import requires_postgres

pytestmark = requires_postgres

BODY = {
    "leave_type": "ANNUAL",
    "start_date": "2026-11-16",
    "end_date": "2026-11-18",
    "reason": "Family trip",
}


@pytest.fixture
def backend() -> str:
    return "postgres"


def test_data_survives_a_restart(settings, auth):
    first = create_app(settings, today=lambda: TODAY)
    request_id = (
        TestClient(first).post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]
    )
    first.state.leavedesk.close()

    second = create_app(settings, today=lambda: TODAY)
    response = TestClient(second).get(f"/leave-requests/{request_id}", headers=auth("e1"))
    second.state.leavedesk.close()

    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"


def test_request_ids_are_uuid7(client, auth):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]

    assert uuid.UUID(request_id).version == 7


def test_a_failed_request_leaves_nothing_behind(client, auth, state):
    client.post("/leave-requests", json=BODY, headers=auth("e1"))
    before = _row_counts(state)

    response = client.post("/leave-requests", json=BODY, headers=auth("e1"))  # overlaps

    assert response.status_code == 409
    assert _row_counts(state) == before


def test_approval_is_recorded_in_the_ledger(client, auth, state):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]
    client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1"))

    with state.session_factory() as session:
        movements = session.scalars(
            select(db.LeaveLedger.movement)
            .where(db.LeaveLedger.leave_request_id == uuid.UUID(request_id))
            .order_by(db.LeaveLedger.id)
        ).all()

    assert movements == ["RESERVE", "CONSUME"]


def test_balance_endpoint_reads_from_the_database(client, auth, state):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]
    client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1"))

    with state.session_factory() as session:
        used = session.execute(
            text(
                "SELECT b.used FROM leave_balances b"
                " JOIN employees e ON e.id = b.employee_id AND e.tenant_id = b.tenant_id"
                " JOIN leave_types t ON t.id = b.leave_type_id AND t.tenant_id = b.tenant_id"
                " WHERE b.tenant_id = :tenant AND e.code = 'e1' AND t.code = 'ANNUAL'"
            ),
            {"tenant": state.tenant_id},
        ).scalar_one()

    rows = client.get("/employees/e1/balance", headers=auth("e1")).json()
    annual = next(r for r in rows if r["leave_type"] == "ANNUAL")
    assert annual["used"] == float(used) == 3


def _row_counts(state) -> tuple[int, int]:
    with state.session_factory() as session:
        requests = session.scalar(
            select(func.count()).where(db.LeaveRequest.tenant_id == state.tenant_id)
        )
        ledger = session.scalar(
            select(func.count()).where(db.LeaveLedger.tenant_id == state.tenant_id)
        )
    return requests, ledger


def test_a_route_that_fails_after_writing_is_rolled_back(app, state, auth):
    from leavedesk.api.state import StoreDep
    from leavedesk.domain.models import Employee

    def write_then_fail(store: StoreDep):
        store.repository.add_employee(
            Employee(id="ghost", name="Ghost", email="ghost@leavedesk.dev", manager_id="m1")
        )
        raise RuntimeError("something broke after the write")

    app.add_api_route("/write-then-fail", write_then_fail, methods=["POST"])

    response = TestClient(app).post("/write-then-fail")

    assert response.status_code == 500
    assert state.has_employee("ghost") is False


def test_notifications_run_after_the_commit(client, auth, state):
    """A notifier opening its own connection already sees the saved request."""
    seen = []

    class ChecksTheDatabase:
        async def send(self, notification):
            with state.session_factory() as session:
                seen.append(session.scalar(select(func.count()).select_from(db.LeaveRequest)))

    state.extra_notifiers.append(ChecksTheDatabase())

    client.post("/leave-requests", json=BODY, headers=auth("e1"))

    assert seen and all(count >= 1 for count in seen)
