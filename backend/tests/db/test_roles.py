"""Day 3, step 5: the app's database role can only read and write rows.

The tests switch to leavedesk_app with SET ROLE, then try things the app must
never be able to do. PostgreSQL itself refuses them (SQLSTATE 42501).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from leavedesk.api.main import create_app
from leavedesk.api.settings import Settings
from leavedesk.db.errors import sqlstate
from tests.postgres import requires_postgres

pytestmark = requires_postgres

PASSWORD = "test-password-123"


@pytest.fixture
def as_app(engine):
    """A connection acting as leavedesk_app, rolled back at the end."""
    with engine.connect() as connection:
        connection.execute(text("SET ROLE leavedesk_app"))
        yield connection
        connection.rollback()


def refused(connection, sql: str) -> str | None:
    """Run sql in a savepoint and return the SQLSTATE it failed with, or None."""
    savepoint = connection.begin_nested()
    try:
        connection.execute(text(sql))
    except DBAPIError as error:
        savepoint.rollback()
        return sqlstate(error)
    savepoint.rollback()
    return None


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE leave_requests",
        "ALTER TABLE employees ADD COLUMN salary int",
        "CREATE TABLE stolen (id int)",
        "TRUNCATE notifications",
        "UPDATE leave_ledger SET used_delta = 0",
        "DELETE FROM leave_ledger",
        "DELETE FROM audit_log",
        "TRUNCATE leave_ledger",
        "SELECT * FROM alembic_version",
    ],
)
def test_the_app_role_cannot(as_app, sql):
    assert refused(as_app, sql) == "42501"  # insufficient_privilege


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM employees",
        "SELECT count(*) FROM leave_ledger",
        "UPDATE notifications SET read_at = now() WHERE false",
        "DELETE FROM idempotency_keys WHERE false",
    ],
)
def test_the_app_role_can(as_app, sql):
    assert refused(as_app, sql) is None


def test_the_whole_api_works_as_the_app_role(database_url):
    """Every route the app has, run with only leavedesk_app's privileges."""
    settings = Settings(
        jwt_secret="test-secret-that-is-at-least-32-characters",
        seed_password=PASSWORD,
        database_url=database_url,
        tenant_name="App role tenant",
        _env_file=None,
    )
    app = create_app(settings)  # seeding happens here, as the admin
    state = app.state.leavedesk

    @event.listens_for(state.engine, "connect")
    def act_as_app(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET ROLE leavedesk_app")
        cursor.close()
        dbapi_connection.commit()

    state.engine.dispose()  # new connections from now on, each with SET ROLE
    try:
        client = TestClient(app)

        def token(email):
            body = {"email": email, "password": PASSWORD}
            access = client.post("/auth/login", json=body).json()["access_token"]
            return {"Authorization": f"Bearer {access}"}

        asha, ravi = token("asha@leavedesk.dev"), token("ravi@leavedesk.dev")
        client.post("/auth/login", json={"email": "asha@leavedesk.dev", "password": "nope"})
        with state.engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar() == "leavedesk_app"

        body = {"leave_type": "CASUAL", "start_date": "2026-12-01", "end_date": "2026-12-01"}
        first = client.post(
            "/leave-requests",
            json=body | {"reason": "Bank work"},
            headers=asha | {"Idempotency-Key": "k1"},
        )
        second = client.post(
            "/leave-requests",
            json=body | {"start_date": "2026-12-02", "end_date": "2026-12-02", "reason": "Visit"},
            headers=asha,
        )
        approved = client.post(f"/leave-requests/{first.json()['id']}/approve", headers=ravi)
        cancelled = client.delete(f"/leave-requests/{second.json()['id']}", headers=asha)
        listed = client.get("/notifications", headers=asha)
        read_all = client.post("/notifications/read-all", headers=asha)
        balance = client.get("/employees/e1/balance", headers=asha)

        assert [first.status_code, second.status_code] == [201, 201]
        assert approved.status_code == cancelled.status_code == 200
        assert listed.status_code == read_all.status_code == balance.status_code == 200
    finally:
        state.close()
