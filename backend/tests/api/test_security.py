"""Day 3, step 5: security. Login lockout, timeouts and safe SQL.

Lockout tests run on both backends. Timeout tests need PostgreSQL.
"""

import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from leavedesk.api.main import create_app
from leavedesk.db import models as db
from leavedesk.db.repository import PostgresLeaveRepository
from tests.api.conftest import PASSWORD, TODAY, error_code
from tests.postgres import requires_postgres

ASHA = "asha@leavedesk.dev"


def login(client, email=ASHA, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


class Clock:
    """A clock the test can move forward."""

    def __init__(self) -> None:
        self.time = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.time


@pytest.fixture
def clock(state) -> Clock:
    clock = Clock()
    state.users.now = clock
    return clock


# Login lockout


def test_five_wrong_passwords_lock_the_account(client, clock):
    for _ in range(5):
        assert login(client, password="wrong-password").status_code == 401

    locked = login(client)  # the right password, but the account is locked

    assert locked.status_code == 401
    # Same message as a wrong password: the response does not reveal the lock.
    assert locked.json()["error"]["message"] == "invalid email or password"


def test_four_wrong_passwords_do_not_lock(client, clock):
    for _ in range(4):
        login(client, password="wrong-password")

    assert login(client).status_code == 200


def test_a_good_login_resets_the_count(client, clock):
    for _ in range(4):
        login(client, password="wrong-password")
    login(client)
    for _ in range(4):
        login(client, password="wrong-password")

    assert login(client).status_code == 200


def test_the_lock_ends_after_15_minutes(client, clock):
    for _ in range(5):
        login(client, password="wrong-password")

    clock.time += timedelta(minutes=14)
    assert login(client).status_code == 401
    clock.time += timedelta(minutes=2)
    assert login(client).status_code == 200


def test_a_lock_only_affects_that_account(client, clock):
    for _ in range(5):
        login(client, password="wrong-password")

    assert login(client, email="kiran@leavedesk.dev").status_code == 200


def test_sql_injection_in_the_email_is_just_a_wrong_login(client):
    for email in ("' OR '1'='1", "asha@leavedesk.dev' --", "x'; DROP TABLE users; --"):
        response = login(client, email=email)
        assert response.status_code in (401, 422)
    assert login(client).status_code == 200  # nothing was dropped


def test_no_sql_is_built_with_f_strings_from_values():
    """Values always go in as bound parameters: text("... :name"), never text(f"...")."""
    package = Path(__file__).resolve().parents[2] / "leavedesk"
    offenders = [
        f"{path.name}:{number}"
        for path in package.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"""\b(text|execute)\(\s*f["']""", line)
    ]

    assert offenders == []


# PostgreSQL only: shared counters and timeouts


@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
@requires_postgres
def test_the_lock_is_shared_by_every_server(settings, client, clock):
    """Counters live in the users table, so another server does not give 5 more tries."""
    for _ in range(5):
        login(client, password="wrong-password")

    other_server = create_app(settings, today=lambda: TODAY)
    try:
        other_server.state.leavedesk.users.now = clock
        assert login(TestClient(other_server)).status_code == 401
    finally:
        other_server.state.leavedesk.close()


@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
@requires_postgres
def test_parallel_guesses_are_all_counted(app, client, state, clock):
    """The users row is locked while checking, so 10 guesses at once lock the account."""
    start = threading.Barrier(10)

    def guess():
        start.wait()
        login(TestClient(app), password="wrong-password")

    threads = [threading.Thread(target=guess) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert login(client).status_code == 401
    with state.session_factory() as session:
        locked_until = session.scalar(
            select(db.User.locked_until)
            .join(db.Employee, db.Employee.id == db.User.employee_id)
            .where(db.User.tenant_id == state.tenant_id, db.Employee.code == "e1")
        )
    assert locked_until is not None


@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
@requires_postgres
def test_every_connection_has_the_timeouts(state):
    with state.engine.connect() as connection:
        shown = {
            name: connection.execute(text(f"SHOW {name}")).scalar()
            for name in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout")
        }

    assert shown == {
        "statement_timeout": "5s",
        "lock_timeout": "2s",
        "idle_in_transaction_session_timeout": "30s",
    }


@pytest.fixture
def quick_timeouts_app(settings):
    quick = settings.model_copy(
        update={"database_lock_timeout_ms": 300, "database_statement_timeout_ms": 300}
    )
    app = create_app(quick, today=lambda: TODAY)
    yield app
    app.state.leavedesk.close()


@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
@requires_postgres
def test_waiting_too_long_for_a_lock_is_503_try_again(quick_timeouts_app, auth):
    app = quick_timeouts_app
    state = app.state.leavedesk
    client = TestClient(app)
    body = {
        "leave_type": "ANNUAL",
        "start_date": "2026-11-16",
        "end_date": "2026-11-18",
        "reason": "Family trip",
    }
    request_id = client.post("/leave-requests", json=body, headers=auth("e1")).json()["id"]

    # Someone else holds the row lock and does not let go.
    with state.session_factory.begin() as session:
        PostgresLeaveRepository(session, state.tenant_id, TODAY.year).get_request(request_id)
        response = client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1"))

    assert response.status_code == 503
    assert error_code(response) == "TRY_AGAIN"
    assert response.headers["retry-after"] == "1"
    # Nothing changed, and once the lock is free the approval works.
    assert (
        client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1")).status_code == 200
    )


@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
@requires_postgres
def test_a_query_that_runs_too_long_is_cancelled(quick_timeouts_app):
    from sqlalchemy.exc import DBAPIError

    from leavedesk.db.errors import sqlstate

    state = quick_timeouts_app.state.leavedesk
    with pytest.raises(DBAPIError) as raised, state.engine.connect() as connection:
        connection.execute(text("SELECT pg_sleep(2)"))

    assert sqlstate(raised.value) == "57014"  # query_canceled
